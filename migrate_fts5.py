import os
import shutil
import sqlite3
import sys


def main(src, dest):
    shutil.copy(src, dest)
    conn = sqlite3.connect(dest)
    conn.execute('pragma foreign_keys=0')
    conn.execute('CREATE TEMP TABLE "_tmp" ("docid", "content", "identifier")')
    conn.execute('INSERT INTO "_tmp" ("docid", "content", "identifier") '
                 'SELECT "docid", "content", "identifier" FROM "main_document"')
    conn.execute('DROP TABLE main_document')
    conn.execute('CREATE VIRTUAL TABLE "main_document" USING fts5 ('
                 '"content", "identifier", prefix=\'2,3\', '
                 'tokenize="porter unicode61")')
    conn.execute('INSERT INTO "main_document" ("rowid", "content", "identifier") '
                 'SELECT "docid", "content", "identifier" FROM "_tmp"')
    conn.execute('DROP TABLE "_tmp"')
    conn.commit()
    conn.close()


if __name__ == '__main__':
    if len(sys.argv) != 3:
        print('Usage: migrate_fts5.py source.db dest.db')
        sys.exit(1)
    main(*sys.argv[1:])
