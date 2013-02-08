#ifndef __INTERNAL_H__
#define __INTERNAL_H__

#include <glib.h>
#include "config.h"
#include "log.h"
#include "hei-packet.h"

G_BEGIN_DECLS

#ifndef MY_DEBUG

#ifdef g_debug
#undef g_debug
#endif
#define g_debug(...)

#endif

GQueue *my_g_queue_concat (GQueue *q1, GQueue *q2);

typedef struct _DecodeHeiPacketContext DecodeHeiPacketContext;
enum DHPCState {
	DHPC_Fine,
	DHPC_Lost,
	DHPC_Too_many_fragments
};
struct _DecodeHeiPacketContext {
	GQueue stack;
	GQueue old_stack;
	guint next_wid;
	guint next_seq;
	guint n_fragments;
	guint total_fragments_size;
	enum DHPCState state;
};

GSocketAddress *make_sock_addr (gchar *addr, gint port);
void decode_hei_packet (HeiPacket *packet,
			DecodeHeiPacketContext *ctxt,
			GFunc callback, gpointer user_data,
			gint pass);

void _debug_queue (GQueue *q, GString *buf);
void debug_queue (GQueue *q);
void print_queue (GQueue *q);

G_END_DECLS
#endif
