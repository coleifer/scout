from functools import wraps
import logging

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
from werkzeug.exceptions import NotFound

from scout.constants import PROTECTED_KEYS
from scout.constants import RANKING_CHOICES
from scout.constants import SEARCH_BM25
from scout.exceptions import error
from scout.models import database
from scout.models import Attachment
from scout.models import BlobData
from scout.models import Document
from scout.models import Index
from scout.models import IndexDocument
from scout.models import Metadata
from scout.search import DocumentSearch
from scout.serializers import AttachmentSerializer
from scout.serializers import DocumentSerializer
from scout.serializers import IndexSerializer
from scout.validator import RequestValidator


attachment_serializer = AttachmentSerializer()
document_serializer = DocumentSerializer()
index_serializer = IndexSerializer()

engine = DocumentSearch()
validator = RequestValidator()

logger = logging.getLogger('scout')


def register_views(app):
    prefix = app.config.get('URL_PREFIX') or ''
    if prefix:
        prefix = '/%s' % prefix.strip('/')

    # Register views and request handlers.
    index_view = IndexView(app)
    index_view.register('index_view', '%s/' % prefix)

    document_view = DocumentView(app)
    document_view.register('document_view', '%s/documents/' % prefix)

    attachment_view = AttachmentView(app)
    attachment_view.register(
        'attachment_view',
        '%s/documents/<document_id>/attachments/' % prefix,
        'path')
    app.add_url_rule(
        '%s/documents/<document_id>/attachments/<path:pk>/download/' % prefix,
        view_func=authentication(app)(attachment_download))


def authentication(app):
    def decorator(fn):
        @wraps(fn)
        def inner(*args, **kwargs):
            api_key = app.config.get('AUTHENTICATION')
            if not api_key:
                return fn(*args, **kwargs)

            # Check headers and request.args for `key=<key>`.
            key = request.headers.get('key') or request.args.get('key')
            if key != api_key:
                logger.info('Authentication failure for key: %s', key)
                return 'Invalid API key', 401
            else:
                return fn(*args, **kwargs)
        return inner
    return decorator


class ScoutView(object):
    def __init__(self, app):
        self.app = app
        self.paginate_by = app.config.get('PAGINATE_BY') or 50

    def register(self, name, url, pk_type=None):
        auth = authentication(self.app)
        base_views = (
            (self.list_view, 'GET', name),
            (self.create, 'POST', name + '_create'))

        for view, method, view_name in base_views:
            self.app.add_url_rule(url, view_name, view_func=auth(view),
                                  methods=[method])

        if pk_type is None:
            detail_url = url + '<pk>/'
        else:
            detail_url = url + '<%s:pk>/' % pk_type
        name += '_detail'

        detail_views = (
            (self.detail, ['GET'], name),
            (self.update, ['POST', 'PUT'], name + '_update'),
            (self.delete, ['DELETE'], name + '_delete'))

        for view, methods, view_name in detail_views:
            self.app.add_url_rule(detail_url, view_name, view_func=auth(view),
                                  methods=methods)

    def paginated_query(self, query, paginate_by=None):
        return PaginatedQuery(
            query,
            paginate_by=paginate_by or self.paginate_by,
            check_bounds=False)

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
        filters = validator.extract_get_params()

        q = request.args.get('q', '').strip()
        if not q and not allow_blank:
            error('Search term is required.')

        query = engine.search(q or '*', index, ranking, ordering, **filters)
        pq = self.paginated_query(query)

        response = {
            'document_count': document_count,
            'documents': document_serializer.serialize_query(
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
            'indexes': [index_serializer.serialize(index)
                        for index in pq.get_object_list()],
            'ordering': ordering,
            'page': pq.get_page(),
            'pages': pq.get_page_count()})

    def create(self):
        data = validator.parse_post(['name'])

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
        data = validator.parse_post(['name'])
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
        return jsonify(document_serializer.serialize(document))

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
        data = validator.parse_post(
            ['content'],
            ['identifier', 'index', 'indexes', 'metadata'])

        indexes = validator.validate_indexes(data)
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
        data = validator.parse_post([], [
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

        if 'metadata' in data:
            del document.metadata
            if data['metadata']:
                document.metadata = data['metadata']

        if len(request.files):
            self.attach_files(document)

        indexes = validator.validate_indexes(data, required=False)
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
        return jsonify(attachment_serializer.serialize(attachment))

    def list_view(self, document_id):
        document = self._get_document(document_id)
        query = (Attachment
                 .select(Attachment, BlobData)
                 .join(
                     BlobData,
                     on=(Attachment.hash == BlobData.hash).alias('_blob'))
                 .where(Attachment.document == document))

        ordering = request.args.getlist('ordering')
        query = engine.apply_rank_and_sort(query, None, ordering, {
            'document': Attachment.document,
            'hash': Attachment.hash,
            'filename': Attachment.filename,
            'mimetype': Attachment.mimetype,
            'timestamp': Attachment.timestamp,
            'id': Attachment.id,
        }, 'filename')

        pq = self.paginated_query(query)
        return jsonify({
            'attachments': [attachment_serializer.serialize(attachment)
                            for attachment in pq.get_object_list()],
            'ordering': ordering,
            'page': pq.get_page(),
            'pages': pq.get_page_count()})

    def create(self, document_id):
        document = self._get_document(document_id)
        validator.parse_post([], [])  # Ensure POST data is clean.

        if len(request.files):
            attachments = self.attach_files(document)
        else:
            error('No file attachments found.')

        return jsonify({'attachments': [
            attachment_serializer.serialize(attachment)
            for attachment in attachments]})

    def update(self, document_id, pk):
        document = self._get_document(document_id)
        attachment = self._get_attachment(document, pk)
        validator.parse_post([], [])  # Ensure POST data is clean.

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

    response = make_response(attachment.blob.data)
    response.headers['Content-Type'] = attachment.mimetype
    response.headers['Content-Length'] = attachment.length
    response.headers['Content-Disposition'] = 'inline; filename=%s' % (
        attachment.filename)

    return response
