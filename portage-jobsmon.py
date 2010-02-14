#!/usr/bin/python
#	vim:fileencoding=utf-8
# Monitor current builds and display their logs on split-screen basis
# (C) 2010 Michał Górny, distributed under the terms of the 3-clause BSD license

import portage

from glob import glob

import time
import curses

# sorry for that dep, will drop it ASAP
import follow

class Screen:
	def __init__(self, root):
		self.root = root
		self.sbar = None
		self.windows = []
		self.redrawing = True
		self.backloglen = 80*25

	def addwin(self, win):
		win.win = None
		win.nwin = None
		win.backlog = ''
		self.windows.append(win)
		self.redrawing = True

	def delwin(self, win):
		del win.win
		del win.nwin
		self.windows.remove(win)
		self.redrawing = True

	def redraw(self):
		if self.redrawing:
			(height, width) = self.root.getmaxyx()
			self.backloglen = height * width
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
					self.sbar.addstr(' parallel merges')
			self.sbar.refresh()

			if jobcount > 0:
				jobrows = (height - 1) / jobcount
				if jobrows < 4:
					# XXX
					pass

				starty = 0
				for w in self.windows:
					w.win = curses.newwin(jobrows - 1, width, starty, 0)
					w.win.idlok(1)
					w.win.scrollok(1)
					w.win.addstr(0, 0, w.backlog)
					w.win.refresh()

					starty += jobrows
					w.nwin = curses.newwin(1, width, starty - 1, 0)
					w.nwin.bkgd(' ', curses.A_REVERSE)
					w.nwin.addstr(0, 0, '[%s]' % w.pkg)
					w.nwin.refresh()

			self.redrawing = False

	def append(self, w, text):
		bl = w.backlog + text
		w.backlog = bl[-self.backloglen:]

		if w.win is not None:
			w.win.addstr(text)
			w.win.refresh()

class FileTailer:
	def __init__(self, fn, pkg, scr):
		self.follow = follow.Follow(fn, True, 3)
		self.pkg = pkg
		self.scr = scr
		scr.addwin(self)

	def __call__(self):
		try:
			data = self.follow.read()
		except OSError:
			pass
		else:
			self.scr.append(self, data)

def main(cscr):
	dir = '%s/portage' % portage.settings['PORTAGE_TMPDIR']
	scr = Screen(cscr)
	mlist = {}
	ts = 0

	while True:
		if time.time() - ts > 3:
			ts = time.time()
			nlist = []
			for fn in glob('%s/*/.*.portage_lockfile' % dir):
				assert(fn.startswith(dir))
				assert(fn.endswith('.portage_lockfile'))
				pkg = ''.join(fn[len(dir)+1:-17].rsplit('.', 2))
				fn = '%s/%s/temp/build.log' % (dir, pkg)
				if fn not in mlist.keys():
					try:
						mlist[fn] = FileTailer(fn, pkg, scr)
					except IOError:
						continue
				nlist.append(fn)

			for fn in mlist.keys():
				if fn not in nlist:
					scr.delwin(mlist[fn])
					del mlist[fn]
				else:
					mlist[fn]()
		else:
			for f in mlist.values():
				f()

		scr.redraw()

if __name__ == "__main__":
	try:
		curses.wrapper(main)
	except KeyboardInterrupt:
		pass

