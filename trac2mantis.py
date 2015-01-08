#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Import Trac bugs into a Mantis database.

Requires:  Trac 1.0.1 or newer from http://trac.edgewall.com/
           Mantis 1.2.18 from http://www.mantisbt.org/
           Python 2.4 from http://www.python.org/
           MySQL >= 3.23 from http://www.mysql.org/

Steffen Mecke <stm2@users.sourceforge.net>

Based on mantis2trac
Dmitry Yusupov <dmitry_yus@yahoo.com> - bugzilla2trac.py
Mark Rowe <mrowe@bluewire.net.nz> - original TracDatabase class
Bill Soudan <bill@soudan.net> - Many enhancements 

Example use:
  python trac2mantis.py --db mantis --tracenv /usr/local/trac-projects/myproj/ \
    --host localhost --user root --clean 

Known bugs:
  Attachment are not converted

    
"""
from urllib import quote
from datetime import datetime, date
import time
import hashlib
import uuid
import random

###
### Conversion Settings -- edit these before running if desired
###

# Mantis version.  
#
# Currently, the following mantis versions are known to work:
#   1.0.1
#
# If you run this script on a version not listed here and it is successful,
# please report it to the Trac mailing list so we can update the list.
MANTIS_VERSION = '1.0.1'

# MySQL connection parameters for the Mantis database.  These can also 
# be specified on the command line.
MANTIS_DB = 'mantis_db'
MANTIS_HOST = 'localhost'
MANTIS_USER = 'mantis_user'
MANTIS_PASSWORD = 'passphrase'

# Path to the Trac environment.
TRAC_ENV = '/var/www/trac/testproject/'

# If true, all existing Trac tickets will be removed 
# prior to import.
MANTIS_CLEAN = False
# If TRAC_CLEAN is true and this is true, tickets will be appended
MANTIS_APPEND = True

# all bugs are imported into this project
PROJECT = "Magellan 2"

# name and email of created users
NN_NAME = "N. N."
NN_EMAIL = "noreply@localhost"

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

STATUS_TRAC_MANTIS = {
    'new'      : 10,
    'reopened' : 20,
    'accepted' : 30,
    'assigned' : 50,
    'closed'   : 90
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

RESOLUTION_TRAC_MANTIS = {
    None : 10,
    '' : 10,
    'duplicate' : 60,
    'fixed' : 20,
    'invalid' : 70,
    'wontfix' : 90,
    'worksforme' : 40
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

SEVERITY_TRAC_MANTIS = {
    None : 50,
    'block' : 80,
    'crash' : 70,
    'major' : 60,
    'minor' : 50,
    'tweak' : 40,
    'text' : 30,
    'trivial' : 20,
    'feature' : 10,
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

PRIORITY_TRAC_MANTIS = {
    'trivial' : 20,
    'minor' : 20,
    'low' : 20,
    'normal' : 30,
    'high' : 40,
    'major' : 50,
    'critical' : 60
}

EDIT_TYPES_NONE = 0
EDIT_TYPES_NOTE_ADDED = 2

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

class TracDatabase(object):
    def __init__(self, project_name, path, db, host, user, password, append):
        self.env = Environment(path)
        self._append = append

        self._tracdb = self.env.get_db_cnx()
        self._tracdb.autocommit = False
        self._trac_cursor = self._tracdb.cursor()
        self._mantis_con = MySQLdb.connect(host=host, 
                user=user, passwd=password, db=db, compress=1, 
                cursorclass=MySQLdb.cursors.DictCursor, use_unicode=1)
        self._mantis_cursor = self._mantis_con.cursor()

        sql = "SELECT id FROM mantis_project_table WHERE name = %s" % (project_name)
        print sql
        self.mantisCursor().execute("SELECT id FROM mantis_project_table WHERE name = %s", (project_name))
        result = self.mantisCursor().fetchall()
        if len(result) > 1:
            raise Exception("Ambiguous project name %s" % project_name)
        elif len(result) == 0:
            sql = """INSERT INTO mantis_project_table (name) VALUES (%s)""" % (project_name)
            print sql
            self.mantisCursor().execute("""INSERT INTO mantis_project_table (name) VALUES (%s)""" , (project_name))
            self.mantisCommit()
            self._project_id = int(self.mantisCursor().lastrowid)
        else:
            self._project_id = int(result[0]['id'])

        self._bug_map = {}
        self._user_map = {}
        self._category_map = {}
        
    def projectId(self):
        return self._project_id

    def tracCursor(self):
        return self._trac_cursor

    def tracCommit(self):
        self._tracdb.commit()

    def mantisCursor(self):
        return self._mantis_cursor

    def mantisCommit(self):
        self._mantis_con.commit()
    
    def hasTickets(self):
        c = self.mantisCursor()
        c.execute('''SELECT count(*) FROM mantis_bug_table WHERE 1''')
        return int(c.fetchall()[0]['count(*)']) > 0

    def clean(self, tablename):
        print 'TRUNCATE %s' % tablename
        self.mantisCursor().execute('TRUNCATE %s' % tablename)
        self.mantisCommit()

    def assertNoTickets(self):
        if not self._append and self.hasTickets():
          raise Exception("Will not modify database with existing tickets!")
          return

    # generate a random character string of given length
    def generateCookie(self, length):
        password = ''
        for i in range(int(length)):
            password += random.choice("abcdefghijklmnopqrstuvwxyz0123456789")
        return password

    # generate a random character string of given length
    def generatePassword(self, length):
        password = ''
        for i in range(int(length)):
            password += chr(random.randint(33,126))
        return password

    def newBugId(self, tracId, mantisId):
        self._bug_map[tracId] = mantisId

    def bugId(self, tracId):
        return self._bug_map[tracId]

    def userId(self, username):
        if username == '' or username is None:
            return 0
        if username not in self._user_map:
            sql = """SELECT id, username FROM mantis_user_table WHERE username = %s""" % (username)
            print sql
            self.mantisCursor().execute("""SELECT id, username FROM mantis_user_table WHERE username = %s""" , (username))
            result = self.mantisCursor().fetchall()
            print result
            if result:
                self._user_map[username] = int(result[0]['id'])
            else:
                result = ((1))
                while result:
                    cookie = self.generateCookie(64)
                    print cookie
                    self.mantisCursor().execute("""SELECT cookie_string FROM mantis_user_table WHERE cookie_string = %s""" , (cookie))
                    result = self.mantisCursor().fetchall()

                sql = """INSERT INTO mantis_user_table (username, realname, email, password, cookie_string) VALUES (%s, %s, %s, Md5(%s), %s) """ % (username, NN_NAME, NN_EMAIL, self.generatePassword(16), cookie)
                print sql
                self.mantisCursor().execute("""INSERT INTO mantis_user_table (username, realname, email, password, cookie_string) VALUES (%s, %s, %s, MD5(%s), %s) """ , (username, NN_NAME, NN_EMAIL, str(self.generatePassword(16)), str(cookie)))
                self.mantisCommit()
                self._user_map[username] = int(self.mantisCursor().lastrowid)

        return self._user_map[username]
        
    def categoryId(self, category):
        if category not in self._category_map:
            sql = """SELECT id FROM mantis_category_table WHERE name = %s AND project_id = '%d'""" % (category, int(self.projectId()))
            print sql
            self.mantisCursor().execute("""SELECT id FROM mantis_category_table WHERE name = %s AND project_id = %s""" , (category, self.projectId()))
            result = self.mantisCursor().fetchall()
            if result:
                self._category_map[category] = result[0]['id']
            else:
                sql = """INSERT INTO mantis_category_table 
                  (project_id, name) VALUES (%s, %s) """ % (self.projectId(), category)
                print sql
                self.mantisCursor().execute("""INSERT INTO mantis_category_table 
                  (project_id, name) VALUES (%s, %s) """ , (self.projectId(), category))
                self.mantisCommit()
                self._category_map[category] = self.mantisCursor().lastrowid

        return self._category_map[category]
        
    def convertMantisTime(self,time2):
	time2 = datetime.fromtimestamp(time2)
	return long(str(int(time.mktime(time2.timetuple()))) + '000000')

    def convertTracTime(self,time2):
	time2 = time2 / 1000000
	return time2


def commentConvert(db, change_ticket, change_time, change_author, change_field, change_oldvalue, change_newvalue):
    sql = """INSERT INTO mantis_bugnote_text_table 
          (note) VALUES (%s)""" % change_newvalue
    print sql
    db.mantisCursor().execute("""INSERT INTO mantis_bugnote_text_table 
          (note) VALUES (%s)""" , (change_newvalue.encode('iso-8859-1','replace')))
    note_id = db.mantisCursor().lastrowid

    sql = """INSERT INTO mantis_bugnote_table
          (bug_id, reporter_id, bugnote_text_id, last_modified, date_submitted)
          VALUES (%s, %s, %s, %s, %s)""" % (db.bugId(change_ticket), db.userId(change_author), note_id, db.convertTracTime(change_time), db.convertTracTime(change_time) )
    print sql
    db.mantisCursor().execute("""INSERT INTO mantis_bugnote_table
          (bug_id, reporter_id, bugnote_text_id, last_modified, date_submitted)
          VALUES (%s, %s, %s, %s, %s)""" , (db.bugId(change_ticket), db.userId(change_author), note_id, db.convertTracTime(change_time), db.convertTracTime(change_time) ))
    db.mantisCommit()

    sql = """INSERT INTO mantis_bug_history_table
          (user_id, bug_id, field_name, old_value, new_value, type, date_modified)
          VALUES (%s, %s, %s, %s, %s, %d, %s)""" % (db.userId(change_author), db.bugId(change_ticket), "", note_id, "", EDIT_TYPES_NOTE_ADDED, db.convertTracTime(change_time))
    print sql
    db.mantisCursor().execute("""INSERT INTO mantis_bug_history_table
          (user_id, bug_id, field_name, old_value, new_value, type, date_modified)
          VALUES (%s, %s, %s, %s, %s, %s, %s)""" , (db.userId(change_author), db.bugId(change_ticket), "", note_id, "", EDIT_TYPES_NOTE_ADDED, db.convertTracTime(change_time)))
    db.mantisCommit()


def changeConvert(db, change_ticket, change_time, change_author, field_name, old_value, new_value, type):
    if old_value is None:
        old_value = ""
    if new_value is None:
        new_value = ""

    sql = """INSERT INTO mantis_bug_history_table
          (user_id, bug_id, field_name, old_value, new_value, type, date_modified)
          VALUES (%s, %s, %s, %s, %s, %s, %s)""" % (db.userId(change_author), db.bugId(change_ticket), field_name, old_value, new_value, type, db.convertTracTime(change_time))
    print sql
    db.mantisCursor().execute("""INSERT INTO mantis_bug_history_table
          (user_id, bug_id, field_name, old_value, new_value, type, date_modified)
          VALUES (%s, %s, %s, %s, %s, %s, %s)""" , (db.userId(change_author), db.bugId(change_ticket), field_name, old_value, new_value, type, db.convertTracTime(change_time)))
    db.mantisCommit()
    


def convert(project_name, _db, _host, _user, _password, _env, _force, _append):
    print "Trac database('%s'): connecting..." % (_env)
    print "Mantis MySQL('%s':'%s':'%s':'%s'): connecting..." % (_db, _host, _user, _password)
    db = TracDatabase(project_name, _env, _db, _host, _user, _password, _append)

    # force mode...
    if _force == 1:
        print "cleaning all tickets..."
        db.clean('mantis_bugnote_table')
        db.clean('mantis_bugnote_text_table')
        db.clean('mantis_bug_file_table')
        db.clean('mantis_bug_history_table')
        db.clean('mantis_bug_monitor_table')
        db.clean('mantis_bug_relationship_table')
        db.clean('mantis_bug_revision_table')
        db.clean('mantis_bug_table')
        db.clean('mantis_bug_text_table')
        db.clean('mantis_bug_tag_table')
        db.clean('mantis_tag_table')


    db.assertNoTickets()

    # custom fields?
    # categories?

    print
    print "Importing bugs..." 

    sql = "SELECT * FROM ticket"
    db.tracCursor().execute(sql)

    bugs = db.tracCursor().fetchall()

    for bug_id, bug_type, bug_time, bug_changetime, bug_component, bug_severity, bug_priority, bug_owner, bug_reporter, bug_cc, bug_version, bug_milestone, bug_status, bug_resolution, bug_summary, bug_description, bug_keywords in bugs:

        # currently ignoring: bug_cc

        print "Inserting bug %d: %s..." % (bug_id, bug_summary)
        if len(bug_description) == 0:
            bug_description = "--"

        sql = """INSERT INTO mantis_bug_text_table (description, steps_to_reproduce, additional_information) VALUES (%s, '', '')""" % (bug_description)
        # print sql
        db.mantisCursor().execute("""INSERT INTO mantis_bug_text_table (description, steps_to_reproduce, additional_information) VALUES (%s, '', '')""" , (bug_description.encode('iso-8859-1','replace')))
        db.mantisCommit()
        bug_description_id = db.mantisCursor().lastrowid

        if 'feature' in bug_type:
            severity = SEVERITY_TRAC_MANTIS['feature']
        else:
            severity = SEVERITY_TRAC_MANTIS[bug_severity]

        sql = """INSERT INTO mantis_bug_table
        (project_id, reporter_id, handler_id, 
         priority, severity, status, resolution, 
         version, target_version, 
         bug_text_id, summary,
         category_id, date_submitted, last_updated) 
        VALUES (%d, %d, %d, 
         %d, %d, %d, %d,
         %s, %s,
         %d, %s,
         %d, %d, %d)""" % (db.projectId(), db.userId(bug_reporter), db.userId(bug_owner),     PRIORITY_TRAC_MANTIS[bug_priority], severity, STATUS_TRAC_MANTIS[bug_status], RESOLUTION_TRAC_MANTIS[bug_resolution],     bug_version, bug_milestone,     bug_description_id, bug_summary,    db.categoryId(bug_component), db.convertTracTime(bug_time), db.convertTracTime(bug_changetime))
        # print sql;
        db.mantisCursor().execute("""INSERT INTO mantis_bug_table
        (project_id, reporter_id, handler_id, 
         priority, severity, status, resolution, 
         version, target_version, 
         bug_text_id, summary,
         category_id, date_submitted, last_updated) 
        VALUES (%s, %s, %s,
         %s, %s, %s, %s,
         %s, %s,
         %s, %s,
         %s, %s, %s)""" , (db.projectId(), db.userId(bug_reporter), db.userId(bug_owner),     PRIORITY_TRAC_MANTIS[bug_priority], severity, STATUS_TRAC_MANTIS[bug_status], RESOLUTION_TRAC_MANTIS[bug_resolution],     bug_version, bug_milestone,     bug_description_id, bug_summary,    db.categoryId(bug_component), db.convertTracTime(bug_time), db.convertTracTime(bug_changetime)))
        db.mantisCommit()
        bug_new_id = db.mantisCursor().lastrowid
        db.newBugId(bug_id, bug_new_id)
        
        for keyword in bug_keywords.split(" "):
            if keyword == "":
                continue
            sql = """SELECT id FROM mantis_tag_table WHERE name = '%s'""" % (keyword)
            print sql
            db.mantisCursor().execute("""SELECT id FROM mantis_tag_table WHERE name = %s""" , (keyword))
            foundKeywords = db.mantisCursor().fetchall()
            if len(foundKeywords) > 0:
                keyword_id = foundKeywords[0]['id']
                print "found %s" % keyword_id
            else:
                sql = """INSERT INTO mantis_tag_table (user_id, name, date_created, date_updated)
                      VALUES (%s, %s, %s, %s)""" % (db.userId(bug_reporter), keyword, db.convertTracTime(bug_time), db.convertTracTime(bug_time))
                print sql
                db.mantisCursor().execute("""INSERT INTO mantis_tag_table (user_id, name, date_created, date_updated)
                      VALUES (%s, %s, %s, %s)""" , (db.userId(bug_reporter), keyword, db.convertTracTime(bug_time), db.convertTracTime(bug_time)))
                db.mantisCommit()
                keyword_id = db.mantisCursor().lastrowid
            
            sql = """INSERT INTO mantis_bug_tag_table VALUES (%d, %d, %d, %s)""" % (bug_id, keyword_id, db.userId(bug_reporter), db.convertTracTime(bug_time))
            print sql
            db.mantisCursor().execute("""INSERT INTO mantis_bug_tag_table VALUES (%s, %s, %s, %s)""", (bug_id, keyword_id, db.userId(bug_reporter), db.convertTracTime(bug_time)))
            db.mantisCommit()
            

    print
    print "Importing bug histories..."
    sql = "SELECT * FROM ticket_change"
    db.tracCursor().execute(sql)

    changes = db.tracCursor().fetchall()

    for change_ticket, change_time, change_author, change_field, change_oldvalue, change_newvalue in changes:
        
        # ignored fields: description, cc, keywords, reporter
        if change_field == 'comment':
            commentConvert(db, change_ticket, change_time, change_author, change_field, change_oldvalue, change_newvalue)

        if change_field == 'resolution':
            changeConvert(db, change_ticket, change_time, change_author, "resolution", RESOLUTION_TRAC_MANTIS[change_oldvalue], RESOLUTION_TRAC_MANTIS[change_newvalue], EDIT_TYPES_NONE)

        if change_field == 'status':
            changeConvert(db, change_ticket, change_time, change_author, "status", STATUS_TRAC_MANTIS[change_oldvalue], STATUS_TRAC_MANTIS[change_newvalue], EDIT_TYPES_NONE)
            
        if change_field == 'owner':
            changeConvert(db, change_ticket, change_time, change_author, "handler_id", db.userId(change_oldvalue), db.userId(change_newvalue), EDIT_TYPES_NONE)

        if change_field == 'reporter':
           changeConvert(db, change_ticket, change_time, change_author, "reporter_id", db.userId(change_oldvalue), db.userId(change_newvalue), EDIT_TYPES_NONE)

        if change_field == 'priority':
            changeConvert(db, change_ticket, change_time, change_author, "priority", PRIORITY_TRAC_MANTIS[change_oldvalue], PRIORITY_TRAC_MANTIS[change_newvalue], EDIT_TYPES_NONE)
            
        if change_field == 'milestone':
            changeConvert(db, change_ticket, change_time, change_author, "target_version", change_oldvalue, change_newvalue, EDIT_TYPES_NONE)

        if change_field == 'summary':
            changeConvert(db, change_ticket, change_time, change_author, "summary", change_oldvalue, change_newvalue, EDIT_TYPES_NONE)

        if change_field == 'version':
            changeConvert(db, change_ticket, change_time, change_author, "version", change_oldvalue, change_newvalue, EDIT_TYPES_NONE)

        if change_field == 'fixed_in_version':
            changeConvert(db, change_ticket, change_time, change_author, "fixed_in_version", change_oldvalue, change_newvalue, EDIT_TYPES_NONE)

        if change_field == 'severity':
            changeConvert(db, change_ticket, change_time, change_author, "severity", SEVERITY_TRAC_MANTIS[change_oldvalue], SEVERITY_TRAC_MANTIS[change_newvalue], EDIT_TYPES_NONE)


    # print
    # print "Importing attachments..."

    


def usage():
    print "trac2mantis - Imports a bug database from Trac into Mantis."
    print
    print "Usage: trac2mantis.py [options]"
    print
    print "Available Options:"
    print "  --db <MySQL dbname>              - Mantis database"
    print "  --tracenv /path/to/trac/env/     - Full path to Trac environment"
    print "  -h | --host <MySQL hostname>     - Mantis DNS host name"
    print "  -u | --user <MySQL username>     - Effective Mantis database user"
    print "  -p | --passwd <MySQL password>   - Mantis database user password"
    print "  -c | --clean                     - Remove current Trac tickets before importing"
    print "  -a | --append                    - Append bugs to existing project"
    print "  --help | help                    - This help info"
    print
    print "Note: Attachment conversion does not work at this point."
    print
    print "Additional configuration options can be defined directly in the script."
    print
    sys.exit(0)

def main():
    global MANTIS_DB, MANTIS_HOST, MANTIS_USER, MANTIS_PASSWORD, TRAC_ENV, MANTIS_CLEAN, MANTIS_APPEND, PROJECT
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
                MANTIS_CLEAN = 1
            elif sys.argv[iter] in ['-a', '--append']:
                MANTIS_APPEND = 1
            else:
                print "Error: unknown parameter: " + sys.argv[iter]
                sys.exit(0)
            iter = iter + 1
    else:
        usage()
        
    convert(PROJECT, MANTIS_DB, MANTIS_HOST, MANTIS_USER, MANTIS_PASSWORD, TRAC_ENV, MANTIS_CLEAN, MANTIS_APPEND)

if __name__ == '__main__':
    main()
