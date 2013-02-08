#ifndef __LOG_H__
#include <glib.h>

G_BEGIN_DECLS

/* logging */
GString *my_msgbuffer ();
void my_msg_append (gchar *fmt, ...) G_GNUC_PRINTF (1, 2);
void my_msgbuffer_flush (GLogLevelFlags level);
void my_msgbuffer_clear ();

G_END_DECLS
#endif
