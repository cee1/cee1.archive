#!/usr/bin/python

import os, os.path, sys
import errno

import pwd
git_uid = pwd.getpwnam('git')[2]

ctx = {
	'GITOSIS_CONF': None,
	'GITOSIS_KEYDIR': 'users-db/public',
	'PRIVATE_KEYDIR': 'users-db/private',
}

def gitosis_sync(gitosis_conf, gitosis_keydir):
	from gitosis import ssh
	from gitosis import gitweb
	from gitosis import gitdaemon
	from gitosis import util
	import ConfigParser

	cfg = ConfigParser.RawConfigParser ()
	cfg.read(gitosis_conf)

	util.RepositoryDir(cfg,
			   (
			   gitdaemon.DaemonProp(),
			   gitweb.GitwebProp(),
			   gitweb.DescriptionProp(),
			   gitweb.OwnerProp()
			   )).travel()

	generated = util.getGeneratedFilesDir(config=cfg)
	gitweb.ProjectList(
			  os.path.join(generated, 'projects.list')
			  ).refresh()

	authorized_keys = util.getSSHAuthorizedKeysPath(config=cfg)
	ssh.writeAuthorizedKeys(
		path=authorized_keys,
		keydir=gitosis_keydir,
	)

from base64 import urlsafe_b64encode, urlsafe_b64decode
class User(object):
	def __init__(self, privkey_dir, pubkey_dir):
		self.priv_keys = privkey_dir
		self.pub_keys = pubkey_dir

	def __encode(self, username):
		prefix = 'git'
		encoded_username = urlsafe_b64encode(username)
		encoded_username = prefix + encoded_username.replace('=', '.')

		return encoded_username

	def __decode(self, encoded_username):
		prefix = 'git' 
		assert encoded_username.startswith('git')

		username = encoded_username[len(prefix):]
		username = username.replace('.', '=')
		username = urlsafe_b64decode(username)	

		return username

	def print_keys(self, username):
		encoded_username = self.__encode(username)
		priv_path = os.path.join(self.priv_keys, encoded_username)
		pub_path = os.path.join(self.pub_keys, encoded_username + '.pub')
	
		if not os.path.exists(priv_path): 
			priv_path = "(not found)"

		if not os.path.exists(pub_path):
			pub_path = "(not found)"

		print "%s's private key: %r" % (username, priv_path)
		print "%s's public key: %r" % (username, pub_path)

	def who(self, encoded_username):
		try:
			username = self.__decode(encoded_username)
		except:
			print 'Malformed encoded_username %r.' % encoded_username
		else:
			print '%r is %r' % (encoded_username, username)

	def encode(self, username):
		print 'Encode %r => %r' % (username, self.__encode(username))
		
	def list(self):
		def _error(e):
			if e.errno == errno.ENOENT:
				pass
			else:
				raise e
		users = {}

		for d in (self.priv_keys, self.pub_keys):
			for (dirpath, dirnames, filenames) \
				in os.walk(d, onerror=_error):
				dirnames[:] = []

				for f in filenames:
					if d == self.pub_keys:
						keytype = 'public key'
						assert f.endswith('.pub')
						encoded_username, ext = os.path.splitext(f)
					else:
						keytype = 'private key'
						encoded_username = f

					try:
						username = self.__decode(encoded_username)
					except:
						print 'Malformed user %s file %r' % (keytype, f)
					else:
						u = users.get(encoded_username, \
							{ 'name' : username,
							  'private key': False,
							  'public key' : False,
							})
						u[keytype] = True
						users[encoded_username] = u
		for u in users:
			name = users[u]['name']

			priv = 'non'
			if users[u]['private key']:
				priv = 'Private'

			pub = 'non'
			if users[u]['public key']:
				pub = 'Public'
	
			print '%-30s\t%-20s\t%-10s\t%-10s' % (u, name, priv, pub)	


if __name__ == '__main__':
	usage = """
	python cmd -G user
		retrieve user's private & pub keypair
	python cmd -W userid
		useid is who?
	python cmd -E user
		encode this user
	python cmd -L
		list users?
	python cmd -S
		sync gitosis
	"""

	argc = len(sys.argv)
	if argc == 3:
		if sys.argv[1] == '-G':
			User(ctx['PRIVATE_KEYDIR'], ctx['GITOSIS_KEYDIR']).print_keys(sys.argv[2])
		elif sys.argv[1] == '-W':
			User(ctx['PRIVATE_KEYDIR'], ctx['GITOSIS_KEYDIR']).who(sys.argv[2])
		elif sys.argv[1] == '-E':
			User(ctx['PRIVATE_KEYDIR'], ctx['GITOSIS_KEYDIR']).encode(sys.argv[2])
		else:
			print usage
	elif argc == 2:
		if sys.argv[1] == '-L':
			User(ctx['PRIVATE_KEYDIR'], ctx['GITOSIS_KEYDIR']).list()
		elif sys.argv[1] == '-S':
			if ctx['GITOSIS_CONF'] == None:
				sys.exit('Synchronize git is shutdown on the host!')

			assert os.geteuid() == git_uid, 'please run under user git'

			print 'synchronizing gitosis'
			gitosis_sync(ctx['GITOSIS_CONF'], ctx['GITOSIS_KEYDIR'])
		else:
			print usage
	else:
		print usage
		

