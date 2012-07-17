#!/usr/bin/env python

"""
Import Mantis bugs into a Trac database.

Requires:  Trac 0.9.X or newer from http://trac.edgewall.com/
           Python 2.4 from http://www.python.org/
           MySQL >= 3.23 from http://www.mysql.org/

Version 1.4
Author: John Lichovník (licho@ufo.cz)
Date: 10.9.2007

Version 1.3
Author: Anton Stroganov (stroganov.a@gmail.com)
Date: December 19, 2006

Based on version 1.1 from:
Author: Joao Prado Maia (jpm@pessoal.org)

Based on version 1.0 from:
Paul Baranowski (paul@paulbaranowski.org)

Based on bugzilla2trac.py by these guys (thank you!):
Dmitry Yusupov <dmitry_yus@yahoo.com> - bugzilla2trac.py
Mark Rowe <mrowe@bluewire.net.nz> - original TracDatabase class
Bill Soudan <bill@soudan.net> - Many enhancements 

Example use:
  python mantis2trac.py --db mantis --tracenv /usr/local/trac-projects/myproj/ \
    --host localhost --user root --clean --products foo,bar

Changes in version 1.4:
  - fixed strftime for Python 2.4
  - fixed Mantis text_id in ticket and comment queries (original version was sometimes adding mismatched descriptions and comments)
  - added IGNORE_VERSION switch

Changes since version 1.2:
  - better join in the attachment author finding query
  - changed default encoding to be utf8
  - added working status->keyword migration for statuses that don't have exact Trac equivalents

Changes since version 1.1:
  - Made it work against Trac running on MySQL (specifically, changes to the 
    LAST_INSERT_ID() call on line 382 (in the addTicket function))
  - Couple of bugfixes
  - Works fine against 10.2
  - Modified to allow specifying product list on command line
  - Modified to migrate database-stored mantis attachments correctly.
      Nota Bene!!! The script requires write access to the attachments 
      directory of the trac env. So, suggested sequence of actions: 
        - chmod -R 777 /usr/local/trac-projects/myproj/attachments/
        - run the script
        - chown -R apache /usr/local/trac-projects/myproj/attachments/
        - chgrp -R webuser /usr/local/trac-projects/myproj/attachments/
        - chmod -R 755 /usr/local/trac-projects/myproj/attachments/

Changes since version 1.0:
  - Made it to work against Trac 0.9.3 (tweaks to make the Environment class work)
  - Re-did all prepared statements-like queries to avoid a DB error
  - Fixed a reference to the wrong variable name when adding a comment

Notes:
  - Private bugs will become public
  - Some ticket changes will not be preserved since they have no 
    equivalents in Trac.
  - I consider milestones and versions to be the same thing (actually,
    I dont really care about the version, because for our project, bugs are 
    only in the 'previous version').
  - Importing attachments is not implemented (couldnt get it to work, 
    and we didnt have enough attachments to justify spending time on this)
    "Clean" will not delete your existing attachments.  There is code in here
    to support adding attachments, but you will have to play with it to 
    make it work.  If you search for the word "attachment" you will find
    all the code related to this.
  - Ticket descriptions & comments will be re-wrapped to 70 characters.
    This may mess up your formatting for your bugs.  If you dont want to do
    this, search for textwrap.fill() and fix it.
  - You will probably want to change "report.css" in trac to handle one more 
    level of priorities (default trac has 6 levels of priorities, while Mantis
    has 7).  When you look at your reports, the color schemes will look wrong.
    
    The lines that control the priority color scheme look like this:
    #tktlist tr.color1-odd  { background: #fdc; border-color: #e88; color: #a22 }
    #tktlist tr.color1-even { background: #fed; border-color: #e99; color: #a22 }
    
    I added a new level 2 ("urgent") with an orange color, 
    and incremented all the rest of the levels:
    #tktlist tr.color2-odd  { background: #FFE08F; border-color: #e88; color: #a22 }
    #tktlist tr.color2-even { background: #FFE59F; border-color: #e99; color: #a22 }
    
"""
from urllib import quote
import datetime
import time

###
### Conversion Settings -- edit these before running if desired
###

# Mantis version.  
#
# Currently, the following mantis versions are known to work:
#   0.19.X
#
# If you run this script on a version not listed here and it is successful,
# please report it to the Trac mailing list so we can update the list.
MANTIS_VERSION = '0.19'

# MySQL connection parameters for the Mantis database.  These can also 
# be specified on the command line.
MANTIS_DB = 'mantis'
MANTIS_HOST = 'localhost'
MANTIS_USER = 'root'
MANTIS_PASSWORD = ''

# Path to the Trac environment.
TRAC_ENV = ''

# If true, all existing Trac tickets will be removed 
# prior to import.
TRAC_CLEAN = True

# Enclose imported ticket description and comments in a {{{ }}} 
# preformat block?  This formats the text in a fixed-point font.
PREFORMAT_COMMENTS = False

# Products are now specified on command line.
# By default, all bugs are imported from Mantis.  If you add a list
# of products here, only bugs from those products will be imported.
# Warning: I have not tested this script where this field is blank!
# default products to ignore:
PRODUCTS = [ ]

# Trac doesn't have the concept of a product.  Instead, this script can
# assign keywords in the ticket entry to represent products.
#
# ex. PRODUCT_KEYWORDS = { 'product1' : 'PRODUCT1_KEYWORD' }
PRODUCT_KEYWORDS = {}

# Bug comments that should not be imported.  Each entry in list should
# be a regular expression.
IGNORE_COMMENTS = [
#   '^Created an attachment \(id='
]

# Ticket changes in Trac have the restriction where the
# bug ID, field, and time must be unique for all entries in the ticket 
# changes table.
# Mantis, for unknown reasons, has fields that can change two states 
# in under a second (e.g. "milestone":""->"1.0", "milestone":"1.0"->"2.0").
# Setting this to true will attempt to fix these cases by adjusting the 
# time for the 2nd change to be one second more than the original time.
# I dont know why you'd want to turn this off, but I give you the option 
# anyhow. :)
TIME_ADJUSTMENT_HACK = True

# If set to true, version numbers wont be assigned to tickets (just milestones)
IGNORE_VERSION = True

###########################################################################
### You probably don't need to change any configuration past this line. ###
###########################################################################

# Mantis status to Trac status translation map.
#
# NOTE: bug activity is translated as well, which may cause bug
# activity to be deleted (e.g. resolved -> closed in Mantis
# would translate into closed -> closed in Trac, so we just ignore the
# change).
#
# Possible Trac 'status' values: 'new', 'assigned', 'reopened', 'closed'
STATUS_TRANSLATE = {
  10 : 'new',      # 10 == 'new' in mantis
  20 : 'assigned', # 20 == 'feedback'
  30 : 'new',      # 30 == 'acknowledged' 
  40 : 'new',      # 40 == 'confirmed'
  50 : 'assigned', # 50 == 'assigned' 
  60 : 'assigned', # 60 == 'QA'
  80 : 'closed',   # 80 == 'resolved' 
  90 : 'closed'    # 90 == 'closed'
}

# Unused:
# Translate Mantis statuses into Trac keywords.  This provides a way 
# to retain the Mantis statuses in Trac.  e.g. when a bug is marked 
# 'verified' in Mantis it will be assigned a VERIFIED keyword.
# STATUS_KEYWORDS = {
#     'confirmed' : 'CONFIRMED',
#     'feedback' : 'FEEDBACK',
#     'acknowledged':'ACKNOWLEDGED',
#     'QA':'QA'
# }
STATUS_KEYWORDS = {
    20 : 'FEEDBACK',
    30 : 'ACKNOWLEDGED',
    40 : 'CONFIRMED',
    60 : 'QA',
    80 : 'RESOLVED'
}

# Possible Trac resolutions are 'fixed', 'invalid', 'wontfix', 'duplicate', 'worksforme'
RESOLUTION_TRANSLATE = {
    10 : '',          # 10 == 'open' in mantis
    20 : 'fixed',     # 20 == 'fixed'
    30 : '',          # 30 == 'reopened' (TODO: 'reopened' needs to be mapped to a status event)
    40 : 'invalid',   # 40 == 'unable to duplicate'
    50 : 'wontfix',   # 50 == 'not fixable'
    60 : 'duplicate', # 60 == 'duplicate'
    70 : 'invalid',   # 70 == 'not an issue'
    80 : '',          # 80 == 'suspended'
    90 : 'wontfix',   # 90 == 'wont fix'
}

# Mantis severities (which will also become equivalent Trac severities)
##SEVERITY_LIST = (('block', '80'), 
##                 ('crash', '70'), 
##                 ('major', '60'), 
##                 ('minor', '50'),
##                 ('tweak', '40'), 
##                 ('text', '30'), 
##                 ('trivial', '20'), 
##                 ('feature', '10'))
SEVERITY_LIST = (('block', '1'), 
                 ('crash', '2'), 
                 ('major', '3'), 
                 ('minor', '4'),
                 ('tweak', '5'), 
                 ('text', '6'), 
                 ('trivial', '7'), 
                 ('feature', '8'))

# Translate severity numbers into their text equivalents
SEVERITY_TRANSLATE = {
    80 : 'block',
    70 : 'crash',
    60 : 'major',
    50 : 'minor',
    40 : 'tweak',
    30 : 'text',
    20 : 'trivial',
    10 : 'feature'
}

# Mantis priorities (which will also become Trac priorities)
##PRIORITY_LIST = (('immediate', '60'), 
##                 ('urgent', '50'), 
##                 ('high', '40'), 
##                 ('normal', '30'), 
##                 ('low', '20'), 
##                 ('none', '10'))
PRIORITY_LIST = (('immediate', '1'), 
                 ('urgent', '2'), 
                 ('high', '3'), 
                 ('normal', '4'), 
                 ('low', '5'), 
                 ('none', '6'))

# Translate priority numbers into their text equivalent
PRIORITY_TRANSLATE = {
    60 : 'immediate', 
    50 : 'urgent', 
    40 : 'high',
    30 : 'normal', 
    20 : 'low', 
    10 : 'none'
}


# Some fields in Mantis do not have equivalents in Trac.  Changes in
# fields listed here will not be imported into the ticket change history,
# otherwise you'd see changes for fields that don't exist in Trac.
IGNORED_ACTIVITY_FIELDS = ['', 'project_id', 'reproducibility', 'view_state', 'os', 'os_build', 'duplicate_id']

###
### Script begins here
###

import os
import re
import sys
import string
import StringIO

import MySQLdb
import MySQLdb.cursors
from trac.env import Environment

if not hasattr(sys, 'setdefaultencoding'):
    reload(sys)

sys.setdefaultencoding('utf-8')

# simulated Attachment class for trac.add
# unused in 1.2
class Attachment:
    def __init__(self, name, data):
        self.filename = name
        self.file = StringIO.StringIO(data.tostring())
  
# simple field translation mapping.  if string not in
# mapping, just return string, otherwise return value
class FieldTranslator(dict):
    def __getitem__(self, item):
        if not dict.has_key(self, item):
            return item
            
        return dict.__getitem__(self, item)

statusXlator = FieldTranslator(STATUS_TRANSLATE)

class TracDatabase(object):
    def __init__(self, path):
        self.env = Environment(path)
        self._db = self.env.get_db_cnx()
        self._db.autocommit = False
        self.loginNameCache = {}
        self.fieldNameCache = {}
    
    def db(self):
        return self._db
    
    def hasTickets(self):
        c = self.db().cursor()
        c.execute('''SELECT count(*) FROM ticket''')
        return int(c.fetchall()[0][0]) > 0

    def assertNoTickets(self):
        if self.hasTickets():
            raise Exception("Will not modify database with existing tickets!")
    
    def setSeverityList(self, s):
        """Remove all severities, set them to `s`"""
        self.assertNoTickets()
        
        c = self.db().cursor()
        c.execute("""DELETE FROM enum WHERE type='severity'""")
        for value, i in s:
            print "inserting severity ", value, " ", i
            c.execute("""INSERT INTO enum (type, name, value) VALUES (%s, %s, %s)""",
                      ("severity", value.encode('utf-8'), i,))
        self.db().commit()
    
    def setPriorityList(self, s):
        """Remove all priorities, set them to `s`"""
        self.assertNoTickets()
        
        c = self.db().cursor()
        c.execute("""DELETE FROM enum WHERE type='priority'""")
        for value, i in s:
            print "inserting priority ", value, " ", i
            c.execute("""INSERT INTO enum (type, name, value) VALUES (%s, %s, %s)""",
                      ("priority", value.encode('utf-8'), i,))
        self.db().commit()

    
    def setComponentList(self, l, key):
        """Remove all components, set them to `l`"""
        self.assertNoTickets()
        
        c = self.db().cursor()
        c.execute("""DELETE FROM component""")
        for comp in l:
            print "inserting component '",comp[key],"', owner",  comp['owner']
            c.execute("""INSERT INTO component (name, owner) VALUES (%s, %s)""",
                      (comp[key].encode('utf-8'), comp['owner'].encode('utf-8'),))
        self.db().commit()
    
    def setVersionList(self, v, key):
        """Remove all versions, set them to `v`"""
        self.assertNoTickets()
        
        c = self.db().cursor()
        c.execute("""DELETE FROM version""")
        for vers in v:
            print "inserting version ", vers[key]
            c.execute("""INSERT INTO version (name) VALUES (%s)""",
                      (vers[key].encode('utf-8'),))
        self.db().commit()
        
    def setMilestoneList(self, m, key):
        """Remove all milestones, set them to `m`"""
        self.assertNoTickets()
        
        c = self.db().cursor()
        c.execute("""DELETE FROM milestone""")
        for ms in m:
            print "inserting milestone ", ms[key]
            c.execute("""INSERT INTO milestone (name) VALUES (%s)""",
                      (ms[key].encode('utf-8'),))
        self.db().commit()
    
    def addTicket(self, id, time, changetime, component,
                  severity, priority, owner, reporter, cc,
                  version, milestone, status, resolution,
                  summary, description, keywords):
        c = self.db().cursor()
        if IGNORE_VERSION:
          version=''
        
        desc = description.encode('utf-8')
        
        if PREFORMAT_COMMENTS:
          desc = '{{{\n%s\n}}}' % desc

        print "inserting ticket %s -- \"%s\"" % (id, summary[0:40].replace("\n", " "))
        c.execute("""INSERT INTO ticket (id, time, changetime, component,
                                         severity, priority, owner, reporter, cc,
                                         version, milestone, status, resolution,
                                         summary, description, keywords)
                                 VALUES (%s, %s, %s, %s,
                                         %s, %s, %s, %s, %s,
                                         %s, %s, %s, %s,
                                         %s, %s, %s)""",
                  (id, self.convertTime(time), self.convertTime(changetime), component.encode('utf-8'),
                  severity.encode('utf-8'), priority.encode('utf-8'), owner, reporter, cc,
                  version, milestone.encode('utf-8'), status.lower(), resolution,
                  summary.encode('utf-8'), desc, keywords))

        self.db().commit()
        
        ## TODO: add database-specific methods to get the last inserted ticket's id...
        ## PostgreSQL:
        # c.execute('''SELECT currval("ticket_id_seq")''')
        ## SQLite:
        # c.execute('''SELECT last_insert_rowid()''')
        ## MySQL:
        # c.execute('''SELECT LAST_INSERT_ID()''')
        # Oh, Trac db abstraction layer already has a function for this...
        return self.db().get_last_id(c,'ticket')

    def convertTime(self,time2):
        return time.mktime(time2.timetuple())+1e-6*time2.microsecond
    
    def addTicketComment(self, ticket, time, author, value):
        print " * adding comment \"%s...\"" % value[0:40]
        comment = value.encode('utf-8')
        
        if PREFORMAT_COMMENTS:
          comment = '{{{\n%s\n}}}' % comment

        c = self.db().cursor()
        c.execute("""INSERT INTO ticket_change (ticket, time, author, field, oldvalue, newvalue)
                                 VALUES        (%s, %s, %s, %s, %s, %s)""",
                  (ticket, self.convertTime(time), author, 'comment', '', comment))
        self.db().commit()

    def addTicketChange(self, ticket, time, author, field, oldvalue, newvalue):
        if (field[0:4]=='doba'): 
          return

        print " * adding ticket change \"%s\": \"%s\" -> \"%s\" (%s)" % (field, oldvalue[0:20], newvalue[0:20], time)
        c = self.db().cursor()
        c.execute("""INSERT INTO ticket_change (ticket, time, author, field, oldvalue, newvalue)
                                 VALUES        (%s, %s, %s, %s, %s, %s)""",
                  (ticket, self.convertTime(time), author, field, oldvalue.encode('utf-8'), newvalue.encode('utf-8')))
        self.db().commit()
        # Now actually change the ticket because the ticket wont update itself!
        sql = "UPDATE ticket SET %s='%s' WHERE id=%s" % (field, newvalue, ticket)
        c.execute(sql)
        self.db().commit()        
        
    # unused in 1.2
    def addAttachment(self, id, attachment, description, author):
        print 'inserting attachment for ticket %s -- %s' % (id, description)
        attachment.filename = attachment.filename.encode('utf-8')
        self.env.create_attachment(self.db(), 'ticket', str(id), attachment, description.encode('utf-8'),
            author, 'unknown')
        
    def getLoginName(self, cursor, userid):
        if userid not in self.loginNameCache:
            cursor.execute("SELECT username,email,realname,last_visit FROM mantis_user_table WHERE id = %i" % int(userid))
            result = cursor.fetchall()

            if result:
                loginName = result[0]['username']
                print 'Adding user %s to sessions table' % loginName
                c = self.db().cursor()

                # check if user is already in the sessions table
                c.execute("SELECT sid FROM session WHERE sid = '%s'" % result[0]['username'].encode('utf-8'))
                r = c.fetchall()
                
                # if there was no user sid in the database already
                if not r:
                    # pre-populate the session table and the realname/email table with user data
                    try:
                        c.execute(
                        """INSERT INTO session 
                            (sid, authenticated, last_visit) 
                        VALUES (%s, %s, %s)""",(result[0]['username'].encode('utf-8'), '1', self.convertTime(result[0]['last_visit'])))
                    except:
                        print 'failed executing sql: '
                        print """INSERT INTO session 
                            (sid, authenticated, last_visit) 
                        VALUES """, (result[0]['username'].encode('utf-8'), '1', self.convertTime(result[0]['last_visit']))
                        print 'could not insert %s into sessions table: sql error %s ' % (loginName, self.db().error())
                    self.db().commit()
                
                    # insert the user's real name into session attribute table
                    c.execute(
                        """INSERT INTO session_attribute 
                            (sid, authenticated, name, value)
                        VALUES
                            (%s, %s, %s, %s)""", (result[0]['username'].encode('utf-8'), '1', 'name', result[0]['realname'].encode('utf-8')))
                    self.db().commit()

                    # insert the user's email into session attribute table
                    c.execute(
                        """INSERT INTO session_attribute 
                            (sid, authenticated, name, value)
                        VALUES
                            (%s, %s, %s, %s)""", (result[0]['username'].encode('utf-8'), '1', 'email', result[0]['email'].encode('utf-8')))
                    self.db().commit()
            else:
                print 'warning: unknown mantis userid %d, recording as anonymous' % userid
                loginName = 'anonymous'

            self.loginNameCache[userid] = loginName

        return self.loginNameCache[userid]

    def get_attachments_dir(self,bugid=0):
        if bugid > 0:
            return self.env.path + 'attachments/ticket/%i/' % bugid        
        else:
            return self.env.path + 'attachments/ticket/'

    def _mkdir(newdir):
        """works the way a good mkdir should :)
            - already exists, silently complete
            - regular file in the way, raise an exception
            - parent directory(ies) does not exist, make them as well
        """
        if os.path.isdir(newdir):
            pass
        elif os.path.isfile(newdir):
            raise OSError("a file with the same name as the desired " \
                          "dir, '%s', already exists." % newdir)
        else:
            head, tail = os.path.split(newdir)
            if head and not os.path.isdir(head):
                _mkdir(head)
            #print "_mkdir %s" % repr(newdir)
            if tail:
                os.mkdir(newdir)

def productFilter(fieldName, products):
    first = True
    result = ''
    for product in products:
        if not first: 
            result += " or "
        first = False
        result += "%s = '%s'" % (fieldName, product)
    return result

def convert(_db, _host, _user, _password, _env, _force):
    activityFields = FieldTranslator()

    # account for older versions of mantis
    if MANTIS_VERSION == '0.19':
        print 'Using Mantis v%s schema.' % MANTIS_VERSION
        activityFields['removed'] = 'oldvalue'
        activityFields['added'] = 'newvalue'

    # init Mantis environment
    print "Mantis MySQL('%s':'%s':'%s':'%s'): connecting..." % (_db, _host, _user, _password)
    mysql_con = MySQLdb.connect(host=_host, 
                user=_user, passwd=_password, db=_db, compress=1, 
                cursorclass=MySQLdb.cursors.DictCursor, use_unicode=1)
    mysql_cur = mysql_con.cursor()

    # init Trac environment
    print "Trac database('%s'): connecting..." % (_env)
    trac = TracDatabase(_env)

    # force mode...
    if _force == 1:
        print "cleaning all tickets..."
        c = trac.db().cursor()
        c.execute("""DELETE FROM ticket_change""")
        trac.db().commit()
        c.execute("""DELETE FROM ticket""")
        trac.db().commit()
        c.execute("""DELETE FROM attachment""")
        os.system('rm -rf %s' % trac.get_attachments_dir())
        os.mkdir(trac.get_attachments_dir())
        trac.db().commit()

    print
    print '0. Finding project IDs...'
    sql =  "SELECT id, name FROM mantis_project_table"
    if PRODUCTS:
        sql += " WHERE %s" % productFilter('name', PRODUCTS)
    mysql_cur.execute(sql)
    project_list = mysql_cur.fetchall()
    project_dict = dict()
    for project_id in project_list:
        print "Mantis project name '%s' has project ID %s" % (project_id['name'], project_id['id'])
        project_dict[project_id['id']] = project_id['id']
        
    print
    print "1. import severities..."
    trac.setSeverityList(SEVERITY_LIST)

    print
    print "2. import components..."
    sql = "SELECT category, user_id as owner FROM mantis_project_category_table"
    if PRODUCTS:
       sql += " WHERE %s" % productFilter('project_id', project_dict)
    print "sql: %s" % sql
    mysql_cur.execute(sql)
    components = mysql_cur.fetchall()
    for component in components:
        component['owner'] = trac.getLoginName(mysql_cur, component['owner'])
    trac.setComponentList(components, 'category')

    print
    print "3. import priorities..."
    trac.setPriorityList(PRIORITY_LIST)

    print
    print "4. import versions..."
    sql = "SELECT DISTINCTROW version FROM mantis_project_version_table"
    if PRODUCTS:
       sql += " WHERE %s" % productFilter('project_id', project_dict)
    mysql_cur.execute(sql)
    versions = mysql_cur.fetchall()
    trac.setVersionList(versions, 'version')

    print
    print "5. import milestones..."
    sql = "SELECT version FROM mantis_project_version_table"
    if PRODUCTS:
       sql += " WHERE %s" % productFilter('project_id', project_dict)
    mysql_cur.execute(sql)
    milestones = mysql_cur.fetchall()
    trac.setMilestoneList(milestones, 'version')

    print
    print '6. retrieving bugs...'
    sql = "SELECT * FROM mantis_bug_table "
    if PRODUCTS:
       sql += " WHERE %s" % productFilter('project_id', project_dict)
    sql += " ORDER BY id"
    mysql_cur.execute(sql)
    bugs = mysql_cur.fetchall()
    
    print
    print "7. import bugs and bug activity..."
    totalComments = 0
    totalTicketChanges = 0
    totalAttachments = 0
    errors = []
    timeAdjustmentHacks = []
    for bug in bugs:
        bugid = bug['id']
        
        ticket = {}
        keywords = []
        ticket['id'] = bugid
        ticket['time'] = bug['date_submitted']
        ticket['changetime'] = bug['last_updated']
        ticket['component'] = bug['category']
        ticket['severity'] = SEVERITY_TRANSLATE[bug['severity']]
        ticket['priority'] = PRIORITY_TRANSLATE[bug['priority']]
        ticket['owner'] = trac.getLoginName(mysql_cur, bug['handler_id'])
        ticket['reporter'] = trac.getLoginName(mysql_cur, bug['reporter_id'])
        ticket['version'] = bug['version']
        if IGNORE_VERSION:
          ticket['version'] = ''
        ticket['milestone'] = bug['version']
        ticket['summary'] = bug['summary']
        ticket['status'] = STATUS_TRANSLATE[bug['status']]
        ticket['cc'] = ''
        ticket['keywords'] = ''

        # Special case for 'reopened' resolution in mantis - 
        # it maps to a status type in Trac.
        if (bug['resolution'] == 30):
            ticket['status'] = 'reopened'
        ticket['resolution'] = RESOLUTION_TRANSLATE[bug['resolution']]
        
        # Compose the description from the three text fields in Mantis:
        # 'description', 'steps_to_reproduce', 'additional_information'
        mysql_cur.execute("SELECT * FROM mantis_bug_text_table WHERE id = %s" % bug['bug_text_id']) 
        longdescs = list(mysql_cur.fetchall())

        # check for empty 'longdescs[0]' field...
        if len(longdescs) == 0:
            ticket['description'] = ''
        else:
            tmpDescr = longdescs[0]['description']
            if (longdescs[0]['steps_to_reproduce'].strip() != ''):
               tmpDescr = ('%s\n\nSTEPS TO REPRODUCE:\n%s') % (tmpDescr, longdescs[0]['steps_to_reproduce'])
            if (longdescs[0]['additional_information'].strip() != ''):
               tmpDescr = ('%s\n\nADDITIONAL INFORMATION:\n%s') % (tmpDescr, longdescs[0]['additional_information'])
            ticket['description'] = tmpDescr
            del longdescs[0]

        # Add the ticket to the Trac database
        trac.addTicket(**ticket)
        
        #
        # Add ticket comments
        #
        mysql_cur.execute("SELECT * FROM mantis_bugnote_table, mantis_bugnote_text_table WHERE bug_id = %s AND mantis_bugnote_table.bugnote_text_id = mantis_bugnote_text_table.id ORDER BY date_submitted" % bugid)
        bug_notes = mysql_cur.fetchall()
        totalComments += len(bug_notes)
        for note in bug_notes:
            trac.addTicketComment(bugid, note['date_submitted'], trac.getLoginName(mysql_cur, note['reporter_id']), note['note'])

        #
        # Convert ticket changes
        #
        mysql_cur.execute("SELECT * FROM mantis_bug_history_table WHERE bug_id = %s ORDER BY date_modified" % bugid)
        bugs_activity = mysql_cur.fetchall()
        resolution = ''
        ticketChanges = []
        keywords = []
        for activity in bugs_activity:
            field_name = activity['field_name'].lower()
            # Convert Mantis field names...
            # The following fields are the same in Mantis and Trac:
            #  - 'status'
            #  - 'priority'
            #  - 'summary'
            #  - 'resolution'
            #  - 'severity'
            #  - 'version'
            #
            # Ignore the following changes:
            #  - project_id
            #  - reproducibility
            #  - view_state
            #  - os
            #  - os_build
            #  - duplicate_id
            #
            # Convert Mantis -> Trac:
            #  - 'handler_id' -> 'owner'
            #  - 'fixed_in_version' -> 'milestone'
            #  - 'category' -> 'component'
            #  - 'version' -> 'milestone'
            
            ticketChange = {}
            ticketChange['ticket'] = bugid
            ticketChange['oldvalue'] = activity['old_value']
            ticketChange['newvalue'] = activity['new_value']
            ticketChange['time'] = activity['date_modified']
            ticketChange['author'] = trac.getLoginName(mysql_cur, activity['user_id'])
            ticketChange['field'] = field_name

            add_keywords = []
            remove_keywords = []
            
            if field_name == 'handler_id':
                ticketChange['field'] = 'owner'
                ticketChange['oldvalue'] = trac.getLoginName(mysql_cur, int(activity['old_value']))
                ticketChange['newvalue'] = trac.getLoginName(mysql_cur, int(activity['new_value']))
            elif field_name == 'fixed_in_version':
                ticketChange['field'] = 'milestone'
            elif field_name == 'category':
                ticketChange['field'] = 'component'
            elif field_name == 'version':
                ticketChange['field'] = 'milestone'
            elif field_name == 'status':
                ticketChange['oldvalue'] = STATUS_TRANSLATE[int(activity['old_value'])]
                ticketChange['newvalue'] = STATUS_TRANSLATE[int(activity['new_value'])]
                if int(activity['old_value']) in STATUS_KEYWORDS:
                    remove_keywords.append(STATUS_KEYWORDS[int(activity['old_value'])])
                if int(activity['new_value']) in STATUS_KEYWORDS:
                    add_keywords.append(STATUS_KEYWORDS[int(activity['new_value'])])
                
            elif field_name == 'priority':
                ticketChange['oldvalue'] = PRIORITY_TRANSLATE[int(activity['old_value'])]
                ticketChange['newvalue'] = PRIORITY_TRANSLATE[int(activity['new_value'])]
            elif field_name == 'resolution':
                ticketChange['oldvalue'] = RESOLUTION_TRANSLATE[int(activity['old_value'])]
                ticketChange['newvalue'] = RESOLUTION_TRANSLATE[int(activity['new_value'])]
            elif field_name == 'severity':
                ticketChange['oldvalue'] = SEVERITY_TRANSLATE[int(activity['old_value'])]
                ticketChange['newvalue'] = SEVERITY_TRANSLATE[int(activity['new_value'])]            

            if add_keywords or remove_keywords:
                # ensure removed ones are in old
                old_keywords = keywords + [kw for kw in remove_keywords if kw not in keywords]
                # remove from new
                keywords = [kw for kw in keywords if kw not in remove_keywords]
                # add to new
                keywords += [kw for kw in add_keywords if kw not in keywords]
                if old_keywords != keywords:
                    ticketChangeKw = ticketChange.copy()
                    ticketChangeKw['field'] = "keywords"
                    ticketChangeKw['oldvalue'] = ' '.join(old_keywords)
                    ticketChangeKw['newvalue'] = ' '.join(keywords)
                    ticketChanges.append(ticketChangeKw)
                                
            if field_name in IGNORED_ACTIVITY_FIELDS:
                continue

            # skip changes that have no effect (think translation!)
            if ticketChange['oldvalue'] == ticketChange['newvalue']:
                continue
                
            ticketChanges.append (ticketChange)

        totalTicketChanges += len(ticketChanges)
        for ticketChange in ticketChanges:
            try:
                trac.addTicketChange (**ticketChange)
            except:
                if TIME_ADJUSTMENT_HACK:
                    addTime = datetime.timedelta(seconds=1)
                    originalTime = ticketChange['time']
                    ticketChange['time'] += addTime
                    try:
                        trac.addTicketChange(**ticketChange)
                        noticeStr = " ~ Successfully adjusted time for ticket(#%s) change \"%s\": \"%s\" -> \"%s\" (%s)" % (bugid, ticketChange['field'], ticketChange['oldvalue'], ticketChange['newvalue'], ticketChange['time'])
                        noticeStr += "\n   Original time: %s" % originalTime
                        timeAdjustmentHacks.append(noticeStr)
                    except:
                        errorStr =  " * ERROR: unable to add ticket(#%s) change \"%s\": \"%s\" -> \"%s\" (%s)" % (bugid, ticketChange['field'], ticketChange['oldvalue'], ticketChange['newvalue'], ticketChange['time'])
                        errorStr += "\n          The bug id, field name, and time must be unique"
                        errors.append(errorStr)
                        print errorStr
                else:
                    errorStr =  " * ERROR: unable to add ticket(#%s) change \"%s\": \"%s\" -> \"%s\" (%s)" % (bugid, ticketChange['field'], ticketChange['oldvalue'], ticketChange['newvalue'], ticketChange['time'])
                    errorStr += "\n          The bug id, field name, and time must be unique"
                    errors.append(errorStr)
                    print errorStr
                

        #
        # Add ticket file attachments
        #
        attachment_sql = "SELECT b.id,b.bug_id,b.title,b.description,b.filename,b.filesize,b.file_type,UNIX_TIMESTAMP(b.date_added) AS date_added, b.content, h.user_id FROM mantis_bug_file_table AS b LEFT JOIN mantis_bug_history_table AS h ON (h.type = 9 AND h.old_value = b.filename AND h.bug_id = b.bug_id) WHERE b.bug_id = %s" % bugid
        # print attachment_sql
        mysql_cur.execute(attachment_sql)
        attachments = mysql_cur.fetchall()
        for attachment in attachments:
            author = trac.getLoginName(mysql_cur, attachment['user_id'])

            # Old attachment stuff that never worked...
            # attachmentFile = open(attachment['diskfile'], 'r')
            # attachmentData = attachmentFile.read()
            # tracAttachment = Attachment(attachment['filename'], attachmentData)
            # trac.addAttachment(bugid, tracAttachment, attachment['description'], author)

            try:
                try:
                    if(os.path.isdir(trac.get_attachments_dir(bugid)) == False):
                        try:
                            os.mkdir(trac.get_attachments_dir(bugid))
                        except:
                            errorStr = " * ERROR: couldnt create attachment directory in filesystem at %s" % trac.get_attachments_dir(bugid)
                            errors.append(errorStr)
                            print errorStr
                    # trac stores the files with the special characters like spaces in the filename encoded to the url 
                    # equivalents, so we have to urllib.quote() the filename we're saving. 
                    attachmentFile = open(trac.get_attachments_dir(bugid) + quote(attachment['filename']),'wb')
                    attachmentFile.write(attachment['content'])
                    attachmentFile.close()
                except:
                    errorStr = " * ERROR: couldnt dump attachment data into filesystem at %s" % trac.get_attachments_dir(bugid) + attachment['filename']
                    errors.append(errorStr)
                    print errorStr
                else:
                    attach_sql = """INSERT INTO attachment (type,id,filename,size,time,description,author,ipnr) VALUES ('ticket',%s,'%s',%i,%i,'%s','%s','127.0.0.1')""" % (bugid,attachment['filename'].encode('utf-8'),attachment['filesize'],attachment['date_added'],attachment['description'].encode('utf-8'),author)
                    try:
                        c = trac.db().cursor()
                        c.execute(attach_sql)
                        trac.db().commit()
                    except:
                        errorStr = " * ERROR: couldnt insert attachment data into database with %s" % attach_sql
                        errors.append(errorStr)
                        print errorStr
                    else:
                        print 'inserting attachment for ticket %s -- %s, added by %s' % (bugid, attachment['description'], author)

                        totalAttachments += 1
            except:
                errorStr = " * ERROR: couldn't migrate attachment %s" % attachment['filename']
                errors.append(errorStr)
                print errorStr

    print
    if TIME_ADJUSTMENT_HACK:
        for adjustment in timeAdjustmentHacks:
            print adjustment
    if len(errors) != 0:
        print "Some errors occurred while importing:"
        for error in errors:
            print error
    else: 
        print "Success!"
    print
    print "Total tickets imported: %d" % len(bugs)
    print "Total ticket comments:  %d" % totalComments
    print "Total ticket changes:   %d" % totalTicketChanges
    print "Total attachments:      %d" % totalAttachments
    print

def usage():
    print "mantis2trac - Imports a bug database from Mantis into Trac."
    print
    print "Usage: mantis2trac.py [options]"
    print
    print "Available Options:"
    print "  --db <MySQL dbname>              - Mantis database"
    print "  --tracenv /path/to/trac/env/     - Full path to Trac environment"
    print "  -h | --host <MySQL hostname>     - Mantis DNS host name"
    print "  -u | --user <MySQL username>     - Effective Mantis database user"
    print "  -p | --passwd <MySQL password>   - Mantis database user password"
    print "  -c | --clean                     - Remove current Trac tickets before importing"
    print "  --products <product1,product2>   - List of products to import from mantis"
    print "  --help | help                    - This help info"
    print
    print "Note:   If you want the ticket attachments to be converted, you MUST run the script"
    print "        as a user who has write permissions to the trac env attachments directory."
    print "Note 2: Attachment conversion only works for attachments stored directly in the mantis"
    print "        database at this point."
    print
    print "Additional configuration options can be defined directly in the script."
    print
    sys.exit(0)

def main():
    global MANTIS_DB, MANTIS_HOST, MANTIS_USER, MANTIS_PASSWORD, TRAC_ENV, TRAC_CLEAN, PRODUCTS
    if len (sys.argv) > 1:
        if sys.argv[1] in ['--help','help'] or len(sys.argv) < 4:
            usage()
        iter = 1
        while iter < len(sys.argv):
            if sys.argv[iter] in ['--db'] and iter+1 < len(sys.argv):
                MANTIS_DB = sys.argv[iter+1]
                iter = iter + 1
            elif sys.argv[iter] in ['-h', '--host'] and iter+1 < len(sys.argv):
                MANTIS_HOST = sys.argv[iter+1]
                iter = iter + 1
            elif sys.argv[iter] in ['-u', '--user'] and iter+1 < len(sys.argv):
                MANTIS_USER = sys.argv[iter+1]
                iter = iter + 1
            elif sys.argv[iter] in ['-p', '--passwd'] and iter+1 < len(sys.argv):
                MANTIS_PASSWORD = sys.argv[iter+1]
                iter = iter + 1
            elif sys.argv[iter] in ['--tracenv'] and iter+1 < len(sys.argv):
                TRAC_ENV = sys.argv[iter+1]
                iter = iter + 1
            elif sys.argv[iter] in ['-c', '--clean']:
                TRAC_CLEAN = 1
            elif sys.argv[iter] in ['--products'] and iter+1 < len(sys.argv):
                PRODUCTS = sys.argv[iter+1].split(',')
                iter = iter + 1
            else:
                print "Error: unknown parameter: " + sys.argv[iter]
                sys.exit(0)
            iter = iter + 1
    else:
        usage()
        
    convert(MANTIS_DB, MANTIS_HOST, MANTIS_USER, MANTIS_PASSWORD, TRAC_ENV, TRAC_CLEAN)

if __name__ == '__main__':
    main()
