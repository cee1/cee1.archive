#include <string.h>
#include <gio/gio.h>

#include "internal.h"

typedef struct _Private Private;

struct _Private
{
	GSocket *socket;

	/* io thread */
	GMainLoop *io_loop;
	GThread *io_thread;
	GSource *socket_source;
	GSource *oq_timeout_source;

	GQueue oqueue;
	GMutex oq_mutex;
	GCond oq_cond;
	gint oq_open_window;

	gboolean quit_thread;
	GQueue squeue;
	gint sq_open_window;
	gint sq_order;
	HeiPacket *packets_received[N_WINPACKETS];
	gint n_packets_received;
	DecodeHeiPacketContext dhpc;

	GThread *feed_thread;
};

static void push_buffer (gpointer buffer, gpointer push_to_who)
{
	/* submit a buffer here */
}

static void squeue_handler_pass2 (Private *priv)
{
	HeiPacket *p;
	GList *iter;
	DecodeHeiPacketContext *dhpc = &priv->dhpc;
	GQueue rqueue = G_QUEUE_INIT;
	guint next_seq;
	gint i, j;

	/* TODO
 	 * Here can adds some fec recovering routine if needed
	 * */

	/* if has recovered data && */
	if (priv->sq_order != -1) /* no out of order packets */
		goto cleanup;

	/* pass2: have lost and success to recover, or out of order */
#ifdef MY_DEBUG
	my_msg_append ("old_stack: ");
	debug_queue (&dhpc->old_stack);
#endif

	/* fill rqueue */
	if (dhpc->old_stack.head) {
		my_g_queue_concat (&rqueue, &dhpc->old_stack);
		g_queue_init (&dhpc->old_stack);
	}

	for (i = 0, j = 0; i < N_KPACKETS; i++) {
		if ((p = priv->packets_received[i])) {
			if (p == (HeiPacket *) dhpc->stack.head) {
				/* move packets in stack to rqueue
				 * note: packets in stack should in order */
				g_queue_push_tail_link (&rqueue,
				 g_queue_pop_head_link (&dhpc->stack));
			} else if (p->tag) {/* partially processed packets */
				hei_packet_ref (p);
				g_queue_push_tail_link (&rqueue, (GList *) p);
			}
		}
	} 
	if (1 /* The dhpc stack is changed, 
	       * that has received at least one orig packet */ ) {
		g_assert (!dhpc->stack.head);
		dhpc->n_fragments = 0;
		dhpc->total_fragments_size = 0;
	}
	next_seq = dhpc->next_seq;

#ifdef MY_DEBUG
	for (i = 0, p = (HeiPacket *) rqueue.head;
		 p; p = (HeiPacket *) ((GList *) p)->next) {
		 my_msg_append ("[%d] %s", i++,
				!p->n_tl ? "(recover)" : "");
		 debug_hei_packet (p);
	}
	my_msgbuffer_flush (G_LOG_LEVEL_DEBUG);
#endif

	while ((p = (HeiPacket *) g_queue_pop_head_link (&rqueue)))
		decode_hei_packet (p,
				   dhpc,
				   push_buffer, NULL /* push to who */,
				   2);

	dhpc->next_seq = MAX (dhpc->next_seq, next_seq);

cleanup:
	/* cleanup: whether pass2 has ran or not */
	for (iter = dhpc->stack.head; iter; iter = iter->next)
		((HeiPacket *) iter)->tag = 0;

	while ((p = (HeiPacket *) g_queue_pop_head_link (&dhpc->old_stack)))
		hei_packet_unref (p);

	for (i = 0; i < N_WINPACKETS; i++)
		if ((p = priv->packets_received[i]))
			hei_packet_unref (p);

	memset (priv->packets_received, 0, sizeof (priv->packets_received));
	priv->n_packets_received = -1;
	priv->sq_order = 0;
}

static void squeue_handler (Private *priv)
{
	HeiPacket *packet = (HeiPacket *) priv->squeue.head; 
	DecodeHeiPacketContext *dhpc = &priv->dhpc;

	if (!packet)
		return;

	if (priv->sq_open_window == -1)
		priv->sq_open_window = packet->wid;
 
	while ((packet = (HeiPacket *) priv->squeue.head) &&
		   packet->wid == priv->sq_open_window &&
		   packet->tag != G_MAXUINT32 /* notify a flush */) {
		packet = (HeiPacket *) g_queue_pop_head_link (&priv->squeue);

		if (priv->packets_received[packet->seq] ||
			priv->n_packets_received < 0) {
			/* Drop duplicated and redundant packet */
			hei_packet_unref (packet);
			continue;
		}

		priv->packets_received[packet->seq] = packet;
		hei_packet_ref (packet);
		priv->n_packets_received++;

		if (HEI_PACKET_IS_FEC (packet)) {
			hei_packet_unref (packet);
			continue;
		}

		if (priv->sq_order >= 0) /* original packets: are they in order */
			priv->sq_order = packet->seq >= priv->sq_order ?
					 packet->seq : -1;

		decode_hei_packet (packet,
				   dhpc,
				   push_buffer, NULL /* push to who */,
				   1);

		/* Received enough packets */
		if (priv->n_packets_received == N_PACKETS_ENOUGH) {
			packet = NULL;
			break;
		}
	}

	if (priv->n_packets_received >= 0 &&
	    (packet || priv->n_packets_received == N_PACKETS_ENOUGH)) {

#ifdef MY_DEBUG
		my_msg_append ("Wid=%d(got %d packets) enter pass2 because %s\n",
			       priv->sq_open_window, priv->n_packets_received,
			       packet ? "window closed" : "received enough packets");

		my_msgbuffer_flush (G_LOG_LEVEL_DEBUG);
#endif

		squeue_handler_pass2 (priv);
	}

	if (packet) { /* packet != NULL: window closed */
		g_debug ("%s: Wid=%d closed because %s(wid=%d)\n",
			 __func__, priv->sq_open_window,
			 packet->tag == G_MAXUINT32 ?
			 "Got a flush packet" : "Got a packet", packet->wid);

		if (packet->tag == G_MAXUINT32) {/* drop a flush packet */
			g_queue_unlink (&priv->squeue, (GList *) packet);
			hei_packet_unref (packet);
		}

		priv->n_packets_received = 0;
		priv->sq_open_window = -1;
	}
}

static gpointer feed_thead_handler (gpointer user_data)
{
	Private *priv = user_data;
	gboolean running = TRUE;

	while (running) {
		g_mutex_lock (&priv->oq_mutex);
		while (!priv->oqueue.head && !priv->quit_thread)
			g_cond_wait (&priv->oq_cond, &priv->oq_mutex);

		if (priv->oqueue.head) {
			HeiPacket *h, *t;

			h = (HeiPacket *) priv->oqueue.head;
			t = (HeiPacket *) priv->oqueue.tail;

			g_debug ("Feed thread: Drain %d packets(head@%p(wid=%d,seq=%d) "
				 "tail@%p(wid=%d,seq=%d) from oqueue",
				 priv->oqueue.length,
				 h, h->wid, h->seq, t, t->wid, t->seq);

			my_g_queue_concat (&priv->squeue, &priv->oqueue);
			g_queue_init (&priv->oqueue);
		}

		running = !priv->quit_thread;
		g_mutex_unlock (&priv->oq_mutex);

		while (priv->squeue.head)
			squeue_handler (priv);
	}

	return NULL;
}

static gboolean
sock_timeout (gpointer user_data)
{
	Private *priv = user_data;

	HeiPacket *flush = hei_packet_new_with_real_data (
			   priv->oq_open_window, 0, NULL, NULL);
	flush->tag = G_MAXUINT32;

	g_mutex_lock (&priv->oq_mutex);
	g_queue_push_tail_link (&priv->oqueue, (GList *) flush);
	g_message ("%s", "socket: timeout pushed a flush packet, unset oq_open_window");
	g_cond_signal (&priv->oq_cond);
	g_mutex_unlock (&priv->oq_mutex);

	priv->oq_open_window = -1;
	priv->oq_timeout_source = NULL;

	return FALSE;
}
static gboolean
sock_in_handler (GSocket *socket,
			GIOCondition condition,
			gpointer user_data)
{
	Private *priv = user_data;
	HeiPacket *packet = hei_packet_new ();
	GSource *timeout_source;
	gssize s = 0;

	s = g_socket_receive_from (priv->socket, NULL,
				   HEI_PACKET_DATA (packet), HEI_PACKET_PACKED_SIZE,
				   NULL, NULL);

	if (priv->oq_timeout_source)
		g_source_destroy (priv->oq_timeout_source);
	timeout_source = g_timeout_source_new (WIN_TIMEOUT);
	g_source_set_callback (timeout_source, sock_timeout, priv, NULL);
	g_source_attach (timeout_source,
					 g_main_loop_get_context (priv->io_loop));
	priv->oq_timeout_source = timeout_source;
	g_source_unref (timeout_source);

	if (-1 == s) {
		goto quit;
	} else if (0 == s) {
		goto quit;
	} else {
		gint distance;

		if (!hei_packet_unpack (packet, (guint16) s))
			goto quit;

		if (packet->seq >= N_WINPACKETS)
			goto quit;

		if (priv->oq_open_window == -1) {
			priv->oq_open_window = packet->wid;
			g_message ("socket: Initail Wid=%d", packet->wid);
	}

		distance = WID_CMP (packet->wid, priv->oq_open_window);
		if (distance) {
			if (distance < 0 && ABS (distance) < WIN_LATE_MAX + 1) {
				g_message ("socket: drop packet(wid=%d,seq=%d), "
					   "because is early than current wid=%d",
					   packet->wid, packet->seq, priv->oq_open_window);
				goto quit;
			}
			g_debug ("socket: move wid from %d to %d (distance=%d)",
				 priv->oq_open_window, packet->wid, distance);
			priv->oq_open_window = packet->wid;
		}

		g_mutex_lock (&priv->oq_mutex);
		g_queue_push_tail_link (&priv->oqueue, (GList *) packet);
		g_cond_signal (&priv->oq_cond);
		g_mutex_unlock (&priv->oq_mutex);
	}

	return TRUE;

quit:
	hei_packet_unref (packet);

	return TRUE;
}

static void priv_free (Private *priv)
{
	if (!priv)
		return;

	g_mutex_lock (&priv->oq_mutex);
	priv->quit_thread = TRUE;
	g_cond_signal (&priv->oq_cond);
	g_mutex_unlock (&priv->oq_mutex);

	if (priv->io_loop)
		g_main_loop_quit (priv->io_loop);

	if (priv->feed_thread)
		g_thread_join (priv->feed_thread);

	if (priv->io_thread)
		g_thread_join (priv->io_thread);

	if (priv->socket_source)
		g_source_destroy (priv->socket_source);

	if (priv->oq_timeout_source)
		g_source_destroy (priv->oq_timeout_source);

	if (priv->socket) {
		GInetAddress *iaddr;
		GError *error = NULL;


		iaddr = g_inet_address_new_from_string (TARGET_ADDRESS_DEFAULT);
		if (g_inet_address_get_is_multicast (iaddr)) {
			if (!g_socket_leave_multicast_group (priv->socket, iaddr,
							     FALSE, NET_IF, &error)) {
				g_critical ("Leave multicast failed: %s", error->message);
				g_clear_error (&error);
			}
		}
		if (iaddr)
			g_object_unref (iaddr);

		g_object_unref (priv->socket);
	}

	if (priv->io_loop)
		g_main_loop_unref (priv->io_loop);

	{
		guint i;
		for (i = 0; i < G_N_ELEMENTS (priv->packets_received); i++)
			if (priv->packets_received[i])
				hei_packet_unref (priv->packets_received[i]);
	}

#define QUEUE_CLEAR(q) G_STMT_START {                       \
	if (g_queue_peek_head ((q)))                        \
		while (g_queue_peek_head ((q))) {           \
			HeiPacket *packet = (HeiPacket *)   \
				g_queue_pop_head_link ((q));\
			hei_packet_unref (packet);          \
		}                                           \
	g_queue_init ((q));                                 \
} G_STMT_END

	QUEUE_CLEAR (&priv->dhpc.old_stack);
	QUEUE_CLEAR (&priv->dhpc.stack);
	QUEUE_CLEAR (&priv->squeue);
	QUEUE_CLEAR (&priv->oqueue);

	g_cond_clear (&priv->oq_cond);
	g_mutex_clear (&priv->oq_mutex);

	memset (priv, 0, sizeof(Private));
	g_free (priv);
}

Private *do_setup (GError **error)
{
	Private *priv = NULL;
	GMainContext *io_context = NULL;

	priv = g_new0 (Private, 1);

	g_mutex_init (&priv->oq_mutex);
	g_cond_init (&priv->oq_cond);
	g_queue_init (&priv->oqueue);
	g_queue_init (&priv->squeue);
	g_queue_init (&priv->dhpc.stack);
	g_queue_init (&priv->dhpc.old_stack);

	io_context = g_main_context_new ();
	priv->io_loop = g_main_loop_new (io_context, TRUE);
	g_main_context_unref (io_context);
	priv->io_thread = g_thread_try_new ("io-thread",
					    (GThreadFunc) g_main_loop_run,
					    priv->io_loop, 
					    error);
	if (!priv->io_thread)
		goto failed;


	{
		GSocketAddress *saddr;
		GInetAddress *miaddr;
		GSource *source = NULL;
		gboolean r;

		priv->socket = g_socket_new (G_SOCKET_FAMILY_IPV4,
					     G_SOCKET_TYPE_DATAGRAM,
					     G_SOCKET_PROTOCOL_UDP, error);
		if (!priv->socket)
			goto failed;

		g_socket_set_blocking (priv->socket, FALSE);

		saddr = make_sock_addr ("0.0.0.0", TARGET_PORT_DEFAULT);
		if (!saddr)
			goto failed;

		r = g_socket_bind (priv->socket, saddr, TRUE, error);
		g_object_unref (saddr);

		if (!r)
			goto failed;

		miaddr = g_inet_address_new_from_string (TARGET_ADDRESS_DEFAULT);
		if (!miaddr)
			goto failed;

		r = g_socket_join_multicast_group (priv->socket, miaddr, 
						   FALSE, NET_IF, error);
		g_object_unref (miaddr);

		if (!r)
			goto failed;

		source = g_socket_create_source (priv->socket, G_IO_IN, NULL);
		g_source_set_callback (source, (GSourceFunc) sock_in_handler,
				       priv, NULL);
		g_source_attach (source, g_main_loop_get_context (priv->io_loop));
		priv->socket_source = source;
	}

	priv->oq_open_window = -1;
	priv->sq_open_window = -1;

	priv->feed_thread = g_thread_try_new ("feed-thread",
					      feed_thead_handler, priv, error);
	if (!priv->feed_thread)
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
