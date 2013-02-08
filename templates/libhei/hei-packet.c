#include <string.h>
#include <stdio.h>
#include "hei-packet.h"
#include "log.h"

#if GLIB_MAJOR_VERSION == 2 && GLIB_MINOR_VERSION < 30
#error "Need glib(>=2.30) for g_atomic_int_add"
#endif

/* Hei Packet:
 * Byte order: LSB
 *
 * SUPER_HEAD + TLs + PAYLOAD
 * SUPER_HEAD = [ wid(16bits) + seq(8bit) + magic(4bits) + number_of_tl(4bits) ]
 * TLs = number_of_tl * [ offset(15bits) + len(15bits) + flag (2bits) ]
 *                                                       flag: 0 complete
 *                                                             1 start of a
 *                                                               new fragment
 *                                                             2 middle of a
 *                                                               new fragment
 *                                                             3 end of a
 *                                                               new fragment
 */
HeiPacket *hei_packet_new ()
{
	HeiPacket *packet;

	packet = g_slice_new0 (HeiPacket);
	packet->ref_count = 1;
	HEI_PACKET_DATA (packet) = g_slice_alloc0 (HEI_PACKET_PACKED_SIZE);
	HEI_PACKET_REAL_DATA (packet) = HEI_PACKET_DATA (packet) + \
					HEI_PACKET_SHEAD_SIZE;

	packet->size = HEI_PACKET_PACKED_SIZE;
	packet->size_filled = HEI_PACKET_SHEAD_SIZE + HEI_PACKET_TLS_SIZE;

	return packet;
}

HeiPacket *hei_packet_new_with_real_data (guint16 wid, guint16 seq,
					  gpointer real_data,
					  GDestroyNotify real_data_destroy)
{
	HeiPacket *packet;

	packet = g_slice_new0 (HeiPacket);
	packet->ref_count = 1;

	HEI_PACKET_REAL_DATA (packet) = real_data;
	packet->real_data_destroy = real_data_destroy;

	packet->size = HEI_PACKET_PACKED_SIZE;
	packet->size_filled = HEI_PACKET_PACKED_SIZE;
	packet->wid = wid;
	packet->seq = seq;

	return packet;
}

gboolean hei_packet_unpack (HeiPacket *packet, guint16 data_size)
{
	guint32 super_head = ((guint32 *) HEI_PACKET_DATA (packet))[0];
	guint32 magic = (super_head & 0xf0) >> 4;
	guint16 wid = (super_head & 0xffff0000) >> 16;
	guint16 seq = (super_head & 0xff00) >> 8;
	guint32 *tls = (guint32 *) HEI_PACKET_REAL_DATA (packet);

	if (magic == HEI_PACKET_MAGIC) {
		guint16 n_tl = super_head & 0xf;

		g_return_val_if_fail (data_size > (HEI_PACKET_SHEAD_SIZE + \
					           HEI_PACKET_TLS_SIZE) &&
						   n_tl > 0 && n_tl <= HEI_PACKET_TLMAX &&
						   (n_tl == HEI_PACKET_TLMAX || tls[n_tl] == 0),
						   FALSE);
		packet->n_tl = n_tl;
	} else {
		g_return_val_if_fail (data_size == HEI_PACKET_PACKED_SIZE &&
				      magic == HEI_PACKET_MAGIC_FEC, FALSE);
	}

	packet->size_filled = data_size;
	packet->wid = wid;
	packet->seq = seq;

	return TRUE;
}

static void hei_packet_free (HeiPacket *packet)
{
	if (HEI_PACKET_DATA (packet))
		g_slice_free1 (packet->size, HEI_PACKET_DATA (packet));
	else if (HEI_PACKET_REAL_DATA (packet))
		if (packet->real_data_destroy)
			packet->real_data_destroy (HEI_PACKET_REAL_DATA (packet));
	g_slice_free (HeiPacket, packet);
}

HeiPacket *hei_packet_ref (HeiPacket *packet)
{
	g_assert (g_atomic_int_add (&packet->ref_count, 1) > 0);
	return packet;
}

void hei_packet_unref (HeiPacket *packet)
{
	gint old_ref_count;

	g_assert ((old_ref_count = \
		   g_atomic_int_add (&packet->ref_count, -1)) > 0);

	if (old_ref_count == 1)
		hei_packet_free (packet);
}

guint16 hei_packet_write (HeiPacket *packet,
			  void *data, guint16 offset, guint16 size)
{
	guint16 bytes_written;
	guint16 size_to_write = size - offset;
	guint32 *tls;
	guint8 *ptr;

	if (packet->n_tl == HEI_PACKET_TLMAX || 
	    (size_to_write + packet->size_filled > packet->size &&
	    HEI_PACKET_MIN_SPACE + packet->size_filled > packet->size))
		return 0;

	tls = (guint32 *) HEI_PACKET_REAL_DATA (packet);
	ptr = (guint8 *) HEI_PACKET_DATA (packet) + packet->size_filled;

	bytes_written = packet->size - packet->size_filled;
	bytes_written = bytes_written > size_to_write ? \
					size_to_write : bytes_written;

	memcpy (ptr, data + offset, bytes_written);
	tls[packet->n_tl] = ((packet->size_filled & 0x7fff) << 17) |    \
			     ((bytes_written  & 0x7fff) << 2)      |    \
			     (bytes_written == size_to_write ?          \
				!offset ? 0 : 3                         \
			      : !offset ? 1 : 2);

	packet->n_tl++;
	packet->size_filled += bytes_written;

	return bytes_written;
}

guint16 hei_packet_read (HeiPacket *packet,
			 void *data, guint16 offset, guint16 size)
{
	guint16 bytes_read;
	guint32 tl;
	guint8 *ptr;
	guint16 size_to_read = size - offset;
	guint16 next_tl = packet->next_tl;

	tl = HEI_PACKET_READ_TL (packet, next_tl);
	if (!tl)
		return 0;

	/* corrupt packet */
	g_return_val_if_fail (TL_VALIDATE (tl,
			      packet->size_filled), 0);

	ptr = (guint8 *) HEI_PACKET_REAL_DATA (packet) + \
			 TL_OFFSET (tl) - HEI_PACKET_SHEAD_SIZE;

	bytes_read = TL_LEN (tl);
	bytes_read = bytes_read > size_to_read ? \
		     size_to_read : bytes_read;

	memcpy (data + offset, ptr, bytes_read);
	packet->next_tl = next_tl;

	return bytes_read;
} 

void _debug_hei_packet (HeiPacket *packet, GString *buf)
{
	guint idx = 0;
	guint32 tl;
	gboolean need_newline = TRUE;

	g_string_append_printf (buf, "HeiPacket(wid=%d,seq=%d@%p), %drefs, data@%p",
				packet->wid, packet->seq, packet, packet->ref_count,
				HEI_PACKET_DATA (packet));

	if (HEI_PACKET_DATA (packet))
		g_string_append_printf (buf, "[0x%08x...]",
					((guint32 *) HEI_PACKET_DATA (packet))[0]);

	g_string_append_printf (buf, "\n%dtls(tag=0x%08x) %dBytes real_data@%p",
				packet->n_tl, packet->tag, packet->size_filled,
				HEI_PACKET_REAL_DATA (packet));

	if (HEI_PACKET_REAL_DATA (packet))
		g_string_append_printf (buf, "[0x%08x...]",
					((guint32 *) HEI_PACKET_REAL_DATA (packet))[0]);

	g_string_append_printf (buf, ":\n");
	while ((tl = HEI_PACKET_READ_TL (packet, idx))) {
		g_string_append_printf (buf, "\t[%d] flag=%d: %dB@%d", idx - 1,
					TL_FLAG (tl), TL_LEN (tl), TL_OFFSET (tl));

		if (!(idx % 3)) {
			g_string_append_printf (buf, "\n");
			need_newline = FALSE;
		} else
			need_newline = TRUE;
	}

	if (need_newline)
		g_string_append_printf (buf, "\n");
}
void debug_hei_packet (HeiPacket *packet)
{
	GString *msgbuffer = my_msgbuffer ();
	_debug_hei_packet (packet, msgbuffer);
}

/* This is for invork@gdb*/
void print_hei_packet (HeiPacket *packet)
{
	GString *msgbuffer = g_string_new (NULL);

	_debug_hei_packet (packet, msgbuffer);
	
	puts (msgbuffer->str);
	g_string_free (msgbuffer, TRUE);
}

