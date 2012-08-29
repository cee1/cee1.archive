#!/usr/bin/env python
import os, fcntl, select, errno
import sys, subprocess, cStringIO 

# Read environment vars:
#	CGI_BRG_OUT_BLKSZ, CGI_BRG_LATENCY
#	SCRIPT_FILE required, <path/to/real_cgi_script>

def fd_nonblock(*fds):
	for fd in fds:
		flags = fcntl.fcntl(fd, fcntl.F_GETFL)
		fcntl.fcntl(fd, fcntl.F_SETFL, flags | os.O_NONBLOCK)

def setup_poll_read(*fds):
	p = select.poll()

	for fd in fds:
                p.register(fd, select.POLLIN | select.POLLPRI | select.POLLERR | select.POLLHUP)

	return p

def do_poll(poll_, timeout = None):
	changed_list = []

	while True:
		try:
			changed_list = poll_.poll(timeout)
		except select.error:
			if sys.exc_info()[1][0] != errno.EINTR:
				raise
		else:
			break
	return changed_list

def _parse_binary_num(s):
	s = s.strip()

	units = 'KMGTPEZY'

	u = s[-1].upper()
	try:
		u = (units.index(u)+1) * 10
		s = s[:-1]
	except:
		u = 0

	i = int(s)

	return  i * (1<<u)

def _parse_headers(msg):
	for br in ('\r\n', '\n'):
		sep = br * 2
		if sep in msg:
			headers = []
			head, body = msg.split(sep, 1)

			for h in head.split(br):
				headers.append(tuple(map(str.strip, h.split(':', 1))))

			return headers, body

def _merge_wsgi_environ(wsgi_env):
	for i in wsgi_env.keys():
		if not i.startswith('wsgi.') and \
		   not i.startswith('UWSGI_'):
			os.environ[i] = wsgi_env[i]

def application(environ, start_response):
	buffer_ = cStringIO.StringIO()

	try:
		buffer_threshold = _parse_binary_num(os.environ['CGI_BRG_OUT_BLKSZ'])
	except:
		buffer_threshold = 1024 * 512
	
	try:
		latency = int(os.environ['CGI_BRG_LATENCY'])
	except:
		latency = 50 # 50ms

	in_ = environ['wsgi.input']
	err_ = environ['wsgi.errors']
	cgi_ = os.environ['SCRIPT_FILE']
	_merge_wsgi_environ(environ)

	print >>sys.stdout, "[INFO] Try to execute cgit '%s', out block size %dBytes, latency %dms" % \
	                    (cgi_, buffer_threshold, latency)

	cgi_exec = subprocess.Popen(cgi_, bufsize = -1,
                                    stdin = in_, stdout = subprocess.PIPE, stderr = err_,
                                    env = os.environ)

	fd_nonblock(cgi_exec.stdout.fileno())
	poll_ = setup_poll_read(cgi_exec.stdout)

	headers_found = False
	status = '200 OK'

	while True:
		changed_list = do_poll(poll_, latency)
		for c in changed_list:
			fd, event = c
			if event & (select.POLLHUP | select.POLLERR):
				if event & select.POLLERR:
					print >>sys.stderr, 'Detach Pipe(%d): because of ' \
							    'POLLERR' % fd
				poll_.unregister(fd)

			if event & (select.POLLIN | select.POLLPRI):
#				print 'Reading... buffer len: %dBytes => ' % buffer_.tell(),
				buffer_.write(cgi_exec.stdout.read())
#				print '%dBytes' % buffer_.tell()

		cgi_exec.poll()
		if not changed_list or \
		   buffer_.tell() >= buffer_threshold or \
		   cgi_exec.returncode != None:
			data = buffer_.getvalue()
			if not headers_found:
				r = _parse_headers(data)
				if r:
					headers, other = r
					data = other

#					print 'Parsed headers:'
#					print headers
#					print
					start_response(status, headers)

					headers_found = True

			if headers_found:
#				reasons = []
#				if not changed_list:
#					reasons.append("Idle for more than 50ms")
#				if buffer_.tell() >= buffer_threshold:
#					reasons.append("Buffer(%dBytes) over threshold" % buffer_.tell())
#				if cgi_exec.returncode != None:
#					reasons.append("Cgi exited")
#
#				print 'Flushed %dBytes (Reason: %s)' % (buffer_.tell(), ', '.join(reasons))

				buffer_.truncate(0)
				yield data

			elif buffer_.tell() >= buffer_threshold or \
			     cgi_exec.returncode != None:
				raise Exception, "!!!No headers found in %d Bytes of output from '%s'" % \
						 (buffer_threshold, cgi_)

		if cgi_exec.returncode != None:
			if cgi_exec.returncode != 0:
				print >>sys.stderr, "!!!CGI '%s' exited with %d" % (cgi_, cgi_exec.returncode)
			break

	buffer_.close()
