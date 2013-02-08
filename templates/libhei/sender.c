#include <string.h>
#include <gio/gio.h>

#include "internal.h"

typedef struct _Private Private;

struct _Private
{
	GSocket *socket;

	HeiPacket *pending_packet;
	GQueue squeue;

	GMutex nf_mutex;
	GCond nf_cond;
	GThread *nf_thread;
	gboolean quit_thread;

	guint wid;
	guint seq;

	guint rl_bytes_sent;
	GTimer *rl_timer;
};

static void push_new_data (Private *priv, void *new_data, guint new_data_size)
{
	if (new_data_size > G_MAXUINT16)
		g_error ("New data too large!");

	if (new_data) {
		guint16 bytes_written;
		guint16 offset = 0;
		GQueue tmp = G_QUEUE_INIT;
		HeiPacket *pending_packet = priv->pending_packet;
		gboolean has_more;

again:
		if (!pending_packet)
			pending_packet = hei_packet_new ();

		bytes_written = hei_packet_write (pending_packet, 
						  new_data,
						  offset,
						  new_data_size);

		offset += bytes_written;
		has_more = offset < new_data_size;
		if (has_more || HEI_PACKET_IS_FULL (pending_packet)) {
			g_queue_push_tail_link (&tmp, (GList *) pending_packet);
			pending_packet = NULL;

			if (has_more)
				goto again;
		}

		priv->pending_packet = pending_packet;
		if (tmp.head) {
				g_mutex_lock (&priv->nf_mutex);
				my_g_queue_concat (&priv->squeue, &tmp);
				g_cond_signal (&priv->nf_cond);
				g_mutex_unlock (&priv->nf_mutex);
		}
	}

}

static gssize send_to_rate_limited (Private *priv,
				    GSocketAddress *address,
				    gpointer data,
				    gsize data_size,
				    GError **error)
{
	gulong time_elapsed = 0;
	gulong timesleep = 0;

	g_timer_elapsed (priv->rl_timer, &time_elapsed); 

	if (priv->rl_bytes_sent >= RATE_LIMIT_BYTES_PER_CYCLE &&
	    time_elapsed <= RATE_LIMIT_CYCLE * 1000)
		/* round to 1ms */
		timesleep = (RATE_LIMIT_CYCLE * 1000 - time_elapsed)/1000 * 1000;

	if (timesleep) {
		g_debug ("%s(): Sent %uB in %lums%luus,exceed ratelimit, will sleep %lums",
			 __func__, priv->rl_bytes_sent,
			time_elapsed/1000, time_elapsed%1000, timesleep/1000);
		g_usleep (timesleep);
	}

	if (timesleep || time_elapsed >= RATE_LIMIT_CYCLE * 1000) {
		priv->rl_bytes_sent = 0;
		g_timer_start (priv->rl_timer);
	}

	priv->rl_bytes_sent += data_size;
	return g_socket_send_to (priv->socket, address,
				 data, data_size,
				 NULL, error);
}

static gpointer
nf_thread_handler (gpointer user_data)
{
	Private *priv = user_data;

	/* Network settings */
	GSocketAddress *saddr = NULL;
	gboolean running = TRUE;

	saddr = make_sock_addr (TARGET_ADDRESS_DEFAULT, TARGET_PORT_DEFAULT);
	g_assert (saddr);

	while (running) {
		GQueue to_send;
		GList *iter;

		g_mutex_lock (&priv->nf_mutex);
		while (!priv->squeue.head && !priv->quit_thread)
			g_cond_wait (&priv->nf_cond, &priv->nf_mutex);

		to_send = priv->squeue;
		g_queue_init (&priv->squeue);
		running = !priv->quit_thread;
		g_mutex_unlock (&priv->nf_mutex);

		for (iter = to_send.head; iter;) {
			HeiPacket *packet = (HeiPacket *) iter;

			packet->wid = priv->wid;
			packet->seq = priv->seq;
			NEXT_SEQ_WID (priv->wid, priv->seq, N_KPACKETS);

			send_to_rate_limited (priv, saddr,
					      HEI_PACKET_PACK (packet),
					      packet->size_filled,
					      NULL);

			iter = iter->next;
			hei_packet_unref (packet);
		}
	}

	g_object_unref (saddr);

	return NULL;
}

static void priv_free (Private *priv)
{
	if (!priv)
		return;

	g_mutex_lock (&priv->nf_mutex);
	priv->quit_thread = TRUE;
	g_cond_signal (&priv->nf_cond);
	g_mutex_unlock (&priv->nf_mutex);

	if (priv->nf_thread)
		g_thread_join (priv->nf_thread);

	if (priv->socket)
		g_object_unref (priv->socket);

	if (priv->rl_timer)
		g_timer_destroy (priv->rl_timer);

	if (priv->pending_packet)
		hei_packet_unref (priv->pending_packet);

	g_queue_init (&priv->squeue);

	g_cond_clear (&priv->nf_cond);
	g_mutex_clear (&priv->nf_mutex);

	memset (priv, 0, sizeof(Private));
	g_free (priv);
}

Private *do_setup (GError **error)
{
	Private *priv = NULL;

	priv = g_new0 (Private, 1);

	g_mutex_init (&priv->nf_mutex);
	g_cond_init (&priv->nf_cond);

	g_queue_init (&priv->squeue);

	{
		GSocketAddress *saddr = NULL;
		gboolean r;

		/* Setup socket & binding */
		priv->socket = g_socket_new (G_SOCKET_FAMILY_IPV4, G_SOCKET_TYPE_DATAGRAM,
					     G_SOCKET_PROTOCOL_UDP, error);
		if (!priv->socket)
			goto failed;

		saddr = make_sock_addr (SOURCE_ADDRESS, SOURCE_PORT);

		r = g_socket_bind (priv->socket, saddr, TRUE, error);

		g_object_unref (saddr);

		if (!r)
			goto failed;

		g_assert ((priv->rl_timer = g_timer_new ()));
	}

	priv->nf_thread = g_thread_try_new ("nf-thread",
					    nf_thread_handler, priv,
					    error);
	if (!priv->nf_thread)
		goto failed;

	return priv;

failed:
	priv_free (priv);
	return NULL;
}

int
main (int argc, char *argv[])
{
	GError *error = NULL;
	GMainLoop *main_loop = NULL;
	Private *priv = NULL;
	int ret_code = -1;


	main_loop = g_main_loop_new (NULL, FALSE);
	if (!main_loop) {
		g_critical ("Create main loop failed!");
		goto out;
	}

	priv = do_setup (&error);
	if (!priv) {
		g_critical ("Failed to setup: %s", error->message);
		g_clear_error (&error);
		goto out;
	}

	g_message ("Starting ...");
	g_main_loop_run (main_loop);
	ret_code = 0;

out:
	if (priv)
		priv_free (priv);

	if (main_loop)
		g_main_loop_unref (main_loop);

	return ret_code;
}
