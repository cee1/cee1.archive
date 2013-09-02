#!/usr/bin/env python
import sys, os.path, os, fcntl, getopt, datetime, time

WorkingDir = '/path/to/a/writabledir' # Store mails to send
SelfID = 'mailSender'
smtp_server = 'smtp.example.com'
smtp_port = 25
smtp_user = '<user>'
smtp_password = '<password>'
smtp_use_tls = False
default_from_addr = '<user>@example.com'

def log_init():
	# Do ready for log
	log_level = logging.INFO
	log_path = os.path.join(WorkingDir, SelfID + '.log')
	log_max_size = 1024 * 1024 * 1
	log_bak_cnt = 1

	log = logging.getLogger('senderLog')
	log.setLevel(log_level)

	log_fmtter = logging.Formatter("%(asctime)s:%(levelname)s:%(message)s")

	# log file handler
	saved_mask = os.umask(0555)
	log_handler = logging.handlers.RotatingFileHandler(log_path, maxBytes=log_max_size, backupCount=log_bak_cnt)
	os.umask(saved_mask)

	log_handler.setLevel(log_level)
	log_handler.setFormatter(log_fmtter)
	log.addHandler(log_handler)

	# log stderr
	# log_handler = logging.StreamHandler()
	# log_handler.setLevel(logging.DEBUG)
	# log_handler.setFormatter(log_fmtter)
	# log.addHandler(log_handler)

	return log

def daemonize():
	if os.fork() != 0: os._exit(0)
	os.setsid()
	if os.fork() != 0: os._exit(0)
	os.umask(0)
	os.chdir('/')

	import resource
	maxfd = resource.getrlimit(resource.RLIMIT_NOFILE)[1]
	if maxfd == resource.RLIM_INFINITY: maxfd = 1024
	
	for fd in xrange(0, maxfd):
		try:
			os.ttyname(fd)
		except:
			continue

		try:
			os.close(fd)
		except OSError:
			pass

	os.open('/dev/null', os.O_RDWR)
	os.dup2(0, 1)
	os.dup2(0, 2)

class ILock(object):
	lock_path =  ''
	def __init__(self):
		self.locked = False
		saved_mask = os.umask(0111)
		self.fd = os.open(self.lock_path, os.O_CREAT | os.O_RDWR)
		os.umask(saved_mask)

	def __del__(self):
		if hasattr(self, 'fd'):
			os.close(self.fd)

	def exlock(self, block=True):
		assert self.locked == False, 're-enter the lock'
		flags = fcntl.LOCK_EX
		if not block: flags |= fcntl.LOCK_NB

		fcntl.lockf(self.fd, flags)
		self.locked = True

	def shlock(self, block=True):
		assert self.locked == False, 're-enter the lock'
		flags = fcntl.LOCK_SH
		if not block: flags |= fcntl.LOCK_NB

		fcntl.lockf(self.fd, flags)
		self.locked = True
	
	def unlock(self):
		assert self.locked == True, 'unlock an unlocked lock'
		fcntl.lockf(self.fd, fcntl.LOCK_UN)
		self.locked = False

class PoolLock(ILock):
	lock_path = os.path.join(WorkingDir, 'pool.lock')

class DaemonLock(ILock):
	lock_path = os.path.join(WorkingDir, 'daemon.lock')

JobIDFormat = "%Y%m%d-%H%M-%S_%f.mail"
def commit_to_pool(from_addr, recipients, message):
	# Seems Python2.6 support the "%f" -- microseconds
	# mail_id = datetime.datetime.now().strftime(JobIDFormat)
	ts = datetime.datetime.now()
	mail_id = "%04d%02d%02d-%02d%02d-%02d_%06d-%d.mail" % (ts.year, ts.month, ts.day, ts.hour, ts.minute, ts.second, ts.microsecond, os.getpid())

	_mail = os.path.join(WorkingDir, '_' + mail_id)
	pending_mail = os.path.join(WorkingDir, 'P' + mail_id)

	lock = PoolLock()
	lock.shlock()

	open(_mail, 'w').write("""From: %s
To: %s
%s""" % (from_addr, recipients, message))

	os.rename(_mail, pending_mail)
	del lock

def scan_pool(log, queue):
	log.info("Scanning not-processed jobs...") 

	lock = PoolLock()
	lock.exlock()
	jfs = os.listdir(WorkingDir)
	del lock

	ordered_jfs = []

	for j in jfs:
		jpath = os.path.join (WorkingDir, j)
		if os.path.isfile(jpath) and os.path.splitext(j)[1] == '.mail':
			if j[0] == '_': 
				log.info("Remove job fragment: %s" % j)
				os.remove(jpath)
			elif j[0] == 'P': 
				log.info("Send pending job: %s" % j)
				heapq.heappush(ordered_jfs, j)

	try:
		while 1: queue.put_nowait(heapq.heappop(ordered_jfs))	
	except IndexError:
		pass
	except Queue.Full:
		log.warning("Too much pending jobs, only process part")
	del ordered_jfs

def do_smtp_send(log, from_addr, recipients, message):
	# Ensure the message complies with RFC2822: use CRLF line endings
	message = '\r\n'.join(re.split('\r?\n', message))

	log.info("Sending notification through SMTP at %s:%d to %s" % (smtp_server, smtp_port, recipients))
	server = smtplib.SMTP(smtp_server, smtp_port)
	# server.set_debuglevel(True)
	if smtp_use_tls:
		server.ehlo()

		if not server.esmtp_features.has_key('starttls'):
			raise IOError, "TLS enabled but server does not support TLS"
		server.starttls()
		server.ehlo()
	if smtp_user:
		server.login(smtp_user.encode('utf-8'), smtp_password.encode('utf-8'))
	start = time.time()
	server.sendmail(from_addr, recipients, message)
	t = time.time() - start
	if t > 5:
		log.warning('Slow mail submission (%.2f s), check your mail setup' % t)
	if smtp_use_tls:
		# avoid false failure detection when the server closes
		# the SMTP connection with TLS enabled
		import socket
		try:
			server.quit()
		except socket.sslerror:
			pass
	else:
		server.quit()

def try_smtp_send(log, jobid, from_addr, recipients, message):
	# Try two times before a mail send fail
	max_nr_tries = 3
	nr_tries = 0
	while 1:
		nr_tries += 1
		try:
			do_smtp_send(log, from_addr, recipients, message) 
		except:
			if nr_tries == max_nr_tries: raise

			s = 5 * nr_tries
			log.warning('Try%d: Send mail faild(job: %s), will sleep %d seconds' % (nr_tries, jobid, s))
			time.sleep(s)
		else:
			break

def do_send(log, queue):
	scan_pool(log, queue)

	while 1:
		try:
			job = queue.get(timeout=60 * 10)
		except Queue.Empty:
			log.debug("(10 minutes idle) Trigger quit...")
			try:
				lock = PoolLock()
				lock.exlock(False)
			except IOError:
				del lock
				log.debug("Detect incoming job, abort quit ...")
				continue
			else:
				log.debug("Wait 1s for new job in the queue ...")
				try:
					job = queue.get(timeout=1)
				except Queue.Empty:
					log.info("10 minutes passed, no jobs received, quit...")
					os._exit(0)
				else:
					del lock
			
		job_file = os.path.join(WorkingDir, job)
		if not os.path.isfile(job_file): continue

		try:
			j = open(job_file, 'r')
			from_addr = j.readline()[len('From: '):-1]
			recipients = j.readline()[len('To: '):-1].split(',')

			j = open(job_file, 'r')
			message = j.read()
			j.close()

			assert recipients and message, 'Some fields of this mail is empty!'
			try_smtp_send(log, job_file, from_addr, recipients, message)
		except:
			log.exception('An exception happened when process "%s":' % job)
		finally:
			try:
				os.remove(job_file)
			except OSError, e:
				log.exception('Failed to remove finished job "%s":%s' % (job_file, errno.errorcode[e.errno]))

def do_monitor(log, queue):
	wm = pyinotify.WatchManager()
	mask = pyinotify.IN_MOVED_TO

	class EventHandler(pyinotify.ProcessEvent):
		def process_IN_MOVED_TO(self, event):
			j = os.path.basename(event.pathname)
			jpath = os.path.join(WorkingDir, j)
			log.debug("inotify: \"%s\" MOVED_TO \"%s\"" % (j, WorkingDir))

			if os.path.isfile(jpath) and os.path.splitext(j)[1] == '.mail' and j[0] == 'P':
				queue.put(j)

	handler = EventHandler()
	notifier = pyinotify.Notifier(wm, handler)

	wdd = wm.add_watch(WorkingDir, mask)
	notifier.loop()

def monitor_and_send():
	try:
		lock = DaemonLock()
		lock.exlock(False)
	except IOError:
		log.debug("Another instance of this daemon is(will be) running, abort...")
		sys.exit('Another instance of this daemon is(will be) running, abort...')

	log = log_init()	
	queue = Queue.Queue(200)

	log.info("""%s Start...
	WorkingDir: "%s"
	smtp_server = "%s:%s"
	smtp_user =  "%s"
	smtp_password = "%s"
	smtp_use_tls = %s""" % (SelfID, WorkingDir, smtp_server, smtp_port, smtp_user, smtp_password, smtp_use_tls))

	send_worker = threading.Thread(target=do_send, name="SendWorker", args=(log, queue))
	send_worker.start()
	do_monitor(log, queue)
	

if __name__ == '__main__':
	if not os.path.exists(WorkingDir):
		saved_mask = os.umask(0)
		os.mkdir(WorkingDir, 01777)
		os.umask(saved_mask)

#	f = open('/tmp/a', 'w')
#	f.write(' '.join(sys.argv) + '\n' + sys.stdin.read())
#	sys.exit(0)

	opts, recipients = getopt.getopt(sys.argv[1:], 'itf:')

	has_i = False
	has_t = False
	from_addr = ''

	for o in opts:
		if o[0] == '-i': has_i = True
		elif o[0] == '-f': from_addr = o[1]
		elif o[0] == '-t': has_t = True

	if not has_i:
		sys.exit('Lack parameter "-i"')

	if not recipients and not has_t:
		sys.exit('Lack recipients, and no "-t" parameter'
			 '(Extract recipients from message headers) specified')

	if has_t:
		message = ''
		for l in sys.stdin:
			if l.startswith('To:'):
				recipients = l[len('To:'):].split(',')
			elif l.startswith('From:'):
				from_addr = l[len('From:'):]
			else:
				message += l
		if not recipients:
			sys.exit('"-t" parameter specified, '
				 'but no valid "TO: xxx@exmaple.com" appears in message')
	else:
		message = sys.stdin.read()

	recipients = ','.join (r.strip() for r in recipients)
	if '\n' in recipients:
		sys.exit('one of the recipients contains "\\n"')

	# from_addr is optional
	if not from_addr:
		from_addr = default_from_addr

	from_addr = from_addr.strip()
	if '\n' in from_addr:
		sys.exit('from_addr contains "\\n"')


	try:
		lock = DaemonLock()
		lock.exlock(False)
	except IOError:
		del lock
		commit_to_pool(from_addr, recipients, message)
	else:
		del lock
		if os.fork() == 0:
			daemonize()
			import logging, logging.handlers, threading, Queue, smtplib, re, heapq, errno, pyinotify
			monitor_and_send()
		else:
			commit_to_pool(from_addr, recipients, message)

