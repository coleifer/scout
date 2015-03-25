"""
RESTful search server powered by SQLite's full-text search extension.
"""
__author__ = 'Charles Leifer'
__kitty__ = 'Huey'
__version__ = '0.1.0'

try:
    from functools import reduce
except ImportError:
    pass
from functools import wraps
import json
import operator
import optparse
import os
import sys

from flask import abort, Flask, jsonify, request, Response
from peewee import *
from playhouse.flask_utils import get_object_or_404
from playhouse.flask_utils import PaginatedQuery
from playhouse.sqlite_ext import *
from playhouse.sqlite_ext import _VirtualFieldMixin
from werkzeug.serving import run_simple


AUTHENTICATION = None
DATABASE = None
DEBUG = False
HOST = '127.0.0.1'
PAGE_VAR = 'page'
PAGINATE_BY = 50
PORT = 8000
SECRET_KEY = 'huey is a little angel.'  # Customize this.
STEM = 'porter'

app = Flask(__name__)
app.config.from_object(__name__)

database = SqliteExtDatabase(None)

#
# Database models.
#

class Document(FTSModel):
    rowid = RowIDField()
    content = TextField()

    class Meta:
        database = database
        db_table = 'main_document'

    @classmethod
    def all(cls):
        return Document.select(Document.rowid, Document.content)

    def get_metadata(self):
        return dict(Metadata
                    .select(Metadata.key, Metadata.value)
                    .where(Metadata.document == self.rowid)
                    .tuples())

    def set_metadata(self, metadata):
        (Metadata
         .insert_many([
             {'key': key, 'value': value, 'document': self.rowid}
             for key, value in metadata.items()])
         .execute())

    def delete_metadata(self):
        Metadata.delete().where(Metadata.document == self.rowid).execute()

    metadata = property(get_metadata, set_metadata, delete_metadata)

    def get_indexes(self):
        return (Index
                .select()
                .join(IndexDocument)
                .where(IndexDocument.document == self))


class BaseModel(Model):
    class Meta:
        database = database


class Metadata(BaseModel):
    document = ForeignKeyField(Document, related_name='metadata_set')
    key = CharField()
    value = CharField()

    class Meta:
        db_table = 'main_metadata'
        indexes = (
            (('document', 'key'), True),
        )


class Index(BaseModel):
    RANK_SIMPLE = 'simple'
    RANK_BM25 = 'bm25'
    RANK_NONE = None

    name = CharField(unique=True)

    class Meta:
        db_table = 'main_index'

    def search(self, search, ranking=RANK_SIMPLE, **filters):
        if ranking == Index.RANK_SIMPLE:
            rank_expr = Document.rank()
        elif ranking == Index.RANK_BM25:
            rank_expr = Document.bm25(Document.content)

        selection = [Document.rowid, Document.content]
        if ranking:
            selection.append(rank_expr.alias('score'))

        query = (Document
                 .select(*selection)
                 .join(IndexDocument)
                 .where(
                     (IndexDocument.index == self) &
                     (Document.match(search))))

        if filters:
            filter_expr = reduce(operator.and_, [
                fn.EXISTS(Metadata.select().where(
                    (Metadata.key == key) &
                    (Metadata.value == value) &
                    (Metadata.document == Document.rowid)))
                for key, value in filters.items()
            ])
            query = query.where(filter_expr)

        if ranking:
            query = query.order_by(rank_expr.desc())

        return query

    def add_to_index(self, document):
        with database.atomic():
            try:
                IndexDocument.create(index=self, document=document)
            except IntegrityError:
                pass

    def index(self, content, document=None, **metadata):
        if document is None:
            document = Document()
        else:
            del document.metadata
        document.content = content
        document.save()
        self.add_to_index(document)

        if metadata:
            document.metadata = metadata
        return document

    @property
    def documents(self):
        return (Document
                .all()
                .join(IndexDocument)
                .where(IndexDocument.index == self))


class IndexDocument(BaseModel):
    index = ForeignKeyField(Index)
    document = ForeignKeyField(Document)

    class Meta:
        db_table = 'main_index_document'
        indexes = (
            (('index', 'document'), True),
        )

#
# View helpers.
#

def parse_post(required_keys=None, optional_keys=None):
    try:
        data = json.loads(request.data)
    except ValueError:
        error('Unable to parse JSON data from request.')

    required = set(required_keys or [])
    optional = set(optional_keys or [])
    all_keys = required | optional
    keys_present = set(key for key in data if data[key] not in ('', None))

    missing = required - keys_present
    if missing:
        error('Missing required fields: %s' % ', '.join(sorted(missing)))

    invalid_keys = keys_present - all_keys
    if invalid_keys:
        error('Invalid keys: %s' % ', '.join(sorted(invalid_keys)))

    return data

class InvalidRequestException(Exception):
    def __init__(self, error_message):
        self.error_message = error_message

    def response(self):
        return jsonify({'error': self.error_message}), 400

def error(message):
    raise InvalidRequestException(message)

def validate_indexes(data, required=True):
    if data.get('index'):
        index_names = [data['index']]
    elif data.get('indexes'):
        index_names = data['indexes']
    elif ('index' in data or 'indexes' in data) and not required:
        return []
    else:
        return None

    indexes = list(Index.select().where(Index.name << index_names))

    # Validate that all the index names exist.
    observed_names = set(index.name for index in indexes)
    invalid_names = []
    for index_name in index_names:
        if index_name not in observed_names:
            invalid_names.append(index_name)

    if invalid_names:
        error('The following indexes were not found: %s.' %
              ', '.join(invalid_names))

    return indexes

def _serialize_documents(document_query, include_score=False):
    # Eagerly load metadata and associated indexes.
    documents = prefetch(
        document_query,
        Metadata,
        IndexDocument,
        Index)
    document_list = []
    for document in documents:
        data = {'id': document.rowid, 'content': document.content}
        data['metadata'] = dict(
            (metadata.key, metadata.value)
            for metadata in document.metadata_set_prefetch)
        data['indexes'] = [
            idx_doc.index.name
            for idx_doc in document.indexdocument_set_prefetch]
        if include_score:
            data['score'] = document.score

        document_list.append(data)

    return document_list

def protect_view(fn):
    @wraps(fn)
    def inner(*args, **kwargs):
        if app.config['AUTHENTICATION']:
            # Check headers and request.args for `key=<key>`.
            api_key = None
            if request.headers.get('key'):
                api_key = request.headers['key']
            elif request.args.get('key'):
                api_key = request.args['key']
            if api_key != app.config['AUTHENTICATION']:
                return Response('Invalid API key'), 401
        return fn(*args, **kwargs)
    return inner

#
# Views.
#

@app.route('/', methods=['GET', 'POST'])
@protect_view
def index_list():
    """
    Main index for the SQLite search index. This view returns a JSON object
    containing a list of indexes (id and name) along with the number of
    documents stored in each index.

    This view can also be used to create new indexes by POSTing a `name`.
    """
    if request.method == 'POST':
        data = parse_post(['name'])

        with database.atomic():
            try:
                index = Index.create(name=data['name'])
            except IntegrityError:
                error('"%s" already exists.' % data['name'])

        return index_detail(index.name)

    query = (Index
             .select(Index, fn.COUNT(IndexDocument.id).alias('count'))
             .join(IndexDocument, JOIN_LEFT_OUTER)
             .group_by(Index)
             .order_by(Index.name))

    return jsonify({'indexes': [
        {'id': index.id, 'name': index.name, 'documents': index.count}
        for index in query
    ]})

@app.route('/<index_name>/', methods=['GET', 'POST', 'DELETE'])
@protect_view
def index_detail(index_name):
    """
    Detail view for an index. This view simply returns a JSON object with
    the index's id, name, and number of documents.

    Existing indexes can be renamed using this view by POSTing a `name`.
    """
    index = get_object_or_404(Index, Index.name == index_name)
    if request.method == 'POST':
        data = parse_post(['name'])
        index.name = data['name']
        with database.atomic():
            try:
                index.save()
            except IntegrityError:
                error('"%s" is already in use.' % index.name)
    elif request.method == 'DELETE':
        with database.atomic():
            (IndexDocument
             .delete()
             .where(IndexDocument.index == index)
             .execute())
            index.delete_instance()

        return jsonify({'success': True})

    pq = PaginatedQuery(
        index.documents,
        paginate_by=app.config['PAGINATE_BY'],
        page_var=app.config['PAGE_VAR'],
        check_bounds=False)

    return jsonify({
        'id': index.id,
        'name': index.name,
        'documents': _serialize_documents(pq.get_object_list()),
        'page': pq.get_page(),
        'pages': pq.get_page_count()})

@app.route('/documents/', methods=['GET', 'POST'])
@protect_view
def document_list():
    """
    Returns a paginated list of documents.

    Documents can be indexed by POSTing content.
    """
    if request.method == 'POST':
        data = parse_post(['content'], ['index', 'indexes', 'metadata'])

        indexes = validate_indexes(data)
        if indexes is None:
            error('You must specify either an "index" or "indexes".')

        document = Document.create(content=data['content'])

        if data.get('metadata'):
            document.metadata = data['metadata']

        for index in indexes:
            index.add_to_index(document)

        return jsonify({
            'id': document.rowid,
            'content': document.content,
            'indexes': [index.name for index in indexes],
            'metadata': document.metadata})

    query = Document.all()

    # Allow filtering by index.
    if request.args.get('index'):
        query = (query
                 .join(IndexDocument, JOIN_LEFT_OUTER)
                 .join(Index)
                 .where(Index.name == request.args['index']))

    pq = PaginatedQuery(
        query,
        paginate_by=app.config['PAGINATE_BY'],
        page_var=app.config['PAGE_VAR'],
        check_bounds=False)

    return jsonify({
        'documents': _serialize_documents(pq.get_object_list()),
        'page': pq.get_page(),
        'pages': pq.get_page_count()})

@app.route('/documents/<int:document_id>/', methods=['GET', 'POST', 'DELETE'])
@protect_view
def document_detail(document_id):
    """
    Return the details for an individual document.
    """
    document = get_object_or_404(
        Document.all(),
        Document.rowid == document_id)

    if request.method == 'DELETE':
        with database.atomic():
            (IndexDocument
             .delete()
             .where(IndexDocument.document == document)
             .execute())
            document.delete_instance()
        return jsonify({'success': True})

    elif request.method == 'POST':
        data = parse_post([], ['content', 'index', 'indexes', 'metadata'])
        if data.get('content'):
            document.content = data['content']
            document.save()

        if 'metadata' in data:
            del document.metadata
            if data['metadata']:
                document.metadata = data['metadata']

        indexes = validate_indexes(data, required=False)
        if indexes is not None:
            with database.atomic():
                (IndexDocument
                 .delete()
                 .where(IndexDocument.document == document)
                 .execute())

                if indexes:
                    IndexDocument.insert_many([
                        {'index': index, 'document': document}
                        for index in indexes]).execute()
        else:
            indexes = document.get_indexes()

        index_names = [index.name for index in indexes]

    else:
        # GET requests.
        indexes = (Index
                   .select(Index.name)
                   .join(IndexDocument)
                   .where(IndexDocument.document == document))
        index_names = [index.name for index in indexes]

    return jsonify({
        'id': document.rowid,
        'content': document.content,
        'indexes': index_names,
        'metadata': document.metadata,
    })

@app.route('/<index_name>/search/', methods=['GET'])
@protect_view
def search(index_name):
    if not request.args.get('q'):
        error('Missing required search parameter "q".')

    search_query = request.args['q']
    ranking = request.args.get('ranking', Index.RANK_SIMPLE)
    if ranking and ranking not in (Index.RANK_SIMPLE, Index.RANK_BM25):
        error('Unrecognized "ranking" type.')

    filters = dict(
        (key, value) for key, value in request.args.items()
        if key not in ('page', 'q'))

    index = get_object_or_404(Index, Index.name == index_name)
    query = index.search(search_query, ranking, **filters)
    pq = PaginatedQuery(
        query,
        paginate_by=app.config['PAGINATE_BY'],
        page_var=app.config['PAGE_VAR'],
        check_bounds=False)

    return jsonify({
        'documents': _serialize_documents(
            pq.get_object_list(),
            include_score=ranking is not None),
        'page': pq.get_page(),
        'pages': pq.get_page_count()})


@app.errorhandler(InvalidRequestException)
def _handle_invalid_request(exc):
    return exc.response()

#
# Initialization, main().
#

def main():
    initialize_database(app.config['DATABASE'])
    if app.config['DEBUG']:
        app.run(host=app.config['HOST'], port=app.config['PORT'], debug=True)
    else:
        run_simple(
            hostname=app.config['HOST'],
            port=app.config['PORT'],
            application=app,
            threaded=True)

def initialize_database(database_file):
    database.init(database_file)

    with database.execution_context():
        Document.create_table(tokenize=app.config['STEM'], fail_silently=True)
        database.create_tables([Metadata, Index, IndexDocument], safe=True)

def panic(s, exit_code=1):
    sys.stderr.write('\033[91m%s\033[0m\n' % s)
    sys.stderr.flush()
    sys.exit(exit_code)

def get_option_parser():
    parser = optparse.OptionParser()
    parser.add_option(
        '-H',
        '--host',
        dest='host',
        help='The hostname to listen on. Defaults to 127.0.0.1.')
    parser.add_option(
        '-p',
        '--port',
        dest='port',
        help='The port to listen on. Defaults to 8000.',
        type='int')
    parser.add_option(
        '-s',
        '--stem',
        dest='stem',
        help='Specify stemming algorithm for content (default="porter").')
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
        dest='paginate_by',
        help='Number of documents displayed per page of results, default=50',
        type='int')
    parser.add_option(
        '-k',
        '--api-key',
        dest='api_key',
        help='Set the API key required to access Scout.')
    return parser


if __name__ == '__main__':
    option_parser = get_option_parser()
    options, args = option_parser.parse_args()

    if options.config:
        app.config.from_pyfile(options.config)

    if os.environ.get('SCOUT_CONFIG'):
        app.config.from_pyfile(os.environ['SCOUT_CONFIG'])

    if os.environ.get('SCOUT_DATABASE'):
        app.config['DATABASE'] = os.environ['SCOUT_DATABASE']

    if len(args) == 0 and not app.config.get('DATABASE'):
        panic('Error: missing required path to database file.')
    elif len(args) > 1:
        panic('Error: [%s] only accepts one argument, which is the path '
              'to the database file.' % __file__)
    elif args:
        app.config['DATABASE'] = args[0]

    # Handle command-line options. These values will override any values
    # that may have been specified in the config file.
    if options.api_key:
        app.config['AUTHENTICATION'] = options.api_key

    if options.debug:
        app.config['DEBUG'] = True

    if options.host:
        app.config['HOST'] = options.host

    if options.paginate_by:
        if options.paginate_by < 1 or options.paginate_by > 1000:
            panic('paginate-by must be between 1 and 1000')
        app.config['PAGINATE_BY'] = options.paginate_by

    if options.port:
        app.config['PORT'] = options.port

    if options.stem:
        if options.stem not in ('simple', 'porter'):
            panic('Unrecognized stemmer. Must be "porter" or "simple".')
        app.config['STEM'] = options.stem

    main()
