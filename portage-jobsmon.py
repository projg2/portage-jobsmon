#!/usr/bin/python
#	vim:fileencoding=utf-8
# Monitor current builds and display their logs on split-screen basis
# (C) 2010 Michał Górny, distributed under the terms of the 3-clause BSD license

MY_PV='0.1'

import portage

import pyinotify
import curses

from optparse import OptionParser
import sys

class Screen:
	def __init__(self, root, firstpdir):
		curses.use_default_colors()

		self.root = root
		self.sbar = None
		self.windows = []
		self.firstpdir = firstpdir
		self.redraw()

	def addwin(self, win, basedir):
		win.win = None
		win.nwin = None
		win.basedir = basedir
		win.backlog = ''
		self.windows.append(win)
		self.redraw()

	def delwin(self, win):
		del win.win
		del win.nwin
		self.windows.remove(win)
		self.redraw()

	def findwin(self, basedir):
		for w in self.windows:
			if w.basedir == basedir:
				return w

		return None

	def redraw(self):
		(height, width) = self.root.getmaxyx()
		# get so much backlog so we could fill in the whole window
		# if a merge becomes the only one left
		self.backloglen = (height - 2) * width
		jobcount = len(self.windows)

		del self.sbar
		for w in self.windows:
			del w.win
			del w.nwin

		self.root.clear()
		self.root.refresh()

		self.sbar = curses.newwin(1, width, height - 1, 0)
		self.sbar.addstr(0, 0, 'portage-jobsmon.py', curses.A_BOLD)
		if jobcount == 0:
			self.sbar.addstr(' (waiting for some merge to start)')
		else:
			self.sbar.addstr(' (monitoring ')
			if jobcount == 1:
				self.sbar.addstr('single', curses.A_BOLD)
				self.sbar.addstr(' merge process)')
			else:
				self.sbar.addstr(str(jobcount), curses.A_BOLD)
				self.sbar.addstr(' parallel merges)')
		self.sbar.refresh()

		if jobcount > 0:
			jobrows = (height - 1) / jobcount
			jobrowsleft = (height - 1) % jobcount
			if jobrows < 4:
				jobrows = 4
				jobcount = (height - 1) / jobrows
				jobrowsleft = (height - 1) % jobcount
			if jobrowsleft > 0:
				jobrowsleft += 1
				jobrows += 1

			starty = 0
			for w in self.windows:
				if jobcount > 0:
					if jobrowsleft > 0:
						jobrowsleft -= 1
						if jobrowsleft == 0:
							jobrows -= 1

					w.win = curses.newwin(jobrows - 1, width, starty, 0)
					w.win.idlok(1)
					w.win.scrollok(1)

					w.newline = False
					w.win.move(0, 0)
					self.append(w, w.backlog, True)

					starty += jobrows
					w.nwin = curses.newwin(1, width, starty - 1, 0)
					w.nwin.bkgd(' ', curses.A_REVERSE)
					dir = w.basedir.rsplit('/', 2)
					w.nwin.addstr(0, 0, '[%s]' % '/'.join(dir[1:3]))
					if dir[0] != self.firstpdir:
						w.nwin.addstr(' (in %s)' % dir[0], curses.A_DIM)
					w.nwin.refresh()

					jobcount -= 1
				else: # job won't fit on the screen
					w.win = None
					w.nwin = None

	def append(self, w, text, omitbacklog = False):
		if not omitbacklog:
			bl = w.backlog + text
			w.backlog = bl[-self.backloglen:]

		if w.win is not None:
			# delay newlines to avoid wasting vertical space
			if w.newline:
				w.win.addstr('\n')
			w.newline = text.endswith('\n')
			if w.newline:
				text = text[:-1]

			w.win.addstr(text)
			w.win.refresh()

class FileTailer:
	def __init__(self, fn):
		self.fn = fn
		self.file = None

		self.reopen()

	def __del__(self):
		if self.file is not None:
			self.file.close()

	def reopen(self):
		if self.file is not None:
			self.file.close()
		self.file = open(self.fn, 'r')

	def pull(self):
		data = self.file.read()
		if len(data) == 0:
			data = None
		return data

def cursesmain(cscr, opts, args):
	if opts.tempdir is None:
		tempdir = [portage.settings['PORTAGE_TMPDIR']]
	else:
		tempdir = opts.tempdir
	pdir = ['%s/portage' % x for x in tempdir]
	firstpdir = pdir[0] # the default one
	pdir.sort(key=len, reverse=True)
	scr = Screen(cscr, firstpdir)

	def ppath(dir):
		for pd in pdir:
			if not dir.startswith(pd):
				continue
			dir = dir[len(pd)+1:].split('/')
			dir.insert(0, pd)
			return dir
		return None

	def pfilter(dir):
		if dir in tempdir:
			return False
		dir = ppath(dir)
		if dir is None:
			return True
		elif len(dir) == 4:
			if dir[3] != 'temp':
				return True
		elif len(dir) > 4:
			return True

		return False

	wm = pyinotify.WatchManager()

	def window_add(dir):
		basedir = '/'.join(dir[0:3])
		fn = '/'.join(dir)

		w = scr.findwin(basedir)
		if w is None:
			scr.addwin(FileTailer(fn), basedir)

			lockfn = '%s/%s/.%s.portage_lockfile' % tuple(dir[0:3])
			wm.add_watch(lockfn, pyinotify.IN_CLOSE_WRITE)
		else:
			w.reopen()
		wm.add_watch(fn, pyinotify.IN_MODIFY)

	class Inotifier(pyinotify.ProcessEvent):
		def process_IN_CREATE(self, ev):
			if not ev.dir:
				dir = ppath(ev.pathname)
				if dir is not None:
					if len(dir) == 5 and dir[3] == 'temp' and dir[4] == 'build.log':
						window_add(dir)

		def process_IN_MODIFY(self, ev):
			dir = ppath(ev.pathname)
			basedir = '/'.join(dir[0:3])

			w = scr.findwin(basedir)
			if w is not None:
				data = w.pull()
				if data is not None:
					scr.append(w, data)

		def process_IN_CLOSE_WRITE(self, ev):
			dir = ppath(ev.pathname)
			basedir = '%s/%s/%s' % (dir[0], dir[1], dir[2][1:-17])

			w = scr.findwin(basedir)
			if w is not None:
				scr.delwin(w)
				del w

	def timeriter(sth):
		pass

	np = Inotifier()
	n = pyinotify.Notifier(wm, np, timeout = opts.timeout * 1000)
	for t in tempdir:
		wm.add_watch(t, pyinotify.IN_CREATE,
				rec=True, auto_add=True, exclude_filter=pfilter)
	n.loop(callback = timeriter)

def main(argv):
	parser = OptionParser(
			version = '%%prog %s' % MY_PV,
			description = 'Monitor parallel emerge builds and display logs on a split-screen basis.'
		)
	parser.add_option('-t', '--tempdir', action='append', dest='tempdir',
			help="Temporary directory to watch (without the 'portage/' suffix); if specified multiple times, all specified directories will be watched; if not specified, defaults to ${PORTAGE_TEMPDIR}")
	parser.add_option('-T', '--timeout', action='store', dest='timeout', type='float', default=2,
			help='The timeout of the poll() call, and thus the max time between consecutive timer loop calls (def: 2 s)')
	(opts, args) = parser.parse_args(args = argv[1:])

	try:
		curses.wrapper(cursesmain, opts, args)
	except KeyboardInterrupt:
		pass

if __name__ == "__main__":
	sys.exit(main(sys.argv))

