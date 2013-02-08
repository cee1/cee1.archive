#include <glib.h>
#include <stdarg.h>

static void msgbuffer_destroy (void *data)
{
	g_string_free ((GString *) data, TRUE);
}

GString *my_msgbuffer ()
{
	static GPrivate msgbuffer_key = G_PRIVATE_INIT (msgbuffer_destroy);
	GString *msgbuffer = g_private_get (&msgbuffer_key);

	if (!msgbuffer) {
		msgbuffer = g_string_new (NULL);
		g_private_set (&msgbuffer_key, msgbuffer);
	}

	return msgbuffer;
}

void my_msgbuffer_flush (GLogLevelFlags level)
{
	GString *msgbuffer = my_msgbuffer ();

	if (msgbuffer->len) {
		g_log (G_LOG_DOMAIN, level, "%s", msgbuffer->str);
		g_string_truncate (msgbuffer, 0);
	}
}

void my_msgbuffer_clear ()
{
	GString *msgbuffer = my_msgbuffer ();
	g_string_truncate (msgbuffer, 0);
}

void my_msg_append (gchar *fmt, ...)
{
	va_list ap;
	GString *msgbuffer = my_msgbuffer ();

	va_start (ap, fmt);
	g_string_append_vprintf (msgbuffer, fmt, ap);
	va_end (ap);
}
