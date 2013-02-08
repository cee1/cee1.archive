#include <glib.h>
#include <gio/gio.h>
#include <string.h>
#include <stdlib.h>
#include <stdio.h>
#include <errno.h>

#include "internal.h"

GQueue *my_g_queue_concat (GQueue *q1, GQueue *q2)
{
	if (q1->tail)
		q1->tail->next = q2->head;

	if (q2->head)
		q2->head->prev = q1->tail;

	if (!q1->head)
		q1->head = q2->head;

	q1->tail = q2->tail;
	q1->length += q2->length;

	return q1;
}

GSocketAddress *make_sock_addr (gchar *addr, gint port)
{
	GInetAddress *iaddr = NULL;
	GSocketAddress *saddr = NULL;

	iaddr = g_inet_address_new_from_string (addr);
	if (!iaddr)
		return NULL;

	saddr = g_inet_socket_address_new (iaddr, port);
	if (!saddr)
		g_object_unref (iaddr);

	return saddr;
}


#ifdef MY_DEBUG
static void debug_dhpc (DecodeHeiPacketContext *ctxt)
{
	gchar *template = "dhpc%s:%d fragments(%dBytes), next_wid:%d, next_seq:%d ::\n"
			  "\tstack(len=%d): head: %p, tail: %p(wid=%d, seq=%d)\n"
			  "\told-stack(len=%d): head: %p, tail: %p(wid=%d, seq=%d)";

	my_msg_append (template, ctxt->state == DHPC_Lost ? "(drop:lost)" :
				 ctxt->state == DHPC_Too_many_fragments ? "(drop:too many)" : "",
				 ctxt->n_fragments,
				 ctxt->total_fragments_size,
				 ctxt->next_wid,
				 ctxt->next_seq,
				 ctxt->stack.length, ctxt->stack.head, ctxt->stack.tail,
				 ctxt->stack.tail ? ((HeiPacket *)ctxt->stack.tail)->wid : 0,
				 ctxt->stack.tail ? ((HeiPacket *)ctxt->stack.tail)->seq : 0,
				 ctxt->old_stack.length, ctxt->old_stack.head, ctxt->old_stack.tail,
				 ctxt->old_stack.tail ? ((HeiPacket *)ctxt->old_stack.tail)->wid : 0,
				 ctxt->old_stack.tail ? ((HeiPacket *)ctxt->old_stack.tail)->seq : 0
		      );
}
#else
#define debug_dhpc(...)
#endif

#define SET_HPACKET_TAG(packet, bit) ((packet)->tag |= (1 << (bit)))
#define GET_HPACKET_TAG(packet, bit) ((packet)->tag &  (1 << (bit)))
void decode_hei_packet (HeiPacket *packet,
			DecodeHeiPacketContext *ctxt,
			GFunc callback, gpointer user_data,
			gint pass)
{
	guint16 tl_idx;
	guint32 tl;
	gboolean has_lost;
	gboolean partial_decoded;
	guint16 saved_tl_idx;

#ifdef MY_DEBUG
	my_msg_append ("Decode(pass%d) ", pass);
	debug_hei_packet (packet);
	debug_dhpc (ctxt);
	my_msgbuffer_flush (G_LOG_LEVEL_DEBUG);
#endif

	has_lost = ctxt->next_wid != packet->wid || ctxt->next_seq != packet->seq;
	if (has_lost) {
		/* reset wid & seq to the new ones*/
		ctxt->next_wid = packet->wid;
		ctxt->next_seq = packet->seq;
		ctxt->state = DHPC_Lost;
	}
	NEXT_SEQ_WID (ctxt->next_wid, ctxt->next_seq, N_KPACKETS);
	g_queue_push_tail_link (&ctxt->stack, (GList *) packet);

	saved_tl_idx = 0;
	partial_decoded = pass ==2 && packet->tag;
	if (partial_decoded) {
		saved_tl_idx = packet->next_tl;
		packet->next_tl = 0;
	}
	tl_idx = packet->next_tl;
	g_assert (pass == 2 || packet->next_tl == 0);

	while ((tl = HEI_PACKET_READ_TL (packet, tl_idx))) { 
		gboolean not_cont;
		gboolean dry_run = partial_decoded &&
				   !GET_HPACKET_TAG (packet, tl_idx - 1) &&
				   tl_idx  - 1 < saved_tl_idx;
		guint tl_flag;

		tl_flag = dry_run ? 0 : TL_FLAG (tl);

		not_cont = tl_flag != 2 && tl_flag != 3;

		if (ctxt->n_fragments && 
		    (ctxt->state == DHPC_Lost || not_cont ||
		    (tl_flag == 2 && ctxt->n_fragments + 1 > MAX_SPLIT_COUNT))) {

			/* dropping all previous packets */
			while (ctxt->stack.head != (GList *) packet) {
				HeiPacket *p = (HeiPacket *) \
						g_queue_pop_head_link (&ctxt->stack);

				if (pass == 1 && ctxt->state == DHPC_Lost) {
					if (p->wid != packet->wid) {
						g_queue_push_tail_link (&ctxt->old_stack,
									(GList *) p);
						hei_packet_ref (p);
					}
					SET_HPACKET_TAG (p, p->next_tl);
				}
				hei_packet_unref (p);
			}

			my_msg_append ("Pass%d: Clear stack(drop %d fragments) because ",
						   pass, ctxt->n_fragments);
			if (ctxt->state == DHPC_Lost)
				my_msg_append ("%s", "Lost packets");
			else if (not_cont)
				my_msg_append ("Got unexpected tl_flag=%d", tl_flag);
			else
				my_msg_append ("Too many fragments");
			my_msgbuffer_flush (ctxt->state == DHPC_Lost ?
					    pass == 1 ? G_LOG_LEVEL_DEBUG :
							G_LOG_LEVEL_MESSAGE
						      : G_LOG_LEVEL_WARNING);
								
			ctxt->n_fragments = 0;
			ctxt->total_fragments_size = 0;

			if (ctxt->state != DHPC_Lost && !not_cont)
				ctxt->state = DHPC_Too_many_fragments;
		}

		if (dry_run) {
			ctxt->state = DHPC_Fine;
			packet->next_tl = tl_idx;

			continue;
		}

		if (!ctxt->n_fragments && (tl_flag == 2 || tl_flag == 3)) {
			if (pass == 1 && ctxt->state == DHPC_Lost)
				SET_HPACKET_TAG (packet, tl_idx - 1); 

			g_log (G_LOG_DOMAIN, ctxt->state == DHPC_Too_many_fragments ?
					     G_LOG_LEVEL_WARNING
					     : pass == 1 ? G_LOG_LEVEL_DEBUG
							 : G_LOG_LEVEL_MESSAGE,
				   "Pass%d: Drop tl%d/%d(len=%d,flag=%d) of "
				   "(wid=%d,seq=%d) because %s",
				   pass, tl_idx, packet->n_tl, TL_LEN (tl), tl_flag,
				   packet->wid, packet->seq,
				   ctxt->state ? ctxt->state == DHPC_Lost ?
						"Lost Packet!"
					      : "Too many fragments"
					      : "No fragments in stack");

			packet->next_tl = tl_idx;
			if (tl_flag == 3)
				ctxt->state = DHPC_Fine;

			continue;
		}

		ctxt->state = DHPC_Fine;
		g_debug ("Accept HeiPacket(wid=%d,seq=%d) %p, "
			 "curr_tl=%d/%d(len=%d,flag=%d)"
			 "fragments=%d(%dBytes)%s",
			 packet->wid, packet->seq, packet,
			 tl_idx, packet->n_tl,
			 TL_LEN (tl), tl_flag,
			 ctxt->n_fragments, ctxt->total_fragments_size,
			 ctxt->state ? ctxt->state == DHPC_Lost ?
			 "Lost Packet!" : "too many fragments" : "");

		if (tl_flag == 0 || tl_flag == 3) {
			void *buffer = NULL;
			guint buffer_size;
			guint16 offset = 0;
			guint16 bytes_read;
			gboolean corrupt = FALSE;

			buffer_size = TL_LEN (tl);
			buffer_size += ctxt->total_fragments_size;
			buffer = malloc (buffer_size);

			while (ctxt->stack.head != (GList *) packet) {
				HeiPacket *p = (HeiPacket *) \
						g_queue_pop_head_link (&ctxt->stack);
				if (!corrupt) {
					bytes_read = hei_packet_read (p,
								      buffer,
								      offset,
								      buffer_size);
					offset += bytes_read;
					corrupt = bytes_read == 0;
				}
				hei_packet_unref (p);
			} 
			ctxt->n_fragments = 0;
			ctxt->total_fragments_size = 0;

			if (!corrupt) {
				bytes_read = hei_packet_read (packet,
							      buffer,
							      offset,
							      buffer_size);
				offset += bytes_read;
				corrupt = bytes_read == 0 ||
					  offset != buffer_size;
			}

			if (corrupt) {
				g_warning ("Pass%d: Drop tl(flag=%d), "
						   "because the whole payload was corrupt!", pass, tl_flag);
				packet->next_tl = tl_idx;
				free (buffer);
				continue;
			}

			g_debug ("Pass%d: Submit a %uBytes Buffer",
				 pass, buffer_size);
			callback (buffer, user_data);
		} else if (tl_flag == 1 || tl_flag == 2) {
			ctxt->n_fragments++;
			ctxt->total_fragments_size += TL_LEN (tl);
		} else {
			packet->next_tl = tl_idx;
			g_warning ("Pass%d: Drop tl(flag=%d), unknown tl", pass, tl_flag);
		}
	}

	if (!ctxt->n_fragments) {
		g_assert (ctxt->stack.head == (GList *) packet);
		g_queue_unlink (&ctxt->stack, (GList *) packet);

		hei_packet_unref (packet);
	}
}

void _debug_queue (GQueue *q, GString *buf)
{
	GList *iter;
	guint count;

	g_string_append_printf (buf, "%d packets(head=%p,tail=%p) in q:\n",
				q->length, q->head, q->tail);

	for (count = 0, iter = q->head; iter; iter = iter->next) {
		HeiPacket *p = (HeiPacket *) iter;

		g_string_append_printf (buf, "[%d] ", count++);
		_debug_hei_packet (p, buf);
	}
}
void debug_queue (GQueue *q)
{
	GString *msgbuffer = my_msgbuffer ();
	_debug_queue (q, msgbuffer);
}

void print_queue (GQueue *q)
{
	GString *buf = g_string_new (NULL);
	_debug_queue (q, buf);
	puts (buf->str);
	g_string_free (buf, TRUE);
}

