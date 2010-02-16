#!/usr/bin/python
#	vim:fileencoding=utf-8
# Monitor current builds and display their logs on split-screen basis
# (C) 2010 Michał Górny, distributed under the terms of the 3-clause BSD license

import portage

import pyinotify
import curses

class Screen:
	def __init__(self, root):
		self.root = root
		self.sbar = None
		self.windows = []
		self.redraw()

	def addwin(self, win, pkg):
		win.win = None
		win.nwin = None
		win.pkg = pkg
		win.backlog = ''
		self.windows.append(win)
		self.redraw()

	def delwin(self, win):
		del win.win
		del win.nwin
		self.windows.remove(win)
		self.redraw()

	def findwin(self, pkg):
		for w in self.windows:
			if w.pkg == pkg:
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
			if jobrows < 4:
				jobrows = 4
				jobcount = (height - 1) / jobrows

			starty = 0
			for w in self.windows:
				if jobcount > 0:
					w.win = curses.newwin(jobrows - 1, width, starty, 0)
					w.win.idlok(1)
					w.win.scrollok(1)

					w.newline = False
					w.win.move(0, 0)
					self.append(w, w.backlog, True)

					starty += jobrows
					w.nwin = curses.newwin(1, width, starty - 1, 0)
					w.nwin.bkgd(' ', curses.A_REVERSE)
					w.nwin.addstr(0, 0, '[%s]' % w.pkg)
					w.nwin.refresh()
				else: # job won't fit on the screen
					w.win = None
					w.nwin = None

				jobcount -= 1

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

def main(cscr):
	tempdir = portage.settings['PORTAGE_TMPDIR']
	pdir = '%s/portage' % tempdir
	scr = Screen(cscr)

	def ppath(dir):
		if not dir.startswith(pdir):
			return None
		dir = dir[len(pdir)+1:].split('/')
		return dir

	def pfilter(dir):
		if dir == tempdir:
			return False
		dir = ppath(dir)
		if dir is None:
			return True
		elif len(dir) == 3:
			if dir[2] != 'temp':
				return True
		elif len(dir) > 3:
			return True

		return False

	wm = pyinotify.WatchManager()

	def window_add(dir):
		pkg = '/'.join(dir[0:2])
		dir.insert(0, pdir)
		fn = '/'.join(dir)

		w = scr.findwin(pkg)
		if w is None:
			scr.addwin(FileTailer(fn), pkg)

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
					if len(dir) == 4 and dir[2] == 'temp' and dir[3] == 'build.log':
						window_add(dir)

		def process_IN_MODIFY(self, ev):
			dir = ppath(ev.pathname)
			pkg = '/'.join(dir[0:2])

			w = scr.findwin(pkg)
			if w is not None:
				data = w.pull()
				if data is not None:
					scr.append(w, data)

		def process_IN_CLOSE_WRITE(self, ev):
			dir = ppath(ev.pathname)
			pkg = '%s/%s' % (dir[0], dir[1][1:-17])

			w = scr.findwin(pkg)
			if w is not None:
				scr.delwin(w)
				del w

	np = Inotifier()
	n = pyinotify.Notifier(wm, np)
	wm.add_watch(tempdir, pyinotify.IN_CREATE,
			rec=True, auto_add=True, exclude_filter=pfilter)
	n.loop()

if __name__ == "__main__":
	try:
		curses.wrapper(main)
	except KeyboardInterrupt:
		pass

