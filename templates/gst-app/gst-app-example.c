/* pgmsend.c
 * Heiher <admin@heiher.info>
 * cee1 <fykcee1@gmail.com>
 */

#include <gst/gst.h>
#if 0
#include <gst/pbutils/missing-plugins.h>
#endif

#if (GST_VERSION_MAJOR == 1 && GST_VERSION_MINOR == 0)
#define DECODEBIN    "decodebin"
#define VIDEORAWCAPS "video/x-raw"
#define RTPJITTERBUF "rtpjitterbuffer"
#define RTPSESSION   "rtpsession"
#else
#define DECODEBIN    "decodebin2"
#define VIDEORAWCAPS "video/x-raw-yuv"
#define RTPJITTERBUF "gstrtpjitterbuffer"
#define RTPSESSION   "gstrtpsession"
#endif

#define PIPELINE_DESC_TEMP "filesrc name=filesrc ! " DECODEBIN " name=decoder"

#define VIDEO_JOINTBIN_DESC "capsfilter caps=\"" VIDEORAWCAPS "\" ! timeoverlay ! tee name=videojoint"
#define VIDEO_SENDBIN_DESC  "videoscale ! "                                                    \
	      "capsfilter name=scalefilter caps=\"" VIDEORAWCAPS ",width=320,height=240\" ! "  \
           "x264enc name=videoencoder tune=zerolatency byte-stream=true vbv-buf-capacity=300 " \
           "bframes=0 b-pyramid=true weightb=true me=dia bitrate=1024 key-int-max=48 ! "       \
		            "rtph264pay ! " RTPJITTERBUF " latency=20 ! " RTPSESSION " ! "     \
//			    "pgmsink name=netsink uri=pgm://127.0.0.1:7500:3056"
			    "udpsink name=netsink"

#define VIDEO_PLAYBIN_DESC "autovideosink"
#define VIDEO_BIN_DESC     VIDEO_JOINTBIN_DESC                            \
                           " videojoint. ! queue ! " VIDEO_SENDBIN_DESC   \
                           " videojoint. ! queue ! " VIDEO_PLAYBIN_DESC

#define AUDIO_PLAYBIN_DESC "audioconvert ! audioresample ! volume name=volume_adj ! autoaudiosink"
#define AUDIO_BIN_DESC     AUDIO_PLAYBIN_DESC

#define PIPELINE_DESC      PIPELINE_DESC_TEMP

struct commandOptions
{
    gint width;
    gint height;
    gint bitrate;
    gint key_int_max;
    gchar *uri;
    gchar *location;
};

struct pipelineWrap {
    GstElement *pipeline;
    GMainLoop *main_loop;
    GstState target_state;
    gboolean buffering;
    gboolean is_live;
    gboolean not_sync;
    gboolean eos_on_shutdown; /* Sending an eos to shutdown */
};

static void print_error_message (GstMessage * msg)
{
    GError *err = NULL;
    gchar *name, *debug = NULL;

    name = gst_object_get_path_string (msg->src);
    gst_message_parse_error (msg, &err, &debug);

    g_error ("ERROR: from element %s: %s", name, err->message);
    if (debug != NULL)
        g_error ("Additional debug info:\n%s\n", debug);

    g_error_free (err);
    g_free (debug);
    g_free (name);
}

static void
pipeline_sync_target_state (struct pipelineWrap *pipeline, GstState cur_state)
{
    GstState next_state;
    GstStateChangeReturn ret;

    if (pipeline->target_state == GST_STATE_NULL) {
        if (cur_state == GST_STATE_PLAYING)
            next_state = GST_STATE_PAUSED;
        else if (cur_state == GST_STATE_PAUSED)
            next_state = GST_STATE_READY;
        else
            next_state = GST_STATE_NULL;
    
        if (next_state == GST_STATE_PAUSED) {
            if (pipeline->eos_on_shutdown) {
                g_message ("EOS on shutdown enabled -- Forcing EOS on the pipeline");
    
                pipeline->eos_on_shutdown = FALSE;
                gst_element_send_event (pipeline->pipeline, gst_event_new_eos ());
            } else {
                g_message ("[target_state='%s']Setting pipeline to PAUSED ...",
                           gst_element_state_get_name (pipeline->target_state));
                gst_element_set_state (pipeline->pipeline, GST_STATE_PAUSED);
            }
        }
    
        if (next_state == GST_STATE_READY) {
            g_message ("[target_state='%s']Setting pipeline to READY ...",
                       gst_element_state_get_name (pipeline->target_state));
            gst_element_set_state (pipeline->pipeline, GST_STATE_READY);
        }
    
        if (next_state == GST_STATE_NULL) {
            g_message ("[target_state='%s']Setting pipeline to NULL ...",
                       gst_element_state_get_name (pipeline->target_state));
            gst_element_set_state (pipeline->pipeline, GST_STATE_NULL);
        }

    } else if (pipeline->target_state == GST_STATE_PLAYING) {
        next_state = cur_state == GST_STATE_PAUSED ? GST_STATE_PLAYING : GST_STATE_PAUSED;
    
        if (next_state == GST_STATE_PAUSED) {
            g_message ("[target_state='%s']Setting pipeline to PAUSED ...",
                       gst_element_state_get_name (pipeline->target_state)); 
            ret = gst_element_set_state (pipeline->pipeline, GST_STATE_PAUSED);
    
            switch (ret) {
            case GST_STATE_CHANGE_FAILURE:
                /* post an application specific message */
                gst_element_post_message (GST_ELEMENT (pipeline->pipeline),
                    gst_message_new_application (GST_OBJECT (pipeline->pipeline),
                        gst_structure_new ("pipeline-play-errors",
                            "message", G_TYPE_STRING, "ERROR: Pipeline doesn't want to pause.", NULL)));
                break;
            case GST_STATE_CHANGE_ASYNC:
        	    g_message ("[target_state='%s']Pipeline is PREROLLING ...",
                               gst_element_state_get_name (pipeline->target_state)); 
                break;
    
            case GST_STATE_CHANGE_NO_PREROLL:
        	    g_message ("[target_state='%s']Pipeline is live and does not need PREROLL ...",
                               gst_element_state_get_name (pipeline->target_state)); 
    
        	    pipeline->is_live = TRUE;
                /* fall through */
            case GST_STATE_CHANGE_SUCCESS:
        	    g_message ("[target_state='%s']Pipeline is PREROLLED ...",
                               gst_element_state_get_name (pipeline->target_state)); 
    
        	    break;
            }
        }
    
        if (next_state == GST_STATE_PLAYING) {
            g_message ("[target_state='%s']Setting pipeline to PLAYING ...",
                       gst_element_state_get_name (pipeline->target_state)); 
    
            if (gst_element_set_state (pipeline->pipeline,
                                       GST_STATE_PLAYING) == GST_STATE_CHANGE_FAILURE) {
                gst_element_post_message (GST_ELEMENT (pipeline->pipeline),
                    gst_message_new_application (GST_OBJECT (pipeline->pipeline),
                        gst_structure_new ("pipeline-play-errors",
                            "message", G_TYPE_STRING, "ERROR: Pipeline doesn't want to play.", NULL)));
            }
        }

    } else if (pipeline->target_state == GST_STATE_PAUSED) {
        g_message ("[target_state='%s']Setting pipeline to PAUSED ...",
                   gst_element_state_get_name (pipeline->target_state)); 
        gst_element_set_state (pipeline->pipeline, GST_STATE_PAUSED);
    }
}

static void
pipeline_set_target_state (struct pipelineWrap *pipeline, GstState target_state)
{
    GstState curr, pending;
    GstStateChangeReturn ret;

    if (target_state == pipeline->target_state) {
        g_warning ("%s() Already in target state %s", __func__,
                   gst_element_state_get_name (target_state));
        return;
    }

    pipeline->target_state = target_state;
    pipeline->not_sync = TRUE;

    ret = gst_element_get_state (pipeline->pipeline, &curr, &pending, 0);
    if (ret == GST_STATE_CHANGE_ASYNC) {
        g_debug ("Setting target state to %s:"
                 "Stop here because still in state change(%s pending) ",
                 gst_element_state_get_name (target_state),
                 gst_element_state_get_name (pending));
        return;
    }

    g_debug ("Setting target state to %s: pipeline is %s%s",
             gst_element_state_get_name (target_state),
             gst_element_state_get_name (curr),
                 ret == GST_STATE_CHANGE_FAILURE ? \
                 " and last state change failed" : "");
                                         
    pipeline_sync_target_state (pipeline, curr);

}

gboolean set_playing (struct pipelineWrap *pipeline)
{
    pipeline_set_target_state (pipeline, GST_STATE_PLAYING);

    return FALSE;
}

gboolean set_stop (struct pipelineWrap *pipeline)
{
    pipeline_set_target_state (pipeline, GST_STATE_NULL);

    return FALSE;
}

gboolean set_pause_play (struct pipelineWrap *pipeline)
{
    pipeline_set_target_state (pipeline, GST_STATE_PAUSED);

    return FALSE;
}


static void bus_message_handler (GstBus *bus,
            GstMessage *message, gpointer user_data)
{
    struct pipelineWrap *pipeline = (struct pipelineWrap *)user_data;

    g_debug ("Bus: received a %s message, from %s",
             gst_message_type_get_name (GST_MESSAGE_TYPE (message)),
             GST_MESSAGE_SRC_NAME (message));

    switch (GST_MESSAGE_TYPE (message))
    {
    case GST_MESSAGE_EOS:
        {
            GstState curr, pending;
            GstStateChangeReturn ret;

            ret = gst_element_get_state (pipeline->pipeline, &curr, &pending, 0);
            g_message ("Got EOS from element \"%s\", "
                       "pipeline(get state returns %s):%s(%s pending).",
                       GST_MESSAGE_SRC_NAME (message),
                       gst_element_state_change_return_get_name (ret),
                       gst_element_state_get_name (curr),
                       gst_element_state_get_name (pending));

            set_stop (pipeline);
            break;
        }
    case GST_MESSAGE_NEW_CLOCK:
        {
            GstClock *clock;

            gst_message_parse_new_clock (message, &clock);

            g_message ("New clock: %s", (clock ? GST_OBJECT_NAME (clock) : "NULL"));
            break;
        }

    case GST_MESSAGE_CLOCK_LOST:
        g_message ("Clock lost, selecting a new one");
        gst_element_set_state (pipeline->pipeline, GST_STATE_PAUSED);
        gst_element_set_state (pipeline->pipeline, GST_STATE_PLAYING);

        break;

    case GST_MESSAGE_INFO:
        {
            GError *gerror;
            gchar *debug;
            gchar *name = gst_object_get_path_string (GST_MESSAGE_SRC (message));

            gst_message_parse_info (message, &gerror, &debug);
            if (debug) {
                g_message ("INFO:%s", debug);
            }
            g_error_free (gerror);
            g_free (debug);
            g_free (name);
            break;
        }

    case GST_MESSAGE_WARNING:
        {
            GError *gerror;
            gchar *debug;
            gchar *name = gst_object_get_path_string (GST_MESSAGE_SRC (message));

            /* dump graph on warning */
            GST_DEBUG_BIN_TO_DOT_FILE_WITH_TS (GST_BIN (pipeline),
                GST_DEBUG_GRAPH_SHOW_ALL, "gst-launch.warning");

            gst_message_parse_warning (message, &gerror, &debug);
            g_warning ("WARNING: from element %s: %s", name, gerror->message);
            if (debug) {
                g_warning ("Additional debug info:\n%s", debug);
            }
            g_error_free (gerror);
            g_free (debug);
            g_free (name);
            break;
        }

    case GST_MESSAGE_ERROR:
        {
            /* dump graph on error */
            GST_DEBUG_BIN_TO_DOT_FILE_WITH_TS (GST_BIN (pipeline),
                GST_DEBUG_GRAPH_SHOW_ALL, "gst-launch.error");

            print_error_message (message);

            g_main_loop_quit (pipeline->main_loop);
            break;
        }

    case GST_MESSAGE_STATE_CHANGED:
        {
            GstState old, new, pending;

            /* we only care about pipeline state change messages */
            if (GST_MESSAGE_SRC (message) != GST_OBJECT_CAST (pipeline->pipeline))
                break;

            /* ignore when we are buffering since then we mess with the states
             * ourselves. */
            if (pipeline->buffering) {
                g_message ("Prerolled, waiting for buffering to finish...");
                break;
            }

            gst_message_parse_state_changed (message, &old, &new, &pending);

            g_debug ("Bus: pipeline state changed from %s to %s (%s pending)",
                     gst_element_state_get_name (old),
                     gst_element_state_get_name (new),
                     gst_element_state_get_name (pending));

            if (pending) /* skip intermediate states */
                break;

            if (pipeline->target_state == new) {
                pipeline->not_sync = FALSE;

#if 0
                /* No GST_STATE_NULL will be received ...*/
                if (pipeline->target_state == GST_STATE_NULL) {
                    g_main_loop_quit (pipeline->main_loop);
                    break;
                }
#endif
            }
            if (pipeline->not_sync)
                pipeline_sync_target_state (pipeline, new);

            /* else not an interesting message */
            break;
        }
    case GST_MESSAGE_BUFFERING:
        {
            gint percent;

            gst_message_parse_buffering (message, &percent);
            g_message ("%s %d%%  \r", "buffering...", percent);

            /* no state management needed for live pipelines */
            if (pipeline->is_live)
                break;

            if (percent == 100) {
                /* a 100% message means buffering is done */
                pipeline->buffering = FALSE;

                /* if the desired state is playing, go back */
                if (pipeline->target_state == GST_STATE_PLAYING) {
                    g_message ("Done buffering, setting pipeline to PLAYING ...");
                    gst_element_set_state (pipeline->pipeline, GST_STATE_PLAYING);
                }
            } else {
                /* buffering busy */
                if (pipeline->buffering == FALSE &&
                    pipeline->target_state == GST_STATE_PLAYING) {
                    /* we were not buffering but PLAYING, PAUSE  the pipeline. */
                    g_message ("Buffering, setting pipeline to PAUSED ...");
                    gst_element_set_state (pipeline->pipeline, GST_STATE_PAUSED);
                }
                pipeline->buffering = TRUE;
            }
            break;
        }
    case GST_MESSAGE_LATENCY:
        {
            g_message ("Redistribute latency...");
            gst_bin_recalculate_latency (GST_BIN (pipeline->pipeline));
            break;
        }
    case GST_MESSAGE_REQUEST_STATE:
        {
            GstState state;
            gchar *name = gst_object_get_path_string (GST_MESSAGE_SRC (message));

            gst_message_parse_request_state (message, &state);

            g_message ("Setting state to %s as requested by %s...",
                       gst_element_state_get_name (state), name);

            gst_element_set_state (pipeline->pipeline, state);

            g_free (name);
            break;
        }
    case GST_MESSAGE_APPLICATION:
        {
            const GstStructure *s;

            s = gst_message_get_structure (message);

            if (gst_structure_has_name (s, "pipeline-play-errors")) {
                g_error ("%s", gst_structure_get_string (s, "message"));
                g_main_loop_quit (pipeline->main_loop);
            }
            break;
        }
#if 0
    case GST_MESSAGE_ELEMENT:
        {
            if (gst_is_missing_plugin_message (message)) {
                const gchar *desc;

                desc = gst_missing_plugin_message_get_description (message);
                g_warning ("Missing element: %s", desc ? desc : "(no description)");
            }
            break;
        }
#endif
    default:
        /* just be quiet by default */
        break;
    }
}

static void pad_added_handler (GstElement *element,
            GstPad *pad, gpointer user_data)
{
    GstBin *pipeline = GST_BIN (user_data);
#if (GST_VERSION_MAJOR == 1 && GST_VERSION_MINOR == 0)
    /* FIXME: workaround from brasero, brasero_metadata_new_decoded_pad_cb
     * get_current_caps() doesn't always seem to work yet here 
     */
    GstCaps *padcaps = gst_pad_query_caps (pad, NULL);
#else
    GstCaps *padcaps = gst_pad_get_caps (pad);
#endif
    GstStructure *s = gst_caps_get_structure (padcaps, 0);

    GstElement *newbin = NULL;
    GstPad *sink;
    struct commandOptions *opts = g_object_get_data (G_OBJECT (pipeline), "cmd_opts");

    GError *gerror = NULL;

    if (g_str_has_prefix (gst_structure_get_name (s), "video")) {
        GstElement *videobin = gst_parse_bin_from_description (VIDEO_BIN_DESC, TRUE, &gerror);

        if (gerror) {
            if (!videobin)
                g_error ("Failed to create videobin: %s <== '" VIDEO_BIN_DESC "'",
                         gerror->message);
            else
                g_warning ("Fixed syntax error: %s <== '" VIDEO_BIN_DESC "'",
                           gerror->message);
            g_clear_error (&gerror);
        } else
            g_debug ("video pad-added, build our video pipeline: '" VIDEO_BIN_DESC "'");

	if (!videobin)
            goto out;

	{
            GstElement *e = NULL;

            /* Setting up scale */
            if (opts->width && opts->height) {
                GstCaps *caps = NULL;

                e = gst_bin_get_by_name (GST_BIN (videobin), "scalefilter");

                caps = gst_caps_new_simple ("video/x-raw-yuv",
                                            "width", G_TYPE_INT, opts->width,
                                            "height", G_TYPE_INT, opts->height,
                                            NULL);
                g_object_set (G_OBJECT (e), "caps", caps, NULL);

                gst_object_unref (caps);
                gst_object_unref (e);
            }

            /* Setting up video encoder */
            if (opts->bitrate || opts->key_int_max) {
                e = gst_bin_get_by_name (GST_BIN (videobin), "videoencoder");

                if (opts->bitrate)
                    g_object_set (G_OBJECT (e), "bitrate", opts->bitrate, NULL);

                if (opts->key_int_max)
                    g_object_set (G_OBJECT (e), "key-int-max", opts->key_int_max, NULL);

                gst_object_unref (e);
            }

            /* Setting up broadcast uri */
            if (opts->uri) {
                e = gst_bin_get_by_name (GST_BIN (videobin), "netsink");
                g_object_set (G_OBJECT (e), "uri", opts->uri, NULL);
                gst_object_unref (e);
            }
        }

        newbin = videobin;
    } else if (g_str_has_prefix (gst_structure_get_name (s), "audio")) {
        GstElement *audiobin = gst_parse_bin_from_description (AUDIO_BIN_DESC, TRUE, &gerror);

        if (gerror) {
            if (!audiobin)
                g_error ("Failed to create audiobin: %s <== '" AUDIO_BIN_DESC "'",
                         gerror->message);
            else
                g_warning ("Fixed syntax error: %s <== '" AUDIO_BIN_DESC "'",
                           gerror->message);
            g_clear_error (&gerror);
        } else
            g_debug ("audio pad-added, build our audio pipeline: '" AUDIO_BIN_DESC "'");

	if (!audiobin)
            goto out;
        {
            GstElement *e = gst_bin_get_by_name (GST_BIN (audiobin), "volume_adj");
            /* Attach to volume adjuster here */
            gst_object_unref (e);
        }

        newbin = audiobin;
    }

    gst_element_set_state (newbin, GST_STATE_PAUSED);
#if 0
    /* some element maybe blocked here */
    gst_element_get_state (newbin, NULL, NULL, GST_CLOCK_TIME_NONE);
#endif
    gst_bin_add (pipeline, newbin);
    sink = gst_element_get_static_pad (newbin, "sink");
    gst_pad_link (pad, sink);
    gst_object_unref (sink);

out:
    gst_caps_unref (padcaps);
}

int main (int argc, char *argv[])
{
    GMainLoop *main_loop = NULL;
    GstElement *pipeline = NULL;
    GstElement *e = NULL;
    GError *gerror = NULL;
    struct commandOptions opts = { 0, };
    struct pipelineWrap pipeline_wrap = { 0, };
    GOptionEntry option_entries[] = 
    {
        { "location", 'l', 0, G_OPTION_ARG_STRING, &opts.location, "Media file location", NULL },
        { "width", 'w', 0, G_OPTION_ARG_INT, &opts.width, "Video width", NULL },
        { "height", 'h', 0, G_OPTION_ARG_INT, &opts.height, "Video height", NULL },
        { "bitrate", 'b', 0, G_OPTION_ARG_INT, &opts.bitrate, "Bitrate", NULL },
        { "key-int-max", 'm', 0, G_OPTION_ARG_INT, &opts.key_int_max, "Maximal distance between two key-frames", NULL },
        { "uri", 'u', 0, G_OPTION_ARG_STRING, &opts.uri, "URI", NULL },
        { NULL }
    };
    GOptionContext *context = NULL;
    GError *err = NULL;
    GstBus *bus = NULL;

    main_loop = g_main_loop_new (NULL, FALSE);

    context = g_option_context_new ("");
    g_option_context_add_main_entries (context, option_entries, NULL);
    if (!g_option_context_parse (context, &argc, &argv, &err)) {
        g_error ("Option parsing failed: %s", err->message);
        g_error_free (err);
    }
    g_option_context_free (context);

    gst_init (&argc, &argv);

    pipeline = gst_parse_launch (PIPELINE_DESC, &gerror);
    if (gerror) {
        if (!pipeline)
            g_error ("Failed to create pipeline: %s <== '" PIPELINE_DESC "'", gerror->message);
        else
            g_warning ("Fixed syntax error: %s <== '" PIPELINE_DESC "'", gerror->message);
        g_clear_error (&gerror);
    }

    if (!pipeline)
        goto quit;

    pipeline_wrap.pipeline = pipeline;
    pipeline_wrap.main_loop = main_loop;

    /* attach extra user specified options */
    g_object_set_data (G_OBJECT (pipeline), "cmd_opts", &opts);

    /* set bus listener */
    bus = gst_pipeline_get_bus (GST_PIPELINE (pipeline));
    g_signal_connect (G_OBJECT (bus), "message",
                      G_CALLBACK (bus_message_handler), &pipeline_wrap);
    gst_bus_add_signal_watch (bus);
    gst_object_unref (bus);

    /* set catching "pad-added" signal of decoder */
    e = gst_bin_get_by_name (GST_BIN (pipeline), "decoder");
    g_signal_connect (G_OBJECT (e), "pad-added",
                      G_CALLBACK (pad_added_handler), pipeline);
    gst_object_unref (e);

    /* set media file location */
    e = gst_bin_get_by_name (GST_BIN (pipeline), "filesrc");
    g_object_set (G_OBJECT (e), "location", opts.location, NULL);
    gst_object_unref (e);

    g_idle_add ((GSourceFunc) set_playing, &pipeline_wrap);
    g_main_loop_run (main_loop);

quit:
    if (pipeline) {
        gst_element_set_state (pipeline, GST_STATE_NULL);
        gst_object_unref (pipeline);
    }

    g_main_loop_unref (main_loop);
    g_free (opts.uri);
    g_free (opts.location);

    gst_deinit ();

    return 0;
}

