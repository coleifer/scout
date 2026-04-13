import logging
from functools import wraps
from urllib.parse import urlencode

from flask import abort
from flask import Flask
from flask import jsonify
from flask import make_response
from flask import request
from flask import url_for
from peewee import *
from playhouse.flask_utils import get_object_or_404
from playhouse.flask_utils import PaginatedQuery

from scout.constants import PROTECTED_KEYS
from scout.constants import RANKING_CHOICES
from scout.constants import SEARCH_BM25
from scout.constants import SEARCH_NONE
from scout.exceptions import error
from scout.exceptions import InvalidSearchException
from scout.models import database
from scout.models import Attachment
from scout.models import BlobData
from scout.models import DocLookup
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
    app.add_url_rule(
        '%s/documents/<document_id>/metadata/' % prefix,
        'update_metadata',
        view_func=authentication(app)(update_metadata),
        methods=['POST', 'PUT'])

    attachment_view = AttachmentView(app)
    attachment_view.register(
        'attachment_view',
        '%s/documents/<document_id>/attachments/' % prefix,
        'path')
    app.add_url_rule(
        '%s/documents/<document_id>/attachments/<path:pk>/download/' % prefix,
        view_func=authentication(app)(attachment_download))
    app.add_url_rule(
        '%s/attachments/' % prefix,
        'attachment_list',
        view_func=authentication(app)(attachment_list),
        methods=['GET'])


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
                return jsonify({'error': 'Invalid API key'}), 401
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

    @staticmethod
    def paginated_response(pq, data):
        """Build next/previous URLs from current request, swapping page."""
        page = pq.get_page()
        pages = pq.get_page_count()
        base = request.base_url
        args = request.args.to_dict(flat=False)

        def build_url(page_num):
            params = dict(args)
            params['page'] = [str(page_num)]
            return '%s?%s' % (base, urlencode(params, doseq=True))

        data.update({
            'next_url': build_url(page + 1) if page < pages else None,
            'previous_url': build_url(page - 1) if page > 1 else None,
            'page': page,
            'pages': pages,
        })
        return data

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

    def _search_response(self, index, document_count):
        ranking = request.args.get('ranking') or SEARCH_BM25
        if ranking not in RANKING_CHOICES:
            error('Unrecognized "ranking" value. Valid options are %s' %
                  ', '.join(RANKING_CHOICES))

        ordering = request.args.getlist('ordering')
        filters = validator.extract_get_params()

        q = request.args.get('q', '').strip()
        include_score = q and q != '*' and ranking != SEARCH_NONE

        try:
            query = engine.search(q, index, ranking, ordering, **filters)
        except InvalidSearchException as exc:
            error(str(exc))

        pq = self.paginated_query(query)

        try:
            documents = document_serializer.serialize_query(
                pq.get_object_list(),
                include_score=include_score)
            filtered_count = query.count()
        except OperationalError as exc:
            error('Invalid search query: %s' % str(exc))

        response = self.paginated_response(pq, {
            'document_count': document_count,
            'documents': documents,
            'filtered_count': filtered_count,
            'filters': filters,
            'ordering': ordering,
        })
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
        response.update(self._search_response(index, document_count))
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
        response = self.paginated_response(pq, {
            'indexes': [index_serializer.serialize(index)
                        for index in pq.get_object_list()],
            'ordering': ordering})
        return jsonify(response)

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
    @staticmethod
    def _get_document(pk):
        try:
            return DocLookup.get_document(pk)
        except Document.DoesNotExist:
            abort(404)

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
        indexes = validator.normalize_get_indexes(request.args)
        if indexes:
            document_count = (Document
                              .select()
                              .join(IndexDocument)
                              .where(IndexDocument.index.in_(indexes))
                              .distinct()
                              .count())
        else:
            indexes = None
            document_count = Document.select().count()

        return jsonify(self._search_response(indexes, document_count))

    def create(self):
        data = validator.parse_post(
            ['content'],
            ['identifier', 'index', 'indexes', 'metadata'])

        indexes = validator.validate_indexes(data)
        if indexes is None:
            error('You must specify either an "index" or "indexes".')

        if data.get('identifier'):
            try:
                doc = (Document
                       .all()
                       .join(DocLookup, on=(DocLookup.rowid == Document.rowid))
                       .where(DocLookup.identifier == data['identifier'])
                       .get())
                return self.update(doc.rowid, document=doc)
            except Document.DoesNotExist:
                pass

        identifier = data.get('identifier')
        with database.atomic():
            document = Document.create(
                content=data['content'],
                identifier=identifier or None)

            if identifier:
                DocLookup.set_identifier(document, identifier)

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

    def update(self, pk, document=None):
        if document is None:
            document = self._get_document(pk)
        data = validator.parse_post([], [
            'content',
            'identifier',
            'index',
            'indexes',
            'metadata'])

        save_document = False
        if 'content' in data:
            document.content = data['content'] or ''
            save_document = True

        with database.atomic():
            if 'identifier' in data and data['identifier']:
                DocLookup.set_identifier(document, data['identifier'])
                save_document = True
            elif 'identifier' in data and document.identifier:
                DocLookup.set_identifier(document, None)
                save_document = True

            if save_document:
                document.save()
                logger.info('Updated document with id = %s', document.get_id())

        if 'metadata' in data:
            if data['metadata']:
                document.metadata = data['metadata']  # Clears existing.
            else:
                del document.metadata

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
            attach_q = (Attachment
                        .select(Attachment.hash)
                        .where(Attachment.document == document))
            attachment_hashes = [a.hash for a in attach_q]

            (DocLookup
             .delete()
             .where(DocLookup.rowid == document.rowid)
             .execute())

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

            for blob_hash in attachment_hashes:
                remaining = (Attachment
                             .select()
                             .where(Attachment.hash == blob_hash)
                             .count())
                if remaining == 0:
                    (BlobData.delete()
                     .where(BlobData.hash == blob_hash)
                     .execute())

            logger.info('Deleted document with id = %s', document.get_id())

        return jsonify({'success': True})


def update_metadata(document_id):
    document = _FileProcessingView._get_document(document_id)
    data = validator.parse_post(['metadata'], [])
    if not data['metadata']:
        del document.metadata
    else:
        document.set_metadata(data['metadata'], clear=False)
    return jsonify(document_serializer.serialize(document))


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
                 .select(Attachment, BlobData, Document)
                 .join_from(Attachment, Document)
                 .join_from(
                     Attachment,
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
        response = self.paginated_response(pq, {
            'attachments': [attachment_serializer.serialize(attachment)
                            for attachment in pq.get_object_list()],
            'ordering': ordering})
        return jsonify(response)

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
            attachment, = self.attach_files(document)
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
    document = _FileProcessingView._get_document(document_id)
    attachment = get_object_or_404(
        document.attachments,
        Attachment.filename == pk)

    response = make_response(attachment.blob.data)
    response.headers['Content-Type'] = attachment.mimetype
    response.headers['Content-Length'] = attachment.length
    response.headers['Content-Disposition'] = 'inline; filename=%s' % (
        attachment.filename)

    return response

def attachment_list():
    query = (Attachment
             .select(Attachment, BlobData)
             .join(BlobData,
                   on=(Attachment.hash == BlobData.hash).alias('_blob')))

    indexes = validator.normalize_get_indexes(request.args)
    if indexes:
        query = (query
                 .join_from(Attachment, Document)
                 .join_from(Document, IndexDocument)
                 .where(IndexDocument.index.in_(indexes))
                 .distinct())

    filename = request.args.get('filename')
    if filename:
        query = query.where(Attachment.filename == filename)

    mimetype = request.args.get('mimetype')
    if mimetype:
        query = query.where(Attachment.mimetype == mimetype)

    ordering = request.args.getlist('ordering')
    query = engine.apply_rank_and_sort(query, None, ordering, {
        'filename': Attachment.filename,
        'mimetype': Attachment.mimetype,
        'timestamp': Attachment.timestamp,
        'id': Attachment.id,
    }, 'filename')

    pq = PaginatedQuery(query, paginate_by=50, check_bounds=False)
    response = ScoutView.paginated_response(pq, {
        'attachments': [attachment_serializer.serialize(attachment)
                        for attachment in pq.get_object_list()],
        'ordering': ordering})
    return jsonify(response)
