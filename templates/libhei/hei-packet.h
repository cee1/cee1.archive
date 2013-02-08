#include <glib.h>
#include "config.h"

#ifndef __HEI_PACKET_H__
#define __HEI_PACKET_H__

G_BEGIN_DECLS
#define HEI_PACKET_MAGIC        0xA
#define HEI_PACKET_MAGIC_FEC    0x5
#define HEI_PACKET_SHEAD_SIZE   4 

#define HEI_PACKET_PACKED_SIZE  (1396 + HEI_PACKET_SHEAD_SIZE)

#define HEI_PACKET_TLMAX        15
#define HEI_PACKET_TLS_SIZE     (HEI_PACKET_TLMAX * 4)

#define HEI_PACKET_PAY_SIZE     (HEI_PACKET_PACKED_SIZE - \
				 HEI_PACKET_SHEAD_SIZE - HEI_PACKET_TLS_SIZE)
#define HEI_PACKET_MIN_SPACE    16 

#define HEI_PACKET_IS_FULL(p)   ((p)->size == (p)->size_filled || \
				 (p)->n_tl == HEI_PACKET_TLMAX)
#define HEI_PACKET_DATA(p)      ((p)->node.data)
#define HEI_PACKET_REAL_DATA(p) ((p)->real_data)
#define HEI_PACKET_READ_TL(p, idx) (idx >= HEI_PACKET_TLMAX ? (guint32) 0 : \
				    ((guint32 *) HEI_PACKET_REAL_DATA (p))[idx++])

#define TL_FLAG(tl)     ((tl) & 0x3)
#define TL_LEN(tl)      (((tl)>>2) & 0x7fff)
#define TL_OFFSET(tl)   (((tl)>>17)& 0x7fff)

#define TL_VALIDATE(tl, p_size) (TL_OFFSET(tl) >= (HEI_PACKET_SHEAD_SIZE + \
						   HEI_PACKET_TLS_SIZE) && \
				 TL_OFFSET(tl) + TL_LEN(tl) <= (p_size))

#define HEI_PACKET_PACK(p) (                               \
	((guint32 *) HEI_PACKET_DATA(p))[0] = (guint32) (  \
			((p)->wid & 0xffff) << 16 |        \
			((p)->seq & 0xff) << 8 |           \
			(HEI_PACKET_MAGIC & 0xf) << 4  |   \
			((p)->n_tl & 0xf)),                \
	HEI_PACKET_DATA(p))

#define HEI_PACKET_PACK_FEC(p) (                           \
	((guint32 *) HEI_PACKET_DATA(p))[0] = (guint32) (  \
			((p)->wid & 0xffff) << 16 |        \
			((p)->seq & 0xff) << 8 |           \
			(HEI_PACKET_MAGIC_FEC & 0xf) << 4),\
	HEI_PACKET_DATA(p))

#define HEI_PACKET_IS_FEC(p)    (!(p)->n_tl)
#define NEXT_SEQ_WID(wid, seq, winsize) G_STMT_START {      \
		wid = (guint16) (wid + (++seq) / (winsize));\
		seq = seq % winsize;                        \
	} G_STMT_END

#define WID_CMP(wid1, wid2) ((gint16)((gint)(wid1) - (wid2)))

struct _HeiPacket {
	GList node;

	guint64 timestamp;
	/* this is protected by fec */
	gpointer real_data;
	GDestroyNotify real_data_destroy;

	gint ref_count;

	guint32 tag;
	guint16 n_tl;
	guint16 size;
	guint16 size_filled;

	/* For reading */
	guint16 next_tl;

	guint16 wid;
	guint16 seq;

};

typedef struct _HeiPacket HeiPacket;

HeiPacket *hei_packet_new ();
HeiPacket *hei_packet_new_with_real_data (guint16 wid, guint16 seq,
					  gpointer real_data,
					  GDestroyNotify real_data_destroy);
void hei_packet_unref (HeiPacket *packet);
HeiPacket *hei_packet_ref (HeiPacket *packet);

gboolean hei_packet_unpack (HeiPacket *packet, guint16 data_size);
guint16 hei_packet_write (HeiPacket *packet,
			  void *data, guint16 offset, guint16 size);

guint16 hei_packet_read (HeiPacket *packet,
			 void *data, guint16 offset, guint16 size);

void _debug_hei_packet (HeiPacket *packet, GString *buf);
void debug_hei_packet (HeiPacket *packet);
void print_hei_packet (HeiPacket *packet);

G_END_DECLS

#endif
