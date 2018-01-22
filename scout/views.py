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
        if api_key is None and request.args.get('key'):
            api_key = request.args['key']
        if api_key != app.config['AUTHENTICATION']:
            logger.info('Authentication failure for key: %s' % api_key)
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
                 .join(IndexDocument, JOIN.LEFT_OUTER)
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
