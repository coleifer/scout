#!/usr/bin/env python

"""
RESTful search server powered by SQLite's full-text search extension.
"""
__author__ = 'Charles Leifer'
__kitty__ = 'Huey'
__version__ = '0.4.0'

try:
    from functools import reduce
except ImportError:
    pass
from functools import wraps
import base64
import datetime
import hashlib
import json
import mimetypes
import operator
import optparse
import os
try:
    from peewee import sqlite3
except ImportError:
    try:
        from pysqlite2 import dbapi2 as sqlite3
    except ImportError:
        import sqlite3
import sys
import zlib

from flask import abort, Flask, jsonify, make_response, request, Response, url_for
from flask.views import MethodView
from peewee import *
from peewee import SelectQuery
from peewee import __version__ as peewee_version_raw
from playhouse.fields import CompressedField
from playhouse.flask_utils import get_object_or_404
from playhouse.flask_utils import PaginatedQuery
from playhouse.sqlite_ext import *
from playhouse.sqlite_ext import FTS_VER
from playhouse.sqlite_ext import _VirtualFieldMixin
try:
    from playhouse.sqlite_ext import FTS5Model
except ImportError:
    FTS5Model = None
from werkzeug import secure_filename
from werkzeug.serving import run_simple


peewee_version = [int(part) for part in peewee_version_raw.split('.')]
if peewee_version < [2, 7, 0]:
    raise RuntimeError('Peewee version 2.7.1 or newer is required for this '
                       'version of Scout. Version found: %s.' %
                       peewee_version_raw)


AUTHENTICATION = None
C_EXTENSIONS = True
DATABASE = None
DEBUG = False
HAVE_FTS4 = FTS_VER == 'FTS4'
HAVE_FTS5 = FTS5Model and FTS5Model.fts5_installed() or False
HOST = '127.0.0.1'
PAGE_VAR = 'page'
PAGINATE_BY = 50
PORT = 8000
SEARCH_EXTENSION = HAVE_FTS5 and 'FTS5' or (HAVE_FTS4 and 'FTS4' or 'FTS3')
SECRET_KEY = 'huey is a little angel.'  # Customize this.
STAR_ALL = False
STEM = None
_PROTECTED_KEYS = set(['page', 'q', 'key', 'ranking', 'identifier', 'index',
                       'ordering'])

app = Flask(__name__)
app.config.from_object(__name__)
if os.environ.get('SCOUT_SETTINGS'):
    app.config.from_envvar('SCOUT_SETTINGS')

database = SqliteExtDatabase(None, c_extensions=app.config['C_EXTENSIONS'])
if app.config.get('DATABASE'):
    database.init(app.config['DATABASE'])

RANK_SIMPLE = 'simple'
RANK_BM25 = 'bm25'
RANK_NONE = 'none'

SEARCH_EXTENSION = app.config['SEARCH_EXTENSION']

if SEARCH_EXTENSION == 'FTS5':
    FTSBaseModel = FTS5Model
    # If we have FTS5, we can assume complex option support.
    ModelOptions = {
        'prefix': [2, 3],
        'tokenize': app.config.get('STEM') or 'porter unicode61'}
else:
    FTSBaseModel = FTSModel
    if SEARCH_EXTENSION == 'FTS4':
        ModelOptions = {
            'prefix': [2, 3],
            'tokenize': app.config.get('STEM') or 'porter',
        }
    else:
        ModelOptions = {'tokenize': app.config.get('STEM') or 'porter'}


class Document(FTSBaseModel):
    """
    The :py:class:`Document` class contains content which should be indexed
    for search. Documents can be associated with any number of indexes via
    the `IndexDocument` junction table. Because `Document` is implemented
    as an FTS3 virtual table, it does not support any secondary indexes, and
    all columns have *Text* type, regardless of their declared type. For that
    reason we will utilize the internal SQLite `rowid` column to relate
    documents to indexes.
    """
    content = SearchField()
    identifier = SearchField()

    class Meta:
        database = database
        db_table = 'main_document'
        extension_options = options = ModelOptions

    @classmethod
    def all(cls):
        # Explicitly select the docid/rowid. Since it is a virtual field, it
        # would not normally be selected.
        return Document.select(
            Document._meta.primary_key,
            Document.content,
            Document.identifier)

    @classmethod
    def search(cls, phrase, index=None, ranking='bm25', ordering=None,
               force_star_all=False, **filters):
        phrase = phrase.strip()
        star_all = app.config['STAR_ALL'] or force_star_all
        if not phrase or (phrase == '*' and not star_all):
            raise InvalidSearchException('Must provide a search query.')
        elif phrase == '*' or ranking == RANK_NONE:
            ranking = None

        query = cls.all()
        if phrase != '*':
            query = query.where(Document.match(phrase))

        # Allow filtering by index(es).
        if index is not None:
            query = query.join(IndexDocument)
            if isinstance(index, (list, tuple, SelectQuery)):
                query = query.where(IndexDocument.index << index)
            else:
                query = query.where(IndexDocument.index == index)

        # Allow filtering by metadata.
        metadata_expr = Document.get_metadata_filter_expression(filters)
        if metadata_expr is not None:
            query = query.where(metadata_expr)

        # Allow sorting and ranking.
        return Document.apply_rank_and_sort(query, ranking, ordering or ())

    @staticmethod
    def get_metadata_filter_expression(filters):
        valid_keys = [key for key in filters if key not in _PROTECTED_KEYS]
        if valid_keys:
            return reduce(operator.and_, [
                Document._build_filter_expression(key, values)
                for key, values in filters.items()])

    @staticmethod
    def _build_filter_expression(key, values):
        def in_(lhs, rhs):
            return lhs << ([i.strip() for i in rhs.split(',')])
        operations = {
            'eq': operator.eq,
            'ne': operator.ne,
            'ge': operator.ge,
            'gt': operator.gt,
            'le': operator.le,
            'lt': operator.lt,
            'in': in_,
            'contains': lambda l, r: operator.pow(l, '%%%s%%' % r),
            'startswith': lambda l, r: operator.pow(l, '%s%%' % r),
            'endswith': lambda l, r: operator.pow(l, '%%%s' % r),
            'regex': lambda l, r: l.regexp(r),
        }
        if key.find('__') != -1:
            key, op = key.rsplit('__', 1)
            if op not in operations:
                error(
                    'Unrecognized operation: %s. Supported operations are:'
                    '\n%s' % (op, '\n'.join(sorted(operations.keys()))))
        else:
            op = 'eq'

        op = operations[op]
        if isinstance(values, (list, tuple)):
            expr = reduce(operator.or_, [
                ((Metadata.key == key) & op(Metadata.value, value))
                for value in values])
        else:
            expr = ((Metadata.key == key) & op(Metadata.value, values))

        return fn.EXISTS(Metadata.select().where(
            expr &
            (Metadata.document == Document._meta.primary_key)))

    @classmethod
    def apply_rank_and_sort(cls, query, ranking, ordering):
        sort_options = {
            'content': cls.content,
            'id': cls._meta.primary_key,
            'identifier': cls.identifier,
        }
        if ranking is not None:
            rank = Document.get_rank_expression(ranking)
            sort_options['score'] = rank
            sort_default = 'score'

            # Add score to the selected columns.
            query = query.select(*query._select + [rank.alias('score')])
        else:
            sort_default = 'id'

        return apply_sorting(query, ordering, sort_options, sort_default)

    @staticmethod
    def get_rank_expression(ranking):
        if ranking == RANK_BM25:
            if SEARCH_EXTENSION != 'FTS3':
                # Search only the content field, do not search the identifiers.
                rank_expr = Document.bm25(1.0, 0.0)
            else:
                # BM25 is not available, use the simple rank method.
                rank_expr = Document.rank(1.0, 0.0)
        elif ranking == RANK_SIMPLE:
            # Search only the content field, do not search the identifiers.
            rank_expr = Document.rank(1.0, 0.0)
        else:
            rank_expr = None

        return rank_expr

    def get_metadata(self):
        return dict(Metadata
                    .select(Metadata.key, Metadata.value)
                    .where(Metadata.document == self.get_id())
                    .tuples())

    def set_metadata(self, metadata):
        (Metadata
         .insert_many([
             {'key': key, 'value': value, 'document': self.get_id()}
             for key, value in metadata.items()])
         .execute())

    def delete_metadata(self):
        Metadata.delete().where(Metadata.document == self.get_id()).execute()

    metadata = property(get_metadata, set_metadata, delete_metadata)

    def get_indexes(self):
        return (Index
                .select()
                .join(IndexDocument)
                .where(IndexDocument.document == self.get_id()))

    def attach(self, filename, data):
        filename = secure_filename(filename)
        hash_obj = hashlib.sha256(data)
        data_hash = base64.b64encode(hash_obj.digest())
        try:
            with database.atomic():
                data_obj = BlobData.create(hash=data_hash, data=data)
        except IntegrityError:
            pass

        mimetype = mimetypes.guess_type(filename)[0] or 'text/plain'
        try:
            with database.atomic():
                attachment = Attachment.create(
                    document=self,
                    filename=filename,
                    hash=data_hash,
                    mimetype=mimetype)
        except IntegrityError:
            attachment = (Attachment
                          .get((Attachment.document == self) &
                               (Attachment.filename == filename)))
            attachment.hash = data_hash
            attachment.mimetype = mimetype
            attachment.save(only=[Attachment.hash, Attachment.mimetype])

        return attachment

    def detach(self, filename):
        return (Attachment
                .delete()
                .where((Attachment.document == self) &
                       (Attachment.filename == filename))
                .execute())

    def serialize(self, prefetched=False, include_score=False):
        data = {
            'id': self.get_id(),
            'identifier': self.identifier,
            'content': self.content,
            'attachments': url_for('attachment_view',
                                    document_id=self.get_id()),
        }

        if prefetched:
            data['metadata'] = dict(
                (metadata.key, metadata.value)
                for metadata in self.metadata_set_prefetch)
            data['indexes'] = [
                idx_doc.index.name
                for idx_doc in self.indexdocument_set_prefetch]
        else:
            data['metadata'] = self.metadata
            indexes = (Index
                       .select(Index.name)
                       .join(IndexDocument)
                       .where(IndexDocument.document == self.get_id())
                       .tuples())
            data['indexes'] = [row[0] for row in indexes]

        if include_score:
            data['score'] = self.score

        return data

    @classmethod
    def serialize_query(cls, query, include_score=False):
        # Eagerly load metadata and associated indexes.
        documents = prefetch(
            query,
            Metadata,
            IndexDocument,
            Index)

        return [
            document.serialize(prefetched=True, include_score=include_score)
            for document in documents]


class BaseModel(Model):
    class Meta:
        database = database


class Attachment(BaseModel):
    """
    A mapping of a BLOB to a Document.
    """
    document = ForeignKeyField(Document, related_name='attachments')
    hash = CharField()
    filename = CharField(index=True)
    mimetype = CharField()
    timestamp = DateTimeField(default=datetime.datetime.now, index=True)

    class Meta:
        indexes = (
            (('document', 'filename'), True),
        )

    @property
    def blob(self):
        if not hasattr(self, '_blob'):
            self._blob = BlobData.get(BlobData.hash == self.hash)
        return self._blob

    @property
    def length(self):
        return len(self.blob.data)

    @classmethod
    def search(cls, phrase, index=None, ranking='bm25', ordering=None,
               **filters):
        query = Document.search(phrase, index, ranking, ordering, **filters)

        # Transform query to apply to Attachments instead.
        query = (query
                 .select(
                     Document._meta.primary_key.alias('document_id'),
                     Document.identifier,
                     Attachment.id,
                     Attachment.hash,
                     Attachment.filename,
                     Attachment.mimetype,
                     Attachment.timestamp)
                 .switch(Document)
                 .join(
                     Attachment,
                     on=(Document._meta.primary_key == Attachment.document)))

        return Attachment.apply_rank_and_sort(query, ranking, ordering or ())

    @classmethod
    def apply_rank_and_sort(cls, query, ranking, ordering):
        sort_options = {
            'document': Attachment.document,
            'hash': Attachment.hash,
            'filename': Attachment.filename,
            'mimetype': Attachment.mimetype,
            'timestamp': Attachment.timestamp,
            'id': Attachment.id}

        if ranking is not None:
            rank = Document.get_rank_expression(ranking)
            sort_options['score'] = rank
            sort_default = 'score'

            # Add score to the selected columns.
            query = query.select(*query._select + [rank.alias('score')])
        else:
            sort_default = 'filename'

        return apply_sorting(query, ordering, sort_options, sort_default)

    def serialize(self, include_score=False):
        data_params = {'document_id': self.document_id, 'pk': self.filename}
        if app.config['AUTHENTICATION']:
            data_params['key'] = app.config['AUTHENTICATION']
        data = {
            'filename': self.filename,
            'mimetype': self.mimetype,
            'timestamp': str(self.timestamp),
            'data_length': self.length,
            'document': url_for(
                'document_view_detail',
                pk=self.document_id),
            'data': url_for('attachment_download', **data_params),
        }
        if include_score:
            data['score'] = self.score
        return data


class BlobData(BaseModel):
    """Content-addressable BLOB."""
    hash = CharField(primary_key=True)
    data = CompressedField(compression_level=6, algorithm='zlib')


class Metadata(BaseModel):
    """
    Arbitrary key/value pairs associated with an indexed `Document`. The
    metadata associated with a document can also be used to filter search
    results.
    """
    document = ForeignKeyField(Document, related_name='metadata_set')
    key = CharField()
    value = TextField()

    class Meta:
        db_table = 'main_metadata'
        indexes = (
            (('document', 'key'), True),
            (('key', 'value'), False),
        )


class Index(BaseModel):
    """
    Indexes contain any number of documents and expose a clean API for
    searching and storing content.
    """
    name = CharField(unique=True)

    class Meta:
        db_table = 'main_index'

    def search(self, phrase, ranking=RANK_BM25, ordering=None, **filters):
        return Document.search(phrase, index=self, ranking=ranking,
                               ordering=ordering, **filters)

    def add_to_index(self, document):
        with database.atomic():
            try:
                IndexDocument.create(index=self, document=document)
            except IntegrityError:
                pass

    def index(self, content, document=None, identifier=None, **metadata):
        if document is None:
            document = Document.create(
                content=content,
                identifier=identifier)
        else:
            del document.metadata
            nrows = (Document
                     .update(
                         content=content,
                         identifier=identifier)
                     .where(Document._meta.primary_key == document.get_id())
                     .execute())

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

    def serialize(self):
        if hasattr(self, 'document_count'):
            document_count = self.document_count
        else:
            document_count = self.documents.count()
        return {
            'id': self.id,
            'name': self.name,
            'documents': url_for('index_view_detail', pk=self.name),
            'document_count': document_count,
        }


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

class InvalidRequestException(Exception):
    def __init__(self, error_message, code=None):
        self.error_message = error_message
        self.code = code or 400

    def response(self):
        return jsonify({'error': self.error_message}), self.code


class InvalidSearchException(ValueError):
    pass


def apply_sorting(query, ordering, mapping, default):
    sortables = [part.strip() for part in ordering]
    accum = []
    for identifier in sortables:
        is_desc = identifier.startswith('-')
        identifier = identifier.lstrip('-')
        if identifier in mapping:
            value = mapping[identifier]
            accum.append(value.desc() if is_desc else value)

    if not accum:
        accum = [mapping[default]]

    return query.order_by(*accum)


def error(message, code=None):
    """
    Trigger an Exception from a view that will short-circuit the Response
    cycle and return a 400 "Bad request" with the given error message.
    """
    raise InvalidRequestException(message, code=code)


def validate_ranking():
    ranking = request.args.get('ranking', RANK_BM25) or None
    if ranking not in (RANK_SIMPLE, RANK_BM25, RANK_NONE, ''):
        types = ', '.join('"%s"' % ranking
                          for ranking in (RANK_BM25, RANK_SIMPLE, RANK_NONE))
        error('Unrecognized "ranking" value. Valid options are: %s' % types)
    elif ranking:
        rank_expr = Document.get_rank_expression(ranking)
    else:
        rank_expr = None
    return (ranking, rank_expr)


def extract_metadata_filters():
    return dict(
        (key, request.args.getlist(key)) for key in request.args
        if key not in _PROTECTED_KEYS)


class RequestValidator(object):
    def parse_post(self, required_keys=None, optional_keys=None):
        """
        Clean and validate POSTed JSON data by defining sets of required and
        optional keys.
        """
        if request.headers.get('content-type') == 'application/json':
            data = request.data
        elif 'data' not in request.form:
            error('Missing correct content-type or missing "data" field.')
        else:
            data = request.form['data']

        if data:
            try:
                data = json.loads(data)
            except ValueError:
                error('Unable to parse JSON data from request.')
        else:
            data = {}

        required = set(required_keys or ())
        optional = set(optional_keys or ())
        all_keys = required | optional
        keys_present = set(key for key in data if data[key] not in ('', None))

        missing = required - keys_present
        if missing:
            error('Missing required fields: %s' % ', '.join(sorted(missing)))

        invalid_keys = keys_present - all_keys
        if invalid_keys:
            error('Invalid keys: %s' % ', '.join(sorted(invalid_keys)))

        return data

    def validate_indexes(self, data, required=True):
        if data.get('index'):
            index_names = (data['index'],)
        elif data.get('indexes'):
            index_names = data['indexes']
        elif ('index' in data or 'indexes' in data) and not required:
            return ()
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


def authenticate_request():
    if app.config['AUTHENTICATION']:
        # Check headers and request.args for `key=<key>`.
        api_key = None
        if request.headers.get('key'):
            api_key = request.headers['key']
        elif request.args.get('key'):
            api_key = request.args['key']
        if api_key != app.config['AUTHENTICATION']:
            return False
    return True


def protect_view(fn):
    @wraps(fn)
    def inner(*args, **kwargs):
        if not authenticate_request():
            return 'Invalid API key', 401
        return fn(*args, **kwargs)
    return inner


class ScoutView(MethodView):
    def __init__(self, *args, **kwargs):
        self.validator = RequestValidator()
        super(ScoutView, self).__init__(*args, **kwargs)

    def dispatch_request(self, *args, **kwargs):
        if not authenticate_request():
            return 'Invalid API key', 401
        return super(ScoutView, self).dispatch_request(*args, **kwargs)

    @classmethod
    def register(cls, app, name, url, pk_type=None):
        view_func = cls.as_view(name)
        # Add GET on index view.
        app.add_url_rule(url, name, defaults={'pk': None}, view_func=view_func,
                         methods=['GET'])
        # Add POST on index view.
        app.add_url_rule(url, name, defaults={'pk': None}, view_func=view_func,
                         methods=['POST'])

        # Add detail views.
        if pk_type is None:
            detail_url = url + '<pk>/'
        else:
            detail_url = url + '<%s:pk>/' % pk_type
        name += '_detail'
        app.add_url_rule(detail_url, name, view_func=view_func,
                         methods=['GET', 'PUT', 'POST', 'DELETE'])

    def paginated_query(self, query, paginate_by=None):
        if paginate_by is None:
            paginate_by = app.config['PAGINATE_BY']

        return PaginatedQuery(
            query,
            paginate_by=paginate_by,
            page_var=app.config['PAGE_VAR'],
            check_bounds=False)

    def get(self, **kwargs):
        if kwargs.get('pk') is None:
            kwargs.pop('pk', None)
            return self.list_view(**kwargs)
        return self.detail(**kwargs)

    def post(self, **kwargs):
        if kwargs.get('pk') is None:
            kwargs.pop('pk', None)
            return self.create(**kwargs)
        return self.update(**kwargs)

    def put(self, **kwargs):
        return self.update(**kwargs)

    def detail(self):
        raise NotImplementedError

    def list_view(self):
        raise NotImplementedError

    def create(self):
        raise NotImplementedError

    def update(self):
        raise NotImplementedError

    def delete(self):
        raise NotImplementedError

    def _search_response(self, index, allow_blank, document_count):
        ranking, _ = validate_ranking()
        ordering = request.args.getlist('ordering')
        filters = extract_metadata_filters()

        q = request.args.get('q', '').strip()
        if not q and not allow_blank:
            error('Search term is required.')

        query = Document.search(q or '*', index, ranking, ordering,
                                force_star_all=True if not q else False,
                                **filters)
        pq = self.paginated_query(query)

        response = {
            'document_count': document_count,
            'documents': Document.serialize_query(
                pq.get_object_list(),
                include_score=True if q else False),
            'filtered_count': query.count(),
            'filters': filters,
            'ordering': ordering,
            'page': pq.get_page(),
            'pages': pq.get_page_count(),
        }
        if q:
            response.update(
                ranking=ranking,
                search_term=q)
        return response

#
# Views.
#

class IndexView(ScoutView):
    def detail(self, pk):
        index = get_object_or_404(Index, Index.name == pk)
        document_count = index.documents.count()
        response = {'name': index.name, 'id': index.id}
        response.update(self._search_response(index, True, document_count))
        return jsonify(response)

    def list_view(self):
        query = (Index
                 .select(
                     Index,
                     fn.COUNT(IndexDocument.id).alias('document_count'))
                 .join(IndexDocument, JOIN_LEFT_OUTER)
                 .group_by(Index))

        ordering = request.args.getlist('ordering')
        query = apply_sorting(query, ordering, {
            'name': Index.name,
            'document_count': SQL('document_count'),
            'id': Index.id}, 'name')

        pq = self.paginated_query(query)
        return jsonify({
            'indexes': [index.serialize() for index in pq.get_object_list()],
            'ordering': ordering,
            'page': pq.get_page(),
            'pages': pq.get_page_count()})

    def create(self):
        data = self.validator.parse_post(['name'])

        with database.atomic():
            try:
                index = Index.create(name=data['name'])
            except IntegrityError:
                error('"%s" already exists.' % data['name'])

        return self.detail(index.name)

    def update(self, pk):
        index = get_object_or_404(Index, Index.name == pk)
        data = self.validator.parse_post(['name'])
        index.name = data['name']

        with database.atomic():
            try:
                index.save()
            except IntegrityError:
                error('"%s" is already in use.' % index.name)

        return self.detail(index.name)

    def delete(self, pk):
        index = get_object_or_404(Index, Index.name == pk)

        with database.atomic():
            (IndexDocument
             .delete()
             .where(IndexDocument.index == index)
             .execute())
            index.delete_instance()

        return jsonify({'success': True})


class _FileProcessingView(ScoutView):
    def attach_files(self, document):
        attachments = []
        for identifier in request.files:
            file_obj = request.files[identifier]
            attachments.append(
                document.attach(file_obj.filename, file_obj.read()))
        return attachments


class DocumentView(_FileProcessingView):
    def _get_document(self, pk):
        return get_object_or_404(
            Document.all(),
            Document._meta.primary_key == pk)

    def detail(self, pk):
        document = self._get_document(pk)
        return jsonify(document.serialize())

    def list_view(self):
        # Allow filtering by index.
        idx_list = request.args.getlist('index')
        if idx_list:
            indexes = Index.select(Index.id).where(Index.name << idx_list)
        else:
            indexes = None

        document_count = Document.select().count()
        return jsonify(self._search_response(indexes, True, document_count))

    def create(self):
        data = self.validator.parse_post(
            ['content'],
            ['identifier', 'index', 'indexes', 'metadata'])

        indexes = self.validator.validate_indexes(data)
        if indexes is None:
            error('You must specify either an "index" or "indexes".')

        document = Document.create(
            content=data['content'],
            identifier=data.get('identifier'))

        if data.get('metadata'):
            document.metadata = data['metadata']

        for index in indexes:
            index.add_to_index(document)

        if len(request.files):
            self.attach_files(document)

        return self.detail(document.get_id())

    def update(self, pk):
        document = self._get_document(pk)
        data = self.validator.parse_post([], [
            'content',
            'identifier',
            'index',
            'indexes',
            'metadata'])

        save_document = False
        if data.get('content'):
            document.content = data['content']
            save_document = True
        if data.get('identifier'):
            document.identifier = data['identifier']
            save_document = True

        if save_document:
            document.save()

        if 'metadata' in data:
            del document.metadata
            if data['metadata']:
                document.metadata = data['metadata']

        if len(request.files):
            self.attach_files(document)

        indexes = self.validator.validate_indexes(data, required=False)
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

        return self.detail(document.get_id())

    def delete(self, pk):
        document = self._get_document(pk)

        with database.atomic():
            (IndexDocument
             .delete()
             .where(IndexDocument.document == document)
             .execute())
            (Attachment
             .delete()
             .where(Attachment.document == document)
             .execute())
            Metadata.delete().where(Metadata.document == document).execute()
            document.delete_instance()

        return jsonify({'success': True})


class AttachmentView(_FileProcessingView):
    def _get_document(self, document_id):
        return get_object_or_404(
            Document.all(),
            Document._meta.primary_key == document_id)

    def _get_attachment(self, document, pk):
        return get_object_or_404(
            document.attachments,
            Attachment.filename == pk)

    def detail(self, document_id, pk):
        document = self._get_document(document_id)
        attachment = self._get_attachment(document, pk)
        return jsonify(attachment.serialize())

    def list_view(self, document_id):
        document = self._get_document(document_id)
        query = (Attachment
                 .select(Attachment, BlobData)
                 .join(
                     BlobData,
                     on=(Attachment.hash == BlobData.hash).alias('_blob'))
                 .where(Attachment.document == document))

        ordering = request.args.getlist('ordering')
        query = Attachment.apply_rank_and_sort(query, None, ordering)

        pq = self.paginated_query(query)
        return jsonify({
            'attachments': [a.serialize() for a in pq.get_object_list()],
            'ordering': ordering,
            'page': pq.get_page(),
            'pages': pq.get_page_count()})

    def create(self, document_id):
        document = self._get_document(document_id)
        self.validator.parse_post([], [])  # Ensure POST data is clean.

        if len(request.files):
            attachments = self.attach_files(document)
        else:
            error('No file attachments found.')

        return jsonify({'attachments': [
            attachment.serialize() for attachment in attachments]})

    def update(self, document_id, pk):
        document = self._get_document(document_id)
        attachment = self._get_attachment(document, pk)
        self.validator.parse_post([], [])  # Ensure POST data is clean.

        nfiles = len(request.files)
        if nfiles == 1:
            attachment.delete_instance()
            self.attach_files(document)
        elif nfiles > 1:
            error('Only one attachment permitted when performing update.')
        else:
            error('No file attachment found.')

        return self.detail(document.get_id(), attachment.filename)

    def delete(self, document_id, pk):
        document = self._get_document(document_id)
        attachment = self._get_attachment(document, pk)
        attachment.delete_instance()
        return jsonify({'success': True})


IndexView.register(app, 'index_view', '/')
DocumentView.register(app, 'document_view', '/documents/')
AttachmentView.register(app, 'attachment_view', '/documents/<document_id>/attachments/', 'path')


@app.route('/documents/<document_id>/attachments/<path:pk>/download/')
@protect_view
def attachment_download(document_id, pk):
    document = get_object_or_404(
        Document.all(),
        Document._meta.primary_key == document_id)
    attachment = get_object_or_404(
        document.attachments,
        Attachment.filename == pk)
    _close_database(None)

    response = make_response(attachment.blob.data)
    response.headers['Content-Type'] = attachment.mimetype
    response.headers['Content-Length'] = attachment.length
    response.headers['Content-Disposition'] = 'inline; filename=%s' % (
        attachment.filename)

    return response


@app.route('/documents/attachments/')
@protect_view
def attachment_search():
    """
    Search the index for attachments matching the given query.
    """
    phrase = request.args.get('q', '') or None
    ranking, _ = validate_ranking()
    ordering = request.args.getlist('ordering')
    filters = extract_metadata_filters()

    # Allow filtering by index.
    idx_list = request.args.getlist('index')
    if idx_list:
        indexes = Index.select(Index.id).where(Index.name << idx_list)
    else:
        indexes = None

    query = Attachment.search(
        phrase or '*',
        indexes,
        ranking if phrase else None,
        ordering,
        force_star_all=True if not phrase else False,
        **filters)
    pq = PaginatedQuery(
        query.naive(),
        paginate_by=app.config['PAGINATE_BY'],
        page_var=app.config['PAGE_VAR'],
        check_bounds=False)

    response = []
    for attachment in pq.get_object_list():
        data = {
            'document_id': attachment.document_id,
            'filename': attachment.filename,
            'hash': attachment.hash,
            'id': attachment.id,
            'identifier': attachment.identifier,
            'mimetype': attachment.mimetype,
            'timestamp': attachment.timestamp.strftime('%Y-%m-%d %H:%M:%S'),
        }
        if phrase:
            data['score'] = attachment.score

        url_params = {
            'document_id': data['document_id'],
            'pk': data['filename']}
        if app.config['AUTHENTICATION']:
            url_params['key'] = app.config['AUTHENTICATION']
        data['data'] = url_for('attachment_download', **url_params)
        response.append(data)

    return jsonify({
        'attachment_count': Attachment.select().count(),
        'attachments': response,
        'filters': filters,
        'ordering': ordering,
        'page': pq.get_page(),
        'pages': pq.get_page_count(),
        'ranking': ranking,
        'search_term': phrase,
    })


@app.errorhandler(InvalidRequestException)
def _handle_invalid_request(exc):
    return exc.response()

@app.before_request
def _connect_database():
    if database.database != ':memory:':
        database.connect()

@app.teardown_request
def _close_database(exc):
    if database.database != ':memory:' and not database.is_closed():
        database.close()

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
        database.create_tables([
            Attachment,
            BlobData,
            Document,
            Index,
            IndexDocument,
            Metadata], safe=True)


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
        help='Specify stemming algorithm for content.')
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
    parser.add_option(
        '-v',
        '--search-version',
        choices=('4', '5'),
        dest='search_version',
        help='Select SQLite search extension version (FTS[4] or FTS[5])',
        type='choice')
    parser.add_option(
        '-a',
        '--star-all',
        action='store_true',
        dest='star_all',
        help='Search query "*" returns all records')
    return parser

def parse_options():
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

    if options.star_all:
        app.config['STAR_ALL'] = True

    if options.search_version:
        app.config['SEARCH_EXTENSION'] = 'FTS%s' % options.search_version


if __name__ == '__main__':
    parse_options()
    main()
