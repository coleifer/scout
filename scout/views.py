from functools import wraps
import json

from flask import abort
from flask import Flask
from flask import jsonify
from flask import make_response
from flask import request
from flask import Response
from flask import url_for
from flask.views import MethodView
from peewee import *
from playhouse.flask_utils import get_object_or_404
from playhouse.flask_utils import PaginatedQuery

from .constants import PROTECTED_KEYS
from .constants import RANKING_CHOICES
from .constants import SEARCH_BM25
from .exceptions import error
from .models import database
from .models import Attachment
from .models import BlobData
from .models import Document
from .models import Index
from .models import IndexDocument
from .models import Metadata
from .search import DocumentSearch
from .serializers import AttachmentSerializer
from .serializers import DocumentSerializer
from .serializers import IndexSerializer


engine = DocumentSearch()


def register_views(app):
    # Register views and request handlers.
    IndexView.register(app, 'index_view', '/')
    DocumentView.register(app, 'document_view', '/documents/')
    AttachmentView.register(app, 'attachment_view',
                            '/documents/<document_id>/attachments/', 'path')
    app.add_url_rule(
        '/documents/<document_id>/attachments/<path:pk>/download/',
        view_func=authentication(app)(attachment_download))


def authentication(app):
    def decorator(fn):
        api_key = app.config.get('AUTHENTICATION')
        if not api_key:
            return fn

        @wraps(fn)
        def inner(*args, **kwargs):
            # Check headers and request.args for `key=<key>`.
            key = request.headers.get('key') or request.args.get('key')
            if key != api_key:
                logger.info('Authentication failure for key: %s', key)
                return 'Invalid API key', 401
            else:
                return fn(*args, **kwargs)
        return inner
    return decorator


class RequestValidator(object):
    def __init__(self, api_key=None):
        self.api_key = api_key

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

    def extract_get_params():
        return dict(
            (key, request.args.getlist(key))
            for key in request.args
            if key not in PROTECTED_KEYS)


class ScoutView(MethodView):
    def __init__(self, *args, **kwargs):
        self.validator = RequestValidator()
        super(ScoutView, self).__init__(*args, **kwargs)

    @classmethod
    def register(cls, app, name, url, pk_type=None):
        view_func = authentication(app)(cls.as_view(name))
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

        cls.paginate_by = app.config.get('PAGINATE_BY') or 50

    def paginated_query(self, query, paginate_by=None):
        return PaginatedQuery(
            query,
            paginate_by=paginate_by or self.paginate_by,
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
        ranking = request.args.get('ranking') or SEARCH_BM25
        if ranking not in RANKING_CHOICES:
            error('Unrecognized "ranking" value. Valid options are %s' %
                  ', '.join(RANKING_CHOICES))

        ordering = request.args.getlist('ordering')
        filters = self.validator.extract_get_params()

        q = request.args.get('q', '').strip()
        if not q and not allow_blank:
            error('Search term is required.')

        query = engine.search(q or '*', index, ranking, ordering,
                              star_all=True if not q else False, **filters)
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
                 .join(IndexDocument, JOIN.LEFT_OUTER)
                 .group_by(Index))

        ordering = request.args.getlist('ordering')
        query = engine.apply_sorting(query, ordering, {
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
            else:
                logger.info('Created new index "%s"' % index.name)

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
            else:
                logger.info('Updated index "%s"' % index.name)

        return self.detail(index.name)

    def delete(self, pk):
        index = get_object_or_404(Index, Index.name == pk)

        with database.atomic():
            ndocs = (IndexDocument
                     .delete()
                     .where(IndexDocument.index == index)
                     .execute())
            index.delete_instance()

        logger.info('Deleted index "%s" and unlinked %s associated documents.',
                    index.name, ndocs)

        return jsonify({'success': True})


class _FileProcessingView(ScoutView):
    def _get_document(self, pk):
        if isinstance(pk, int) or (pk and pk.isdigit()):
            query = Document.all().where(Document._meta.primary_key == pk)
            try:
                return query.get()
            except Document.DoesNotExist:
                pass
        return get_object_or_404(Document.all(), Document.identifier == pk)

    def attach_files(self, document):
        attachments = []
        for identifier in request.files:
            file_obj = request.files[identifier]
            attachments.append(
                document.attach(file_obj.filename, file_obj.read()))
            logger.info('Attached %s to document id = %s',
                        file_obj.filename, document.get_id())
        return attachments


class DocumentView(_FileProcessingView):
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

        if data.get('identifier'):
            try:
                document = self._get_document(data['identifier'])
            except NotFound:
                pass
            else:
                return self.update(data['identifier'])

        document = Document.create(
            content=data['content'],
            identifier=data.get('identifier'))

        if data.get('metadata'):
            document.metadata = data['metadata']

        logger.info('Created document with id=%s', document.get_id())

        for index in indexes:
            index.add_to_index(document)
            logger.info('Added document %s to index %s',
                        document.get_id(), index.name)

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
            logger.info('Updated document with id = %s', document.get_id())
        else:
            logger.warning('No changes, aborting update of document id = %s',
                           document.get_id())

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
            logger.info('Deleted document with id = %s', document.get_id())

        return jsonify({'success': True})


class AttachmentView(_FileProcessingView):
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
