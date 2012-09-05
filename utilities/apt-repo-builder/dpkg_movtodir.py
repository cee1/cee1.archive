#!/usr/bin/python
import os, os.path, sys, logging, re

quiet = logging.WARNING
force = False
DebNameVersionSep = '_'
DefaultDirMode = 0755

def _mkdir_p (dir):
	d = dir
	to_mk = []

	while not os.path.exists (d):
		to_mk.append (d)
		parent = os.path.dirname (d)
		if parent == '' or d == parent:
			#the root of path
			break
		d = parent
	
	if to_mk:
		to_mk.reverse ()
		for d in to_mk:
			try:
				os.mkdir (d, DefaultDirMode)
			except OSError:
				logging.exception ('_mkdir_p: Can\'t create dir "%s"' % d)
				raise
			except:
				raise
	
	if not os.path.isdir (dir):
		raise IOError, '_mkdir_p: "%s" is not a directory' % dir

def _index (pkg_name):
	index = pkg_name[0]
	
	if index == 'l' and len (pkg_name) >= 4 and pkg_name[:3] == 'lib':
		index = pkg_name[:4]
	
	return index

def moving (old_path, pool, src):
	dir_path = os.path.join (pool, _index(src), src)
	_mkdir_p (dir_path)
	
	f = os.path.basename (old_path)
	new_path = os.path.join (dir_path, f)
	
	action = 'mv "%s" -> "%s"' % (old_path, new_path)
	
	if not os.path.isfile (old_path):
		logging.debug ('%s, but "%s" is not a regular file or not exists' % (action, old_path))
		return
	if os.path.islink (old_path):
		logging.debug ('%s, but "%s" is not a symbol link' % (action, old_path))
		return
	
	if os.path.lexists (new_path):
		if not force:
			logging.info ('%s, but "%s" exists, try --force' % (action, new_path))
			return
		
		logging.info ('%s, force overwrite "%s"' % (action, new_path))

	try:
		os.rename (old_path, new_path)
	except OSError:
		_e = sys.exc_info ()
		logging.exception ('%s failed\n%s\n' % (action, _e[1]))

def walk_idx (idx_file, visitor):
	a_pkg = {}
	
	line_no = 0
	nr_pkg = 0
	cur_key = ''

	for line in open (idx_file, 'r'):
		line_no += 1
		
		if line == '\n':
			if not a_pkg: continue

			try:
				_r = visitor (a_pkg)
			except:
				_e = sys.exc_info()
				logging.exception ('An Exception(%s) Happened when process %s(%d): %s\n%s\n' % (_e[0], idx_file, line_no, line, _e[1]))
				sys.exit (-1)
			
			nr_pkg += 1	
			if _r:
				a_pkg = {}
				break

			a_pkg = {}
			continue

		if line[0] != ' ' and line[0] != '\t':
			try:
				k, v = line.split(':', 1)
			except ValueError:
				logging.exception ('(%s:%d)line "%s" not has a ":"' % (idx_file, line_no, line))
				raise
			else:
				cur_key = k.strip ()
 				a_pkg[cur_key] = v.strip ()
		else:
			a_pkg[cur_key] += ('\n' + line[:-1])

	if a_pkg:
		try:
			visitor (a_pkg)
		except:
			_e = sys.exc_info()
			logging.exception ('An Exception(%s) Happened when process %s(%d): %s\n%s\n' % (_e[0], idx_file, line_no, line, _e[1]))
			sys.exit (-1)

		nr_pkg += 1
	
	print '%s: %d Packages processed' % (idx_file, nr_pkg)

from getopt import gnu_getopt, GetoptError

if __name__ == '__main__':
	usage = """usage: %s -p /path/to/Packages -s /path/to/Sources /path/to/pool
	moving debian (binary & source) packages to corresponding dirs according to /path/to/Packages & /path/to/Sources
	"""
 	
 	providers = {}
	def _process_src (a_pkg):
 		sep = re.compile ('[ \t]+')
 		
 		src = a_pkg['Package']
 		fs = a_pkg['Files']
 		
		_fs = (l for l in a_pkg['Files'].split ('\n') if l.strip ())
		for l in _fs:
			fis = [fi for fi in sep.split (l) if fi.strip ()]
 			assert len (fis) == 3, 'Files: fields (%s) not equal to 3' % fs
 			
 			moving (fis[2], pool, src)
 			
		bins = [b.strip () for b in a_pkg['Binary'].split (', ') if b]
		
		for b in bins:
			if providers.has_key (b):
				if src not in providers[b]:
					providers[b].append (src)
			else:
				providers[b] = [src]
						
	def _process_pkg (a_pkg):	
 		f = a_pkg['Filename']
		pkg = a_pkg['Package']
		ver = a_pkg['Version']
		
		sep = re.compile ('[ \t]+')
		
		has_source_field = a_pkg.has_key ('Source')
		has_provider = providers.has_key (pkg)
		
		src = None

		if has_source_field:
			may_many_srcs = sep.split (a_pkg['Source'])
			may_many_srcs = [src for src in may_many_srcs if not src.startswith ('(')]

			if len(may_many_srcs) == 1:
				src = may_many_srcs[0]

				if has_provider:
					if src not in providers[pkg]:
						logging.warning ('The provider("%s") specified by source field of Binary "%s" doesn\'t provide it, according *Sources* index file' % (src, pkg))
				else:
					logging.warning ('The provider("%s") specified by source field of Binary "%s" doesn\'t exist in *Sources* index file' % (src, pkg))

			else: # many source fields
				logging.warning ('Ignore Binary "%s": its source filed specifies too many providers%s' % (pkg, str(may_many_srcs)))

		else: # not has_source_field
			if has_provider:
				if len(providers[pkg]) == 1:
					logging.debug ('Binary "%s"(%s) doesn\'t have a source field' % (pkg, ver))
					src = providers[pkg][0]
				else:
					logging.warning ('Ignore Binary "%s": it doesn\'t have a source field and has more than one providers%s in *Source* index file' % (pkg, str(providers[pkg])))
			else:
				logging.warning ('Ignore Binary "%s": it doesn\'t have a source field or any provider in *Source* index file' % pkg)
		
		if src:
 			moving (f, pool, src)

	try:
		opts, left = gnu_getopt (sys.argv[1:], 'fhvp:s:', ['help', 'force', 'verbose', 'Packages=', 'Sources='])
	except GetoptError:
    		_e = sys.exc_info ()
		print >>sys.stderr, _e[1]
		print >>sys.stderr, usage % sys.argv[0]
		sys.exit (-1)

	Sources = ''
	Packages = ''
	pool = ''
	
	for o, v in opts:
		if o == '-h' or o == '--help':
			print usage % sys.argv[0]
			sys.exit (0)
		if o == '-p' or o == '--Packages':
			Packages = v
		if o == '-s' or o == '--Sources':
			Sources = v
		if o == '-v' or o == '--verbose':
			quiet = logging.INFO
		if o == 'f' or o == '--force':
			force = True
	
	if not Sources:
		print >>sys.stderr, 'please specify /path/to/Sources'
		print >>sys.stderr, usage % sys.argv[0]
		sys.exit (-1)
	
	if not Packages:
		print >>sys.stderr, 'please specify /path/to/Packages'
		print >>sys.stderr, usage % sys.argv[0]
		sys.exit (-1)
	
	if len (left) != 1:
		print >>sys.stderr, 'expect /path/to/pool'
		print >>sys.stderr, usage % sys.argv[0]
		sys.exit (-1)
	
	pool = left[0]
	if not os.path.isdir (pool):
		sys.exit ("\"%s\" is not a directory" % target)
	
	logging.basicConfig (level = quiet, format = '%(asctime)s %(levelname)s: %(message)s')
	
	try:
		walk_idx (Sources, _process_src)
		walk_idx (Packages, _process_pkg)
		for pkg in providers:
			srcs = providers[pkg]
			if len (srcs) > 1:
				print '%s mutiSource: %s' % (pkg, str (srcs))

	except KeyboardInterrupt:
		sys.exit ('Interrupt')
	except SystemExit:
		pass
	except:
		_e = sys.exc_info ()
		logging.exception ('uncached exception(%s): %s' % (_e[0], _e[1]))

