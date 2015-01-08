#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Import Mantis bugs into a Mantis database.

Requires:  Mantis 1.2.18 from http://www.mantisbt.org/
           Python 2.4 from http://www.python.org/
           MySQL >= 3.23 from http://www.mysql.org/

Steffen Mecke <stm2@users.sourceforge.net>

Based on mantis2trac
Dmitry Yusupov <dmitry_yus@yahoo.com> - bugzilla2trac.py
Mark Rowe <mrowe@bluewire.net.nz> - original TracDatabase class
Bill Soudan <bill@soudan.net> - Many enhancements 

Example use:
  python mantis2mantis.py --indb oldmantis --outdb newmantis
    --host localhost --user root --password secret --clean 

    
"""
from datetime import datetime, date
import time
import hashlib
import uuid
import random


# MySQL connection parameters for the Mantis database.  These can also 
# be specified on the command line.
MANTIS_IN_DB = 'mantis_oldbugs'
MANTIS_OUT_DB = 'mantis_newbugs'
MANTIS_HOST = 'localhost'
MANTIS_USER = 'mantis_user'
MANTIS_PASSWORD = 'replace with password'

# all bugs are imported into this project
OUT_PROJECT = "Imported Project"

# set to true to convert bug project membership to tags
PROJECT_TO_TAGS = False

# set to true to convert bug project membership to a custom field
PROJECT_TO_CUSTOM = True
# this is the name of the custom field 
PROJECT_CUSTOM_FIELD_NAME = "Project"

# If true, all existing Mantis tickets will be removed prior to import.
MANTIS_CLEAN = False
# If TRAC_CLEAN is true and this is true, tickets will be appended
MANTIS_APPEND = False


###########################################################################
### You probably don't need to change any configuration past this line. ###
###########################################################################

DEBUG = False

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

if not hasattr(sys, 'setdefaultencoding'):
    reload(sys)

sys.setdefaultencoding('utf-8')

class MantisDatabase(object):
    def __init__(self, out_project_name, _in_db, _out_db, _host, _user, _password, _append):
        self._append = _append
        self._in_con = MySQLdb.connect(host=_host, 
                user=_user, passwd=_password, db=_in_db, compress=1, 
                cursorclass=MySQLdb.cursors.DictCursor, use_unicode=1)
        self._in_cursor = self._in_con.cursor()

        self._out_con = MySQLdb.connect(host=_host, 
                user=_user, passwd=_password, db=_out_db, compress=1, 
                cursorclass=MySQLdb.cursors.DictCursor, use_unicode=1)
        self._out_cursor = self._out_con.cursor()

        # create project if it doesn't exist
        sql = "SELECT id FROM mantis_project_table WHERE name = %s" % (out_project_name)
        if DEBUG:
            print sql
        self.outCursor().execute("SELECT id FROM mantis_project_table WHERE name = %s", (out_project_name))
        result = self.outCursor().fetchall()
        if len(result) > 1:
            raise Exception("Ambiguous project name %s" % out_project_name)
        elif len(result) == 0:
            sql = """INSERT INTO mantis_project_table (name) VALUES (%s)""" % (out_project_name)
            if DEBUG:
                print sql
            self.outCursor().execute("""INSERT INTO mantis_project_table (name) VALUES (%s)""" , (out_project_name))
            self.outCommit()
            self._project_id = int(self.outCursor().lastrowid)
        else:
            self._project_id = int(result[0]['id'])

        self._id_map = { 
            'mantis_user_table' : {}, 
            'mantis_category_table' : {}, 
            'mantis_project_tag_table' : {} 
        }


    # setup tables for project mapping
    def initProjectTable(self):
        self.newIdMapping('mantis_project_table', 0, self.projectId())
        sql = "SELECT * FROM mantis_project_table"
        self.inCursor().execute(sql)
        if PROJECT_TO_CUSTOM:
            self.initProjectCustom()

        for project in self.inCursor().fetchall():
            self.newIdMapping('mantis_project_table', project['id'], self.projectId())
            if PROJECT_TO_TAGS:
                self.projectTagId(project['id'])
            if PROJECT_TO_CUSTOM:
                self.newIdMapping('mantis_project_custom_table', project['id'], project['name'])

    # setup tables for projects as custom field
    def initProjectCustom(self):
        sql = """INSERT INTO mantis_custom_field_table 
            (name, type, possible_values, default_value, valid_regexp)
            VALUES (%s, %s, '', '', '')""" % (PROJECT_CUSTOM_FIELD_NAME, 0)
        if DEBUG:
            print sql
        self.outCursor().execute("""INSERT INTO mantis_custom_field_table 
            (name, type, possible_values, default_value, valid_regexp)
            VALUES (%s, %s, '', '', '')""" , (PROJECT_CUSTOM_FIELD_NAME, 0))
        self._project_custom_field_id = self.outCursor().lastrowid

        sql = """INSERT INTO mantis_custom_field_project_table 
            (field_id, project_id, sequence)
            VALUES (%s, %s, %s)""" % (self._project_custom_field_id, self.projectId(), 0)
        if DEBUG:
            print sql
        self.outCursor().execute("""INSERT INTO mantis_custom_field_project_table 
            (field_id, project_id, sequence)
            VALUES (%s, %s, %s)""", (self._project_custom_field_id, self.projectId(), 0))

    # the id of the custom field used for project info
    def projectCustomFieldId(self):
        return self._project_custom_field_id
        
    # setup tags for given projectId
    def projectTagId(self, inProjectId):
        tagMap = self._id_map['mantis_project_tag_table']
        if inProjectId not in tagMap:
            sql = """SELECT id, name FROM mantis_project_table WHERE id = %s""" % inProjectId
            if DEBUG:
                print sql
            self.inCursor().execute("""SELECT id, name FROM mantis_project_table WHERE id = %s""" % (inProjectId))
            project = self.inCursor().fetchall()[0]

            sql = """SELECT id FROM mantis_tag_table WHERE name = %s""" % (project['name'])
            #            if DEBUG:
            if DEBUG:
                print sql
            self.outCursor().execute("""SELECT id FROM mantis_tag_table WHERE name = %s""" % (project['id']))
            result = self.outCursor().fetchall()
            if result:
                if DEBUG:
                    print result
                tagMap[inProjectId] = int(result[0]['id'])
            else:
                sql = """INSERT INTO mantis_tag_table 
                  (user_id, name, description, date_created, date_updated) 
                  VALUES (%s, %s, %s, UNIX_TIMESTAMP(), UNIX_TIMESTAMP())""" % (0, project['name'], "Project was: %s" % project['name'])
                if DEBUG:
                    print sql
                self.outCursor().execute("""INSERT INTO mantis_tag_table 
                  (user_id, name, description, date_created, date_updated) 
                  VALUES (%s, %s, %s, UNIX_TIMESTAMP(), UNIX_TIMESTAMP())""" , (0, project['name'], "Project was: %s" % project['name']))
                self.outCommit()
                tagMap[inProjectId] = int(self.outCursor().lastrowid)

        return tagMap[inProjectId]

    # returns id of output project
    def projectId(self):
        return self._project_id

    # database cursor for input database
    def inCursor(self):
        return self._in_cursor

    # database cursor for output database
    def outCursor(self):
        return self._out_cursor

    # commit to output database
    def outCommit(self):
        self._out_con.commit()
    
    def hasTickets(self):
        c = self.outCursor()
        c.execute('''SELECT count(*) FROM mantis_bug_table WHERE 1''')
        return int(c.fetchall()[0]['count(*)']) > 0

    def assertNoTickets(self):
        if not self._append and self.hasTickets():
          raise Exception("Will not modify database with existing tickets!")
          return

    # wipe a table
    # if whereClause is given, only matching rows will be deleted
    def clean(self, tablename, whereClause="", replacement=()):
        if whereClause == "":
            if DEBUG:
                print 'TRUNCATE %s' % tablename
            self.outCursor().execute('TRUNCATE %s' % tablename)
            self.outCommit()
        else:
            sql = 'DELETE FROM %s %s' % (tablename, whereClause)
            if DEBUG:
                print sql % replacement
            self.outCursor().execute('DELETE FROM %s %s' % (tablename, whereClause), replacement)
            self.outCommit()

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

    # add a key mapping for the given table, key and output key
    def newIdMapping(self, mapName, inkey, outkey):
        if mapName not in self._id_map:
            self._id_map[mapName] = {}
        self._id_map[mapName][inkey] = outkey;

    # map a key of input database to corresponding key in output database
    def idMap(self, mapName, key):
        if mapName == 'mantis_user_table':
            return self.userId(key)

        if key == 0:
            if key in self._id_map[mapName]:
                return self._id_map[mapName][key]
            else:
                return 0

        if mapName in self._id_map and key in self._id_map[mapName]:
            return self._id_map[mapName][key]
        else:
            if DEBUG:
                print mapName, key
                print self._id_map[mapName]
            return 0

    # map bug key of input database to output database
    def bugId(self, inId):
        return self.idMap('mantis_bug_table', inId)

    # map user key of input database to output database
    def userId(self, inUserId):
        userMap = self._id_map['mantis_user_table']
        if inUserId == 0 or inUserId is None:
            return 0
        if inUserId not in userMap:
            sql = """SELECT id, email FROM mantis_user_table WHERE id = %s""" % inUserId
            if DEBUG:
                print sql
            self.inCursor().execute("""SELECT * FROM mantis_user_table WHERE id = %s""" , (inUserId))
            users = self.inCursor().fetchall()
            user = users[0]

            sql = """SELECT id, username FROM mantis_user_table WHERE email = %s AND username=%s""" % (user['email'], user['username'])
            if DEBUG:
                print sql
            self.outCursor().execute("""SELECT id, username FROM mantis_user_table WHERE email = %s AND username = %s""" , (user['email'], user['username']))
            result = self.outCursor().fetchall()
            if result:
                userMap[inUserId] = int(result[0]['id'])
            else:
                hasCookies = ((1))
                while hasCookies:
                    cookie = self.generateCookie(64)
                    self.outCursor().execute("""SELECT cookie_string FROM mantis_user_table WHERE cookie_string = %s""" , (cookie))
                    hasCookies = self.outCursor().fetchall()

                sql = """INSERT INTO mantis_user_table (username, realname, email, password, cookie_string) VALUES (%s, %s, %s, Md5(%s), %s) """ % (user['username'], user['realname'], user['email'], self.generatePassword(16), cookie)
                if DEBUG:
                    print sql
                self.outCursor().execute("""INSERT INTO mantis_user_table (username, realname, email, password, cookie_string) VALUES (%s, %s, %s, Md5(%s), %s) """ , (user['username'], user['realname'], user['email'], self.generatePassword(16), cookie))
                self.outCommit()
                userMap[inUserId] = int(self.outCursor().lastrowid)

        return userMap[inUserId]

    # map category key of input to output database
    def categoryId(self, categoryId):
        categoryMap = self._id_map['mantis_category_table']
        if categoryId not in categoryMap:
            sql = """SELECT id FROM mantis_category_table WHERE id = %s""" % categoryId
            if DEBUG:
                print sql
            self.inCursor().execute("""SELECT id FROM mantis_category_table WHERE id = %s""" , (categoryId))
            category = self.inCursor().fetchall()[0]['id']

            sql = """SELECT id FROM mantis_category_table WHERE name = %s AND project_id = '%d'""" % (category, int(self.projectId()))
            if DEBUG:
                print sql
            self.outCursor().execute("""SELECT id FROM mantis_category_table WHERE name = %s AND project_id = %s""" , (category, self.projectId()))
            result = self.outCursor().fetchall()
            if result:
                categoryMap[categoryId] = int(result[0]['id'])
            else:
                sql = """INSERT INTO mantis_category_table 
                  (project_id, name) VALUES (%s, %s) """ % (self.projectId(), category)
                if DEBUG:
                    print sql
                self.outCursor().execute("""INSERT INTO mantis_category_table 
                  (project_id, name) VALUES (%s, %s) """ , (self.projectId(), category))
                self.outCommit()
                categoryMap[categoryId] = self.outCursor().lastrowid

        return categoryMap[categoryId]

    # insert given row to output database, performing necessary id mappings
    def mapRow(self, tablename, idname, idMaps, row):
        values = ()
        sql = """INSERT INTO %s
              (""" % tablename
        fields = ""
        for column in row:
            if column != idname:
                if len(fields) > 0:
                    fields += ", %s" % column
                else:
                    fields += "%s" % column
                if column in idMaps:
                    values = values + (self.idMap(idMaps[column], row[column]),)
                else:
                    values = values + (row[column], )

        sql += fields
        sql += """)
               VALUES ("""
        template = ""
        for column in row:
            if column != idname:
                if len(template) > 0:
                    template += ", %s"
                else:
                    template += "%s"
        sql += template
        sql += ")"
        if DEBUG:
            print sql % values
        self.outCursor().execute(sql, (values))
        self.outCommit()

        if idname is not None:
            self.newIdMapping(tablename, row[idname],  self.outCursor().lastrowid)

    # copy a table to output database
    # idname: name of id column in input database
    # idMaps: keys are foreign keys to table given as value
    # checkDuplicateClause: checks if row might exist in output table
    # checkFields: fields that replace wildcards in checkDuplicateClause
    def mapTable(self, tablename, idname, idMaps, checkDuplicateClause = "", checkFields = ()):
        sql = "SELECT * FROM %s" % tablename
        if DEBUG:
            print sql
        self.inCursor().execute(sql)

        for row in self.inCursor().fetchall():

            if checkDuplicateClause != "":
                checkValues = ()
                for field in checkFields:
                    if DEBUG:
                        print checkValues, field
                    checkValues = checkValues + (row[field],)
                    if DEBUG:
                        print checkDuplicateClause % checkValues
                self.outCursor().execute(checkDuplicateClause , checkValues)
                existing = self.outCursor().fetchall()

            if checkDuplicateClause == "" or not existing or len(existing) == 0:
                self.mapRow(tablename, idname, idMaps, row)
            elif checkDuplicateClause != "" and len(existing) > 0:
                if DEBUG:
                    print row
                    print existing
                    print "map %s:%s => %s" % (tablename, row[idname], existing[0]['id'])
                self.newIdMapping(tablename, row[idname], existing[0]['id'])

def convert(_project_name, _in_db, _out_db, _host, _user, _password, _force, _append):
    global DEBUG
    print "Mantis MySQL('%s':'%s':'%s':'%s':'%s'): connecting..." % (_in_db, _out_db, _host, _user, _password)
    db = MantisDatabase(_project_name, _in_db, _out_db, _host, _user, _password, _append)


    if _force == 1:
        print "cleaning all tickets..."
        db.clean('mantis_bugnote_table')
        db.clean('mantis_bugnote_text_table')
        db.clean('mantis_bug_file_table')
        db.clean('mantis_bug_history_table')
        db.clean('mantis_bug_monitor_table')
        db.clean('mantis_bug_relationship_table')
        db.clean('mantis_bug_revision_table')
        db.clean('mantis_bug_tag_table')
        db.clean('mantis_bug_text_table')
        db.clean('mantis_tag_table')
        db.clean('mantis_category_table', "WHERE project_id = %s", (db.projectId()))
        db.clean('mantis_project_version_table', "WHERE project_id = %s", (db.projectId()))
        
        sql = """DELETE s FROM mantis_custom_field_string_table as s
            JOIN mantis_bug_table as b ON s.bug_id = b.id
            WHERE b.project_id = %s""" % (db.projectId())
        if DEBUG:
            print sql
        db.outCursor().execute("""DELETE s FROM mantis_custom_field_string_table as s
            JOIN mantis_bug_table as b ON s.bug_id = b.id
            WHERE b.project_id = %s""", (db.projectId()))

        if DEBUG:
            print """DELETE FROM mantis_custom_field_table WHERE id NOT IN
                (SELECT field_id FROM mantis_custom_field_project_table
                WHERE project_id != %s)""" % (db.projectId())
        db.outCursor().execute("""DELETE FROM mantis_custom_field_table WHERE id NOT IN
                (SELECT field_id FROM mantis_custom_field_project_table
                WHERE project_id != %s)""", (db.projectId()))
        if DEBUG:
            print """DELETE FROM mantis_custom_field_project_table 
                WHERE project_id = %s""" % (db.projectId())
        db.outCursor().execute("""DELETE FROM mantis_custom_field_project_table
            WHERE project_id = %s""", (db.projectId()))

        db.clean('mantis_bug_table')

    db.assertNoTickets()

    db.initProjectTable()

    print
    print "Importing bugs..." 

    # omitted mantis_filters_table, mantis_config_table, mantis_plugin_table, mantis_project_hierarchy_table, mantis_project_table, project_user_list_table, mantis_sponsorship_table, mantis_tokens_table, mantis_user_pref_table, mantis_user_print_pref_table
    # TODO mantis_email_table?, mantis_news_table, mantis_project_file_table

    print "Importing bug texts..." 
    db.mapTable('mantis_bug_text_table', 'id', {})
    print "Importing categories..."
    db.mapTable('mantis_category_table', 'id', {
        'project_id': 'mantis_project_table',
        'user_id' : 'mantis_user_table'}, 
                """SELECT id FROM mantis_category_table 
                WHERE project_id = %s AND name = %s""" % (db.projectId(), '%s'), ('name', ))
    db.mapTable('mantis_user_profile_table', 'id', {
        'user_id': 'mantis_user_table'})

    print "Importing bugs..."
    db.mapTable('mantis_bug_table', 'id', {
        'project_id': 'mantis_project_table',
        'reporter_id' : 'mantis_user_table',
        'handler_id' : 'mantis_user_table',
        'reporter_id' : 'mantis_user_table',
        'bug_text_id' : 'mantis_bug_text_table',
        'profile_id' : 'mantis_user_profile_table',
        'category_id' : 'mantis_category_table',}) 

    print "Importing bugnotes..."
    db.mapTable('mantis_bugnote_text_table', 'id', {})
    db.mapTable('mantis_bugnote_table', 'id', { 
        'bug_id' : 'mantis_bug_table', 
        'reporter_id' : 'mantis_user_table', 
        'bugnote_text_id' : 'mantis_bugnote_text_table'})
    db.mapTable('mantis_bug_file_table', 'id', {
        'bug_id' : 'mantis_bug_table',
        'user_id' : 'mantis_user_table' })
    print "Importing bug history..."
    db.mapTable('mantis_bug_history_table', 'id', {
        'user_id' : 'mantis_user_table',
        'bug_id' : 'mantis_bug_table',})
    db.mapTable('mantis_bug_monitor_table', None, {
        'user_id' : 'mantis_user_table',
        'bug_id' : 'mantis_bug_table',})
    print "Importing bug relationships ..."
    db.mapTable('mantis_bug_relationship_table', 'id', {
        'source_bug_id' : 'mantis_bug_table',
        'destination_bug_id' : 'mantis_bug_table',})
    db.mapTable('mantis_bug_revision_table', 'id', {
        'bug_id' : 'mantis_bug_table',
        'bugnote_id' : 'mantis_bugnote_text_table'})

    print "Importing custom fields..."
    db.mapTable('mantis_custom_field_table', 'id', {})
    db.mapTable('mantis_custom_field_string_table', None, {
        'field_id': 'mantis_custom_field_table',
        'bug_id' : 'mantis_bug_table',})

    db.mapTable('mantis_custom_field_project_table', None, {
        'field_id': 'mantis_custom_field_table',
        'project_id': 'mantis_project_table'},
                """SELECT id FROM mantis_custom_field_project_table
                WHERE project_id = %s AND field_id = %s""" % (db.projectId(), '%s'), ('field_id', ))
    db.mapTable('mantis_project_version_table', 'id', {
        'project_id': 'mantis_project_table'},
                """SELECT id FROM mantis_project_version_table
                WHERE project_id = %s AND version = %s""" % (db.projectId(), '%s'), ('version', ))

    print "Importing tags..."
    db.mapTable('mantis_tag_table', 'id', {
        'user_id' : 'mantis_user_table',})
    db.mapTable('mantis_bug_tag_table', None, {
        'bug_id' : 'mantis_bug_table',
        'tag_id' : 'mantis_tag_table',
        'user_id' : 'mantis_user_table',})


    print "Updating duplicates and project..."
    # update duplicate_id in bugs
    sql = """SELECT id, duplicate_id, project_id FROM mantis_bug_table"""
    if DEBUG:
        print sql
    db.inCursor().execute(sql)
    for bug in db.inCursor().fetchall():
        if _project_name and PROJECT_TO_TAGS:
            # map project to tag
            sql = """INSERT INTO mantis_bug_tag_table (bug_id, tag_id, user_id, date_attached)
                  VALUES (%s, %s, 0, UNIX_TIMESTAMP())""" % (db.bugId(bug['id']), db.idMap('mantis_project_tag_table', bug['project_id']))
            if DEBUG:
                print sql
            db.outCursor().execute("""INSERT INTO mantis_bug_tag_table (bug_id, tag_id, user_id, date_attached)
                  VALUES (%s, %s, 0, UNIX_TIMESTAMP())""" , (db.bugId(bug['id']), db.idMap('mantis_project_tag_table', bug['project_id'])))
            db.outCommit()

        if _project_name and PROJECT_TO_CUSTOM:
            # map project to custom field
            sql = """INSERT INTO mantis_custom_field_string_table (field_id, bug_id, value)
                 VALUES (%s, %s, %s)""" % (db.projectCustomFieldId(), db.bugId(bug['id']), db.idMap('mantis_project_custom_table', bug['project_id']))
            if DEBUG:
                print sql
            db.outCursor().execute("""INSERT INTO mantis_custom_field_string_table (field_id, bug_id, value)
                 VALUES (%s, %s, %s)""", (db.projectCustomFieldId(), db.bugId(bug['id']), db.idMap('mantis_project_custom_table', bug['project_id'])))


        if bug['duplicate_id'] is not None and bug['duplicate_id'] > 0:
            sql = """UPDATE mantis_bug_table SET duplicate_id = %s""" % (db.bugId(bug['duplicate_id']))
            if DEBUG:
                print sql
            db.outCursor().execute("""UPDATE mantis_bug_table SET duplicate_id = %s""" , (db.bugId(bug['duplicate_id'])))
            db.outCommit()
                                                       
    
def usage():
    print "trac2mantis - Imports a bug database from Trac into Mantis."
    print
    print "Usage: trac2mantis.py [options]"
    print
    print "Available Options:"
    print "  --indb <MySQL dbname>            - Mantis input database"
    print "  --outdb <MySQL dbname>           - Mantis output database"
    print "  --project <Mantis projectname>   - Mantis output project"
    print "  -h | --host <MySQL hostname>     - Mantis DNS host name"
    print "  -u | --user <MySQL username>     - Effective Mantis database user"
    print "  -p | --passwd <MySQL password>   - Mantis database user password"
    print "  -c | --clean                     - Remove current Trac tickets before importing"
    print "  --help | help                    - This help info"
    print
    print "Additional configuration options can be defined directly in the script."
    print
    print "Note: users are also converted, including access level. You might want to check"
    print "the user list of your project to avoid unintentional escalation of privileges."
    print
    sys.exit(0)

def main():
    global MANTIS_IN_DB, MANTIS_OUT_DB, MANTIS_HOST, MANTIS_USER, MANTIS_PASSWORD, TRAC_ENV, MANTIS_CLEAN, MANTIS_APPEND, OUT_PROJECT
    if len (sys.argv) > 1:
        if sys.argv[1] in ['--help','help'] or len(sys.argv) < 4:
            usage()
        iter = 1
        while iter < len(sys.argv):
            if sys.argv[iter] in ['--indb'] and iter+1 < len(sys.argv):
                MANTIS_IN_DB = sys.argv[iter+1]
                iter = iter + 1
            elif sys.argv[iter] in ['--outdb'] and iter+1 < len(sys.argv):
                MANTIS_OUT_DB = sys.argv[iter+1]
                iter = iter + 1
            elif sys.argv[iter] in ['--project'] and iter+1 < len(sys.argv):
                OUT_PROJECT = sys.argv[iter+1]
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
        
    convert(OUT_PROJECT, MANTIS_IN_DB, MANTIS_OUT_DB, MANTIS_HOST, MANTIS_USER, MANTIS_PASSWORD, MANTIS_CLEAN, MANTIS_APPEND)

if __name__ == '__main__':
    main()

