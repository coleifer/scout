#!/usr/bin/env python

import os
import sys

from peewee import SqliteDatabase

def main(filename):
    db = SqliteDatabase(filename)
    db.execute_sql('ALTER TABLE "main_document" ADD COLUMN identifier TEXT;')
    print('Successfully updated schema.')

def panic(s):
    sys.stderr.write(s + '\n')
    sys.stderr.flush()
    sys.exit(1)

if __name__ == '__main__':
    if len(sys.argv) != 1:
        panic('Missing path to database file.')
    filename = sys.argv[0]
    if not os.path.isfile(filename):
        panic('"%s" not found or is not a file.' % filename)
    main(filename)
