#!/usr/bin/env python
# -*- coding: UTF-8 -*-
import urllib, urllib2, cookielib, HTMLParser
import re, datetime, locale, csv, codecs, cStringIO
import sys, os.path

DEBUG = True
class HTMLNode(object):
	def __init__(self, tag, attrs, pos = None):
		self.tagName = tag
		self.attributes = {}
		self.childNodes = []

		for attr in attrs:
			n, v = attr
			self.attributes[n] = v

		if self.attributes.has_key(u'id'):
			self.path_name = u'%s#%s' % (tag, self.attributes[u'id'])
		elif self.attributes.has_key('class'):
			c = u'.'.join(self.attributes[u'class'].split())
			self.path_name = u'%s.%s' % (tag, c)
		else:
			self.path_name = tag
		self.pos = pos

	def getAttribute(self, name):
		return self.attributes.get(name, u'')

	def getElementsByTagName(self, tag):
		r = []
		nn = [self.childNodes]

		for children in nn:
			for n in children:
				if n.tagName == tag:
					r.append(n)

				if n.childNodes:
					nn.append(n.childNodes)

		return r
	
	def getElementsByClassName(self, class_names):
		r = []
		nn = [self.childNodes]
	
		for children in nn:
			for n in children:
				if n.attribues.has_key(u'class'):
					class1 = class_names.split()
					class2 = n.attributes[u'class'].split()
					for c in class1:
						if c not in class2:
							break
					else:
						r.append(n)
				if n.childNodes:
					nn.append(n.childNodes)
		return r

class MyHTMLParser(HTMLParser.HTMLParser):
	def __init__(self):
		self._path = u''
		self._nodes = []
		self._hits = [getattr(self, h) for h in dir(self) if h.startswith("hit_")]

		HTMLParser.HTMLParser.__init__(self)

	def check_hits(self):
		for h in self._hits:
			if h(): break	

	def handle_starttag(self, tag, attrs):
		if tag in [u'br', u'hr', u'link', u'img', u'input']:
			return self.handle_startendtag(tag, attrs)

		nod = HTMLNode(tag, attrs, self.getpos())

		if self._nodes:
			# Parent node: Link its children
			self._nodes[-1].childNodes.append(nod)

		self._nodes.append(nod)
		self._path += u'/' + nod.path_name

	def handle_data(self, data):
		if not self._nodes: return

		nod = self._nodes[-1]

		d = getattr(nod, 'text_data', [])
		d.append(data)
		setattr(nod, 'text_data', d)

	def handle_endtag(self, tag):
		nod = self._nodes[-1]

		if nod.tagName != tag:
			try: # JIRA HTML page is really bad!! try auto merge
				top = len(self._nodes)-1
				for i in xrange(top-1, -1, -1):
					if self._nodes[i].tagName == tag:
						break
				else:
					raise HTMLParser.HTMLParseError(u"App detected: Nested tags!"
					  u"(The opening tag is '%s', but close '%s', path='%s')"
					  % (nod.tagName, tag, self._path), self.getpos())

				for j in xrange(top, i, -1):
					_tag = self._nodes[-1].tagName
					if DEBUG:
						print >>sys.stderr, u"Malform HTML page detected! " \
						  u"Auto close tag '%s', path='%s'" \
						  u"(current tag is '%s' line %d, column %d)" \
						  % (_tag, self._path, tag,
						     self.getpos()[0], self.getpos()[1])
					self.handle_endtag(_tag)
			except HTMLParser.HTMLParseError:
				if tag == 'tbody':
					if DEBUG:
						print >>sys.stderr, u"Malform HTML page detected! " \
						  u"Drop 'tbody' tag, path='%s'" \
						  u"(line %d, column %d)" \
						  % (self._path, self.getpos()[0], self.getpos()[1])
					return
				else:
					raise

		self.check_hits()

		self._path = self._path.rsplit(u'/', 1)[0]
		self._nodes.pop()

	def handle_startendtag(self, tag, attrs):
		nod = HTMLNode(tag, attrs, self.getpos())

		if self._nodes:
			# Parent node: Link its children
			self._nodes[-1].childNodes.append(nod)

		p = self._path
		self._nodes.append(nod)
		self._path += u'/' + nod.path_name

		self.check_hits()

		self._path = p
		self._nodes.pop()


def parse_jira_datetime(s):
	locale.setlocale(locale.LC_ALL, 'zh_CN.utf8')
	r = datetime.datetime.strptime(s, '%Y/%B/%d %I:%M %p')
	locale.setlocale(locale.LC_ALL, '')

	return r

def parse_jira_date(s):
	locale.setlocale(locale.LC_ALL, 'zh_CN.utf8')
	r = datetime.datetime.strptime(s, '%Y/%B/%d')
	locale.setlocale(locale.LC_ALL, '')

	return r

def parse_jira_timespent(s):
	s = re.search(u'[0-9]+(\.[0-9]+)?', s).group(0)
	return float(s)

class JiraReportHTMLParser(MyHTMLParser):
	def __init__(self):
		MyHTMLParser.__init__(self)
		self.pager = []
		self.issues = []

	def feed(self, data):
		MyHTMLParser.feed(self, data)
		if self.issues:
			assert len(self.pager) == 3, \
			       u'Failed to parse pager, got %d, expect 3' % len(self.pager)
			assert self.pager[0] == len(self.issues)
		else:
			self.pager = [0, 0, 0]

	def hit_pager(self):
		"""Process "显示<b>56</b>个问题中的 <b>1</b> 到 <b>50</b>"""
		nod = self._nodes[-1]

		if self._path.endswith(u'td.jiraformheader'):
			bs = [chld for chld in nod.childNodes if chld.tagName == u'b']
			if len(bs) != 3:
				return True

			try:
				self.pager = map(lambda chld: int(chld.text_data[0]), bs)
			except (ValueError, AttributeError):
				raise HTMLParser.HTMLParseError(
				  u"App detected: failed to parse N1, N2 and N3 in "
				  u"'显示<b>N1</b>个问题中的 <b>N2</b> 到 <b>N3</b>'",
				  nod.pos)

			# Is it finished: disable this hit
			self._hits.remove(self.hit_pager)

			return True

	def hit_issues(self):
		nod = self._nodes[-1]

		if self._path.endswith(u".nav.issuekey/a") and \
		   u'#issuerow' in self._path and \
		   u'#issuetable/' in self._path:
			data = nod.text_data[0]
			url = nod.getAttribute(u'href')

			self.issues.append((data, url))

			return True

	
class JiraIssueHTMLParser(MyHTMLParser):
	def __init__(self, issue_id, issue_url):
		MyHTMLParser.__init__(self)

		self.issue_id = issue_id
		self.issue_url = issue_url

		self.title = None # 概要
		self.men = []    # 负责人和协办人
		self.deadline = None  # 预期完成日 
		self.done_day = None  # 实际完成日
		self.resolve = None   # 解决
		self.time_spending = [] # <-- 本周投入
		self.project = None   # 与公司项目关系
		self.module = None    # 所属模块 

	def feed(self, data):
		MyHTMLParser.feed(self, data)
		assert self.title
		assert self.men
		assert self.project

	def hit_issue_header(self):
		nod = self._nodes[-1]

		if self._path.endswith(u'#issue_header'):
			rows = [i for i in nod.childNodes if i.tagName == u'tr']

			# the first row: td/table/tr/td
			r1 = rows[0].childNodes[0].childNodes[0].childNodes[0].childNodes[0]

			# 项目：b/a
			self.project = r1.childNodes[0].childNodes[0].text_data[0]

			# 标题：
			h3 = [h for h in r1.childNodes if h.path_name == u'h3.formtitle'][0]
			self.title = h3.text_data[0]

			# 预期时间: 
			font =[f for f in r1.childNodes if f.tagName == u'font'][0]
			try:
				deadline_nod = font.childNodes[2]
			except IndexError:
				pass
			else:
				datestamp = deadline_nod.text_data[0]
				self.deadline = parse_jira_date(datestamp.encode('utf-8').strip())
		
			# the second row: td/a （模块）
			try:
				module_node = rows[1].childNodes[1].childNodes[0]
			except IndexError:
				pass
			else:
				self.module = module_node.text_data[0]

			self._hits.remove(self.hit_issue_header)
			return True

	def hit_assignee(self):
		nod = self._nodes[-1]

		if re.search(u'#issue_summary_assignee_[^/]+$', self._path):
			self.men.insert(0, nod.text_data[0])

			self._hits.remove(self.hit_assignee)
			return True

	def hit_assistant(self):
		nod = self._nodes[-1]

		if self._path.endswith(u'#rowForcustomfield_10002'):
			self.men.extend(
			  [a.text_data[0] \
			   for a in nod.childNodes[1].getElementsByTagName(u'a')]
			)

			self._hits.remove(self.hit_assistant)
			return True

	def hit_change_history(self):
		nod = self._nodes[-1]

		if self._path.endswith(u'#issue_actions_container/div.actionContainer'):
			# case for '这个问题还没有改动'
			if u'#changehistory' not in nod.childNodes[0].path_name:
				return True

			row_a = nod.childNodes[0]
			row_b = nod.childNodes[1]

			# a
			ch_header = [chld for chld in row_a.childNodes if '#ch_header' in chld.path_name]
			who = ch_header[0].text_data[0].strip()

			# font/font
			timestamp = row_a.childNodes[-1].childNodes[0].text_data[0]
			timestamp = parse_jira_datetime(timestamp.encode('utf-8').strip())

			# table
			changes = row_b.childNodes[0]

			for c in changes.childNodes:
				d = c.childNodes[0].childNodes[0].text_data[0] # <-- td/b
				d = d.strip()

				if d == u'状态':
					s = c.childNodes[2].text_data[0] # <-- td
					s = s.strip()

					if s == u'关闭' or s == u'解决':
						self.done_day = timestamp 
					elif s == u'重新打开':
						self.done_day = None
						self.resolve = None
				elif d == u'解决':
					r = c.childNodes[1].text_data[0] # <-- td
					r.strip()

					self.resolve = r
				elif d == u'已花费时间':
					t1_nod = c.childNodes[1] # <-- td
					t2_nod = c.childNodes[2] # <-- td

					t1 = 0
					if hasattr(t1_nod, 'text_data'):
						tmp = t1_nod.text_data[0].strip()
						if tmp:
							t1 = parse_jira_timespent(tmp)

					tmp = t2_nod.text_data[0].strip() # <-- td 
					t2 = parse_jira_timespent(tmp)

					self.time_spending.append((who, timestamp, t2-t1))

			return True

	def get_timespending(self, begin, end):
		result = {}

		for i in xrange(len(self.time_spending)):
			who_, timestamp_, time_ = self.time_spending[i]
			if timestamp_ >= begin:
				break
		else:
			return result

		for j in xrange(i, len(self.time_spending)):
			who_, timestamp_, time_ = self.time_spending[j]
			if timestamp_ > end:
				break
			else:
				sum_time = result.get(who_, 0)
				sum_time += time_
				result[who_] = sum_time

		return result

	def format_issue_name(self):
		return u'[%s]%s' % (self.issue_id, self.title)	

	def format_issue_men(self):
		return u','.join(self.men)

	def format_issue_deadline(self):
		if self.deadline:
			return self.deadline.strftime(u'%Y/%m/%d')
		return u''

	def format_issue_done_day(self):
		if self.done_day:
			return self.done_day.strftime(u'%Y/%m/%d %H:%M')
		return u''

	def format_project_name(self):
		PROJECT_MAPPER = { u'软件部': u'其他' }
		return PROJECT_MAPPER.get(self.project, self.project)

	def format_group_name(self):
		if self.module and self.module in [u'日常事务', u'部门建设']:
			group_name = u'日常事务&部门建设'
		else:
			group_name = self.format_project_name()

		return group_name

	def format_timespending(self, begin ,end):
		sum_time = 0
		timespending_stat = self.get_timespending(begin, end)

		for w in timespending_stat:
			sum_time += timespending_stat[w]

		if sum_time:
			return u'%g小时' % sum_time
		else:
			return u''

	def format_importance(self):
		IMPORTANCE = [u'4-非常重要', u'3-重要', u'2-稍微重要', u'1-一般性/例行性']
		default = 1

		if self.module and re.match(u'[^a-zA-Z._]*kpi[^a-zA-Z._]*$', self.module, re.I):
			return IMPORTANCE[0]

		return IMPORTANCE[default]

	def format_urgency(self):
		URGENCY = [u'4-非常紧急', u'3-紧急', u'2-稍微紧急', u'1-一般性/例行性']
		default = 2

		if self.module and re.match(u'[^a-zA-Z._]*kpi[^a-zA-Z._]*$', self.module, re.I):
			return URGENCY[1]

		return URGENCY[default]

	def format_comment(self, site):
		return u"%s %s%s" % (self.resolve or '', site, self.issue_url)


class JIRA(object):
	def __init__(self, site):
		self.site = site
		self.cookie = cookielib.CookieJar()

		opener = urllib2.build_opener(
		         urllib2.HTTPCookieProcessor(self.cookie))
		urllib2.install_opener(opener)

	def login(self, user, passwd):
		url = u"%s/login.jsp" % self.site

		# Got initial cookie
		r = urllib2.urlopen(url); 

		data = urllib.urlencode(
		  ((u'os_username', user), (u'os_password', passwd),
		  (u'os_destination', u"/secure/"))
		                       )
		urllib2.urlopen(url, data); 

	def get_report(self, report_path, begin_, end_):
		report = {}
		extra_stat = {}

		url = u"%s%s" % (self.site, report_path)

		total = 1
		start = end = 0
		while end < total:
			_url = url + u'?pager/start=%d' % end
			try:
				r = urllib2.urlopen(_url); 
			except:
				print >>sys.stderr, u'!!Failed to retrieve report page %s' % _url
				raise

			report_page = r.read()

			report_parser = JiraReportHTMLParser()
			try:
				report_parser.feed(report_page.decode(u'utf-8'))
				pass
			except:
				print >>sys.stderr, \
				u"!!Something wrong when parse the report page(line %d, column %d): %s" \
				% (report_parser.getpos()[0], report_parser.getpos()[1], _url)

				if DEBUG:
					print >>sys.stderr, u"Dump the page as 'jira-report.html'!"
					print >>file(u"jira-report.html", 'w'), report_page
				raise

			for issue in report_parser.issues:
				issue_id, issue_url = issue

				_url = \
                u'%s%s?page=com.atlassian.jira.plugin.system.issuetabpanels:changehistory-tabpanel' \
                                       % (self.site, issue_url)
				try:
					r = urllib2.urlopen(_url)
				except:
					print >>sys.stderr, u'!!Failed to retrieve issue page %s' % _url
					raise

				issue_page = r.read()

				issue_parser = JiraIssueHTMLParser(issue_id, issue_url)
				try:
					issue_parser.feed(issue_page.decode(u'utf-8'))
					pass
				except:
					print >>sys.stderr, \
				u"!!Something wrong when parse the issue page(line %d, column %d): %s!" \
				% (issue_parser.getpos()[0], issue_parser.getpos()[1], _url)

					if DEBUG:
						print >>sys.stderr, \
						u"Dump the page as 'jira-%s.html'!" % issue_id
						print >>file(u"jira-%s.html" % issue_id, 'w'), issue_page
					raise


				group_name = issue_parser.format_group_name()
				group = report.get(group_name, [])

				group.append(
					(
					issue_parser.format_issue_name(),         # 本周工作事项
					issue_parser.format_issue_men(),          # 负责人
					issue_parser.format_issue_deadline(),     # 计划完成时间
					issue_parser.format_issue_done_day(),           # 实际完成时间
					issue_parser.format_comment(self.site),   # 备注
					issue_parser.format_timespending(begin_, end_), # 本周投入工时
					issue_parser.format_importance(),         # 重要程度
					issue_parser.format_urgency(),            # 紧急程度
					issue_parser.format_project_name()        # 与公司项目关系
					))

				report[group_name] = group

				timespending_stat = issue_parser.get_timespending(begin_, end_)
				for w in timespending_stat:
					sum_time = extra_stat.get(w, 0)
					sum_time += timespending_stat[w]
					extra_stat[w] = sum_time
				
			total, start, end = report_parser.pager

			return report, extra_stat

# Copy&Modify from http://docs.python.org/library/csv.html?highlight=csv#examples
class UnicodeWriter:
	"""
	A CSV writer which will write rows to CSV file "f",
	which is encoded in the given encoding.
	"""

	def __init__(self, f, dialect=csv.excel, encoding="gb2312", **kwds):
		# Redirect output to a queue
		self.queue = cStringIO.StringIO()
		self.writer = csv.writer(self.queue, dialect=dialect, **kwds)
		self.stream = f
		self.encoder = codecs.getincrementalencoder(encoding)()

	def writerow(self, row):
		self.writer.writerow([s.encode("utf-8") for s in row])

		# Fetch UTF-8 output from the queue ...
		data = self.queue.getvalue()
		data = data.decode("utf-8")

		# ... and reencode it into the target encoding
		data = self.encoder.encode(data)

		# write to the target stream
		self.stream.write(data)

		# empty queue
		self.queue.truncate(0)

	def writerows(self, rows):
		for row in rows:
			self.writerow(row)

if __name__ == '__main__':
	locale.setlocale(locale.LC_ALL, '')

	usage = '%s %s [%s] [%s]' % (
		sys.argv[0], '/path/to/abc.csv',
		"Stat Begin Weekday: 1-Last monday, 7-Last sunday]",
		"Stat End Weekday: 1-Last monday, 7-Last sunday]")

	try:
		csv_file_path = sys.argv[1]

		if os.path.abspath(csv_file_path) == os.path.abspath(__file__):
			sys.exit('Refuse to overwrite self!')

		if os.path.splitext(csv_file_path)[1] != '.csv':
			print >>sys.stderr, usage
			sys.exit("csv file name should be ended with '.csv'!")

		csv_file = file(csv_file_path, 'wb')
	except IndexError:
		sys.exit(usage)
	except IOError:
		sys.exit("Can't open file '%s'" % csv_file_path)

	now_ = datetime.datetime.now()	
	try:	
		end_weekday = int(sys.argv[3]) 
	except ValueError:
		sys.exit(usage)
	except IndexError:
		end_ = now_
	else:
		delta_day = now_.isoweekday() - end_weekday

		if delta_day == 0:
			end_ = now_
		else:
			if delta_day < 0:
				delta_day += 7
			end_ = now_ - datetime.timedelta(days = delta_day)
			end_ = datetime.datetime(end_.year, end_.month, end_.day,
			                         23, 59, 59)

	try:	
		begin_weekday = int(sys.argv[2]) 
	except ValueError:
		sys.exit(usage)
	except IndexError:
		delta_day = 6
	else:
		delta_day = end_.isoweekday() - begin_weekday
		if delta_day < 0:
			delta_day += 7
		if delta_day <= 3:
			delta_day += 7
	finally:
		begin_ = end_ - datetime.timedelta(days = delta_day)
		begin_ = datetime.datetime(begin_.year, begin_.month, begin_.day)

	print "Stat JIRA activity from '%s' to '%s'" % (
	      begin_.strftime('%Y/%m/%d %H:%M(%W %A)'), end_.strftime('%Y/%m/%d %H:%M(%W %A)'))

	jira = JIRA("http://example.jira.com")
	jira.login("<jira_user>", "<jira_passwd>")

	result, people_stat = jira.get_report(
"/secure/IssueNavigator.jspa?reset=true&mode=hide&pid=10001&sorter/order=DESC&sorter/field=priority&resolution=-1&component=10540",
	                         begin_, end_)

	print "Writing to %s" % csv_file_path
	csv_file = UnicodeWriter(csv_file)
	for grp in result:
		csv_file.writerow((grp, u'', u'', u'', u'', u'', u'', u'', u''))
		csv_file.writerows(result[grp])
		csv_file.writerow((u'', u'', u'', u'', u'', u'', u'', u'', u''))

	for w in people_stat:
		csv_file.writerow((w, u'%g小时' % people_stat[w]))
	print "\nDone"
