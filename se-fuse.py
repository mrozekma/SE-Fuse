#!/usr/bin/python
from __future__ import with_statement
import fuse
from fuse import Fuse
import stat
import os
import errno
from time import time

import urllib
import gzip
import json
import StringIO

fuse.fuse_python_api = (0, 2)

class RingBuffer:
	def __init__(self, size):
		self.k = [None for i in xrange(size)]
		self.map = {}

	def __getitem__(self, key):
		return self.map[key]

	def __setitem__(self, key, value):
		oldKey = self.k.pop(0)
		if oldKey in self.map:
			del self.map[oldKey]
		self.k.append(key)
		self.map[key] = value

	def __delitem__(self, key):
		self.k.remove(key)
		self.k.insert(0, None)
		del self.map[key]

	def __len__(self):
		return len(self.map)

	def __contains__(self, item):
		return item in self.map

	def __iter__(self):
		return self.iterkeys()

	def keys(self):
		return self.map.keys()

	def iterkeys(self):
		return self.map.iterkeys()

def api(endpoint, params = None):
	if not params: params = {}
	params['key'] = '-kzNzUSBo0CVXPYRWfCuHA'
	compressedFile = urllib.urlopen("http://api.unix.stackexchange.com/1.0/%s?%s" % (endpoint, '&'.join(["%s=%s" % i for i in params.iteritems()])))
	uncompressedFile = gzip.GzipFile(fileobj = StringIO.StringIO(compressedFile.read()))
	return json.load(uncompressedFile)

class Stats(fuse.Stat):
	id = 0

	def __init__(self, isDir, isLink):
		self.st_mode = {True: stat.S_IFDIR | 0644, False: stat.S_IFREG | 0755}[isDir]
		if isLink: self.st_mode |= stat.S_IFLNK
		self.st_ino = Stats.id
		Stats.id += 1
		self.st_dev = 0
		self.st_nlink = {True: 2, False: 1}[isDir]
		self.st_uid = os.getuid()
		self.st_gid = os.getgid()
		self.st_size = {True: 4096, False: 0}[isDir]
		self.st_atime = self.st_mtime = self.st_ctime = int(time())

class Inode:
	# path should be relative (e.g. bar instead of /foo/bar)
	def __init__(self, filename, data = '', isDir = False, isLink = False):
		assert '/' not in filename
		self.filename = filename
		self.stat = Stats(isDir, isLink)
		self.children = {}
		self.setData(data)

	def __iadd__(self, inode):
		self.children[inode.filename] = inode
		self.stat.st_nlink += 1
		return self

	def __getitem__(self, filename):
		if '/' in filename:
			if filename[-1] == '/': filename = filename[:-1]
			filename = filename.split('/')
			assert filename[0] == ''
			filename = filename[1:]

			node = self
			for part in filename:
				node = node[part]
				if not node: return None
			return node
		else:
			return self.children.get(filename, None)

	def getChildren(self): return self.children

	def getData(self): return self.data

	def setData(self, data):
		self.data = data
		self.stat.st_size = len(data)

class UserInode(Inode):
	def __init__(self, usersNode, uid):
		Inode.__init__(self, str(uid), isDir = True)
		self.usersNode = usersNode
		data = api("users/%d" % uid)
		assert data['total'] == 1
		user = data['users'][0]

		for k in ['user_type', 'display_name', 'reputation', 'email_hash', 'age', 'website_url', 'location', 'question_count', 'answer_count', 'view_count', 'up_vote_count', 'down_vote_count', 'accept_rate', 'association_id']:
			if k in user:
				self += Inode(k, "%s\n" % str(user[k]), isDir = False)
			else:
				self += Inode(k, "/dev/null", isLink = True)
		if 'creation_date' in user:
			self.stat.st_ctime = user['creation_date']
		if 'last_access_date' in user:
			self.stat.st_atime = user['last_access_date']
		if 'email_hash' in user:
			self += GravatarNode(user['email_hash'])

	def rmdir(self):
		del self.usersNode[self.filename]

class UsersInode(Inode):
	def __init__(self):
		Inode.__init__(self, "users", isDir = True)
		self.cache = RingBuffer(10)

	def __getitem__(self, filename):
		uid = int(filename)
		if not uid: return None
		if uid not in self.cache:
			self.cache[uid] = UserInode(self, uid)
		return self.cache[uid]

	def __delitem__(self, filename):
		del self.cache[int(filename)]

	def getChildren(self): return self.cache

	def removeChild(self, child):
		del self.cache[child]

class GravatarNode(Inode):
	def __init__(self, emailHash):
		Inode.__init__(self, "gravatar")
		u = urllib.urlopen("http://www.gravatar.com/avatar/%s?s=128&d=identicon&r=PG" % emailHash)
		self.setData(u.read())

class SEFS(Fuse):
	def __init__(self, *args, **kw):
		Fuse.__init__(self, *args, **kw)
		self.rootNode = Inode('', isDir = True)
		self.handles = {}

		# self.rootNode += Inode('test', True)
		self.rootNode += UsersInode()
		print "ready"

	def getattr(self, path):
		print '*** getattr ' + path + '\n'
		node = self.rootNode[path]
		if node == None: return -errno.ENOENT
		return node.stat

	def readdir(self, path, offset):
		print '*** readdir ' + path + ' ' + str(offset) + '\n'
		print self.rootNode[path]
		print self.rootNode[path].getChildren()
		for x in self.rootNode[path].getChildren(): print x
		print '-'*50
		for path in self.rootNode[path].getChildren(): yield fuse.Direntry(str(path))

	def mythread ( self ):
		print '*** mythread\n'
		return -errno.ENOSYS

	def chmod ( self, path, mode ):
		print '*** chmod ', path, oct(mode)
		return -errno.ENOSYS

	def chown ( self, path, uid, gid ):
		print '*** chown ', path, ' ', uid, ' ', gid
		return -errno.ENOSYS

	def fsync ( self, path, isFsyncFile ):
		print '*** fsync ', path, ' ', isFsyncFile
		return -errno.ENOSYS

	def link ( self, targetPath, linkPath ):
		print '*** link', ' ', targetPath, ' ', linkPath
		return -errno.ENOSYS

	def mkdir ( self, path, mode ):
		print '*** mkdir', ' ', path, ' ', oct(mode)
		return -errno.ENOSYS

	def mknod ( self, path, mode, dev ):
		print '*** mknod', ' ', path, ' ', oct(mode), ' ', dev
		return -errno.ENOSYS

	def open ( self, path, flags ):
		print '*** open', ' ', path, ' ', str(flags)
		print self.rootNode[path].getData()
		return 0

	def read ( self, path, length, offset ):
		print '*** read', ' ', path, ' ', length, ' ', offset
		print self.rootNode[path].getData()[offset : offset+length]
		return "%s" % self.rootNode[path].getData()[offset : offset+length]

	def readlink(self, path):
		print '*** readlink', ' ', path
		return self.rootNode[path].getData()

	def release ( self, path, flags ):
		print '*** release', ' ', path, ' ', flags
		return 0

	def rename ( self, oldPath, newPath ):
		print '*** rename', ' ', oldPath, ' ', newPath
		return -errno.ENOSYS

	def rmdir(self, path):
		print '*** rmdir', ' ', path
		try:
			fn = self.rootNode[path].rmdir
		except AttributeError:
			return -errno.ENOSYS

		fn()
		return 0

	def statfs ( self ):
		print '*** statfs\n'
		return -errno.ENOSYS

	def symlink ( self, targetPath, linkPath ):
		print '*** symlink', ' ', targetPath, ' ', linkPath
		return -errno.ENOSYS

	def truncate ( self, path, size ):
		print '*** truncate', ' ', path, ' ', size
		return -errno.ENOSYS

	def unlink ( self, path ):
		print '*** unlink', ' ', path
		return -errno.ENOSYS

	def utime ( self, path, times ):
		print '*** utime', ' ', path, ' ', str(times)
		return -errno.ENOSYS

	def write ( self, path, buf, offset ):
		print '*** write', ' ', path, ' ', buf, ' ', offset
		return -errno.ENOSYS


if __name__ == '__main__':
	fs = SEFS(version = fuse.__version__, usage = '', dash_s_do = 'setsingle')
	fs.parse(values = fs, errex = 1)
#	fs.multithreaded = 0
	fs.main()
