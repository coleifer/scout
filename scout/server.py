import logging
import optparse
import os
import sys

from flask import Flask
from werkzeug.serving import run_simple

from scout.exceptions import ImproperlyConfigured
from scout.exceptions import InvalidRequestException
from scout.models import database
from scout.models import Attachment
from scout.models import BlobData
from scout.models import DocLookup
from scout.models import Document
from scout.models import Index
from scout.models import IndexDocument
from scout.models import Metadata
from scout.views import register_views


logger = logging.getLogger('scout')


def create_server(config=None, config_file=None):
    app = Flask(__name__)

    # Configure application using a config file.
    if config_file is not None:
        app.config.from_pyfile(config_file)

    # (Re-)Configure application using command-line switches/environment flags.
    if config is not None:
        app.config.update(config)

    # Initialize the SQLite database.
    initialize_database(app.config.get('DATABASE') or 'scout.db',
                        pragmas=app.config.get('SQLITE_PRAGMAS') or None,
                        migrate=app.config.get('_DB_MIGRATE', False))
    register_views(app)

    @app.errorhandler(InvalidRequestException)
    def handle_invalid_request(exc):
        return exc.response()

    @app.before_request
    def connect_database():
        if database.database != ':memory:':
            database.connect()

    @app.teardown_request
    def close_database(exc):
        if database.database != ':memory:' and not database.is_closed():
            database.close()

    return app


def initialize_database(database_file, pragmas=None, migrate=False):
    database.init(database_file, pragmas=pragmas)

    with database.connection_context():
        # Check if old schema.
        if is_fts4(database):
            logger.error('FTS4 schema found, migration required.')
            if not migrate:
                raise ImproperlyConfigured(
                    'Your database uses FTS4, but Scout requires FTS5. '
                    'You can migrate your database using the provided '
                    'migrate_fts5.py script or initialize the server with '
                    '--migrate')
            else:
                logger.warning('Migrating FTS4 to FTS5')
                try:
                    with database.atomic():
                        migrate_schema(database)
                except Exception:
                    logger.exception('Error applying migration')
                    raise

        with database.atomic():
            database.create_tables([
                Attachment,
                BlobData,
                DocLookup,
                Document,
                Index,
                IndexDocument,
                Metadata])

def is_fts4(database):
    # Check if old schema.
    curs = database.execute_sql('select sql from sqlite_master where '
                                'name = ?', ('main_document',))
    res = curs.fetchone()
    if res is not None:
        sql, = res
        return 'USING FTS4' in sql
    return False

def migrate_schema(database):
    conn = database.connection()
    conn.execute('pragma foreign_keys=0')

    logger.info('Creating temp table to hold FTS4 data')
    conn.execute('CREATE TEMP TABLE "_tmp" ("docid", "content", "identifier")')
    conn.execute('INSERT INTO "_tmp" ("docid", "content", "identifier") '
                 'SELECT "docid", "content", "identifier" '
                 'FROM "main_document"')
    conn.execute('DROP TABLE main_document')
    logger.info('Creating new FTS5 table')
    conn.execute('CREATE VIRTUAL TABLE "main_document" USING fts5 ('
                 '"content", "identifier", prefix=\'2,3\', '
                 'tokenize="porter unicode61")')
    logger.info('Populating FTS5 table')
    conn.execute('INSERT INTO "main_document" '
                 '("rowid", "content", "identifier") '
                 'SELECT "docid", "content", "identifier" FROM "_tmp"')
    conn.execute('DROP TABLE "_tmp"')

    logger.info('Creating doc lookup table')
    conn.execute('CREATE TABLE IF NOT EXISTS "main_doclookup" ('
                 '"rowid" INTEGER NOT NULL PRIMARY KEY, '
                 '"identifier" TEXT NOT NULL)')
    conn.execute('CREATE UNIQUE INDEX IF NOT EXISTS '
                 '"main_doclookup_identifier" '
                 'ON "main_doclookup" ("identifier")')
    logger.info('Populating doc lookup table')
    conn.execute('INSERT OR IGNORE INTO "main_doclookup" '
                 '("rowid", "identifier") '
                 'SELECT "rowid", "identifier" FROM "main_document" '
                 'WHERE "identifier" IS NOT NULL AND "identifier" != ?', ('',))
    logger.info('Finished migration successfully.')


def run(app):
    if app.config['DEBUG']:
        app.run(host=app.config['HOST'], port=app.config['PORT'], debug=True)
    else:
        run_simple(
            hostname=app.config['HOST'],
            port=app.config['PORT'],
            application=app,
            threaded=True)


def panic(s, exit_code=1):
    sys.stderr.write('\033[91m%s\033[0m\n' % s)
    sys.stderr.flush()
    sys.exit(exit_code)


def get_option_parser():
    parser = optparse.OptionParser()
    parser.add_option(
        '-H',
        '--host',
        default='127.0.0.1',
        dest='host',
        help='The hostname to listen on. Defaults to 127.0.0.1.')
    parser.add_option(
        '-p',
        '--port',
        default=8000,
        dest='port',
        help='The port to listen on. Defaults to 8000.',
        type='int')
    parser.add_option(
        '-u',
        '--url-prefix',
        dest='url_prefix',
        help='URL path to prefix Scout API.')
    parser.add_option(
        '-d',
        '--debug',
        action='store_true',
        dest='debug',
        help='Run Flask app in debug mode.')
    parser.add_option(
        '-c',
        '--config',
        dest='config',
        help='Configuration module (python file).')
    parser.add_option(
        '--paginate-by',
        default=50,
        dest='paginate_by',
        help='Number of documents displayed per page of results, default=50',
        type='int')
    parser.add_option(
        '-k',
        '--api-key',
        dest='api_key',
        help='Set the API key required to access Scout.')
    parser.add_option(
        '-C',
        '--cache-size',
        default=64,
        dest='cache_size',
        help='SQLite page-cache size (MB). Defaults to 64MB.',
        type='int')
    parser.add_option(
        '-f',
        '--fsync',
        action='store_true',
        dest='fsync',
        help='Synchronize database to disk on every write.')
    parser.add_option(
        '-j',
        '--journal-mode',
        default='wal',
        dest='journal_mode',
        help='SQLite journal mode. Defaults to WAL (recommended).')
    parser.add_option(
        '-l',
        '--logfile',
        dest='logfile',
        help='Log file')
    parser.add_option(
        '-m',
        '--max-request-size',
        default=64 * 1024 * 1024,
        dest='max_request_size',
        help='Maximum size of request body in bytes, default 64MB',
        type='int')
    parser.add_option(
        '--migrate',
        action='store_true',
        dest='migrate',
        help='Migrate FTS4 to FTS5 and update schema in-place.')
    return parser

def parse_options():
    option_parser = get_option_parser()
    options, args = option_parser.parse_args()

    if options.logfile:
        handler = logging.FileHandler(options.logfile)
        logger.addHandler(handler)

    config_file = os.environ.get('SCOUT_CONFIG') or options.config
    config = {'DATABASE': os.environ.get('SCOUT_DATABASE')}

    if len(args) == 0 and not config['DATABASE']:
        panic('Error: missing required path to database file.')
    elif len(args) > 1:
        panic('Error: [%s] only accepts one argument, which is the path '
              'to the database file.' % __file__)
    elif args:
        config['DATABASE'] = args[0]

    pragmas = [
        ('journal_mode', options.journal_mode),
        ('foreign_keys', 0)]
    if options.cache_size:
        pragmas.append(('cache_size', -1024 * options.cache_size))
    if not options.fsync:
        pragmas.append(('synchronous', 0))

    config['SQLITE_PRAGMAS'] = pragmas

    if options.max_request_size:
        config['MAX_CONTENT_LENGTH'] = options.max_request_size

    # Handle command-line options. These values will override any values
    # that may have been specified in the config file.
    if options.api_key:
        config['AUTHENTICATION'] = options.api_key
    if options.debug:
        config['DEBUG'] = True
    config['HOST'] = options.host or '127.0.0.1'
    config['PORT'] = options.port or 8000
    config['URL_PREFIX'] = options.url_prefix or ''
    if options.paginate_by:
        if options.paginate_by < 1 or options.paginate_by > 1000:
            panic('paginate-by must be between 1 and 1000')
        config['PAGINATE_BY'] = options.paginate_by

    if options.migrate:
        config['_DB_MIGRATE'] = True

    return create_server(config, config_file)


def main():
    app = parse_options()
    run(app)


if __name__ == '__main__':
    main()
