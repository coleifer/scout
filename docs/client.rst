.. _client:

Scout Client
============

Scout comes with a simple Python client. This document describes the client API.

.. py:class:: Scout(endpoint[, key=None])

    The :py:class:`Scout` class provides a simple, Pythonic API for interacting with and querying a Scout server.

    :param endpoint: The base URL the Scout server is running on.
    :param key: The authentication key (if used) required to access the Scout server.

    Example of initializing the client:

    .. code-block:: pycon

        >>> from scout_client import Scout
        >>> scout = Scout('https://search.my-site.com/', key='secret!')

    .. py:method:: get_indexes()

        Return the list of indexes available on the server.

        Data returned:

        * document_count
        * documents link (URI for list of indexed documents)
        * id
        * name

        Example:

        .. code-block:: pycon

            >>> scout.get_indexes()
            [{'document_count': 132, 'documents': '/3/', 'id': 3, 'name': 'blog-entries'},
             {'document_count': 18, 'documents': '/3/', 'id': 2, 'name': 'test-index'},
             {'document_count': 830, 'documents': '/3/', 'id': 1, 'name': 'vault'}]

    .. py:method:: create_index(name)

        Create a new index with the given name. If an index with that name already exists, you will receive a 400 response.

        Example:

        .. code-block:: pycon

            >>> scout.create_index('new-index')
            {'document_count': 0,
             'documents': [],
             'id': 5,
             'name': 'new-index',
             'page': 1,
             'pages': 0}

    .. py:method:: rename_index(old_name, new_name)

        Rename an existing index.

        Example:

        .. code-block:: pycon

            >>> scout.rename_index('new-index', 'renamed-index')
            {'document_count': 0,
             'documents': [],
             'id': 5,
             'name': 'renamed-index',
             'page': 1,
             'pages': 0}

    .. py:method:: delete_index(name)

        Delete an existing index.

        Example:

        .. code-block:: pycon

            >>> scout.delete_index('renamed-index')
            {'success': True}

    .. py:method:: get_index([page=None])

        Return the details about the particular index, along with a paginated list of all documents stored in the given index.

        By default the results are paginated 50 documents-per-page. To retrieve a particular page of results, specify ``page=X``.

        Example:

        .. code-block:: pycon

            >>> scout.get_index('vault')

            {'document_count': 58,
             'documents': [
                {'attachments': '/documents/1/attachments/',
                 'content': 'The Rendlesham forest incident is one of the most interesting UFO accounts.',
                 'id': 1,
                 'identifier': None,
                 'indexes': ['vault'],
                 'metadata': {'type': 'ufo'}},
                {'attachments': '/documents/2/attachments/',
                 'content': 'Huey is not very interested in UFOs.',
                 'id': 2,
                 'identifier': None,
                 'indexes': ['vault'],
                 'metadata': {'type': 'huey'}},
                {'attachments': '/documents/3/attachments/',
                 'content': 'Sometimes I wonder if huey is an alien.',
                 'id': 3,
                 'identifier': None,
                 'indexes': ['vault'],
                 'metadata': {'type': 'huey'}},
                ... snip ...
             ],
             'id': 1,
             'name': 'vault',
             'page': 1,
             'pages': 2}

    .. py:method:: create_document(content, indexes[, identifier=None[, attachments=None[, **metadata]]])

        Store a document in the specified index(es).

        :param str content: Text content to expose for search.
        :param indexes: Either the name of an index or a list of index names.
        :param identifier: Optional alternative user-defined identifier for document.
        :param attachments: An optional mapping of filename to file-like object, which should be uploaded and stored as attachments on the given document.
        :param metadata: Arbitrary key/value pairs to store alongside the document content.

        .. code-block:: pycon

            >>> scout.create_document('another test', 'test-index', foo='bar')

            {'attachments': '/documents/7/attachments',
             'content': 'another test',
             'id': 7,
             'identifier': None,
             'indexes': ['test-index'],
             'metadata': {'foo': 'bar'}}

    .. py:method:: update_document([document_id=None[, content=None[, indexes=None[, metadata=None[, identifier=None[, attachments=None]]]]]])

        Update one or more attributes of a document that's stored in the database.

        :param int document_id: The integer document ID (required).
        :param str content: Text content to expose for search (optional).
        :param indexes: Either the name of an index or a list of index names (optional).
        :param metadata: Arbitrary key/value pairs to store alongside the document content (optional).
        :param identifier: Optional alternative user-defined identifier for document.
        :param attachments: An optional mapping of filename to file-like object, which should be uploaded and stored as attachments on the given document. If a filename already exists, it will be over-written with the new attachment.

        .. note:: If you specify metadata when updating a document, existing metadata will be replaced by the new metadata. To simply clear out the metadata for an existing document, pass an empty ``dict``.

        Example:

        .. code-block:: pycon

            >>> scout.update_document(document_id=7, content='updated content')

            {'attachments': '/documents/7/attachments',
             'content': 'updated content',
             'id': 7,
             'identifier': None,
             'indexes': ['test-index'],
             'metadata': {'foo': 'bar'}}

    .. py:method:: delete_document(document_id)

        Remove a document from the database, as well as all indexes.

        :param int document_id: The integer document ID.

        Example:

        .. code-block:: pycon

            >>> scout.delete_document(7)
            {'success': True}

    .. py:method:: get_document(document_id)

        Retrieve content for the given document.

        :param int document_id: The integer document ID.

        Example:

        .. code-block:: pycon

            >>> scout.get_document(7)

            {'attachments': '/documents/7/attachments',
             'content': 'updated content',
             'id': 7,
             'identifier': None,
             'indexes': ['test-index'],
             'metadata': {'foo': 'bar'}}

    .. py:method:: get_documents(**kwargs)

        Retrieve a paginated list of all documents in the database, regardless of index.

        :param kwargs: Arbitrary keyword arguments passed to the API.

    .. py:method:: search(index, query, **kwargs)

        :param str index: The name of the index to search in.
        :param str query: Search query. SQLite's full-text index supports a wide variety of `query operations <http://sqlite.org/fts3.html#section_3>`_.
        :param kwargs: Additional search parameters.

        Search the specified index for documents matching the given query. A paginated list of results will be returned. Additionally, you can filter on metadata for exact matches.

        Valid values for ``kwargs``:

        * ``page=X``
        * ``ranking=(simple|bm25)``, use the specified ranking algorithm for scoring search results. By default Scout uses the *simple* algorithm.
        * Arbitrary key/value pairs for filtering based on metadata values.

        Example search without any filters:

        .. code-block:: pycon

            >>> results = scout.search('vault', 'interesting', ranking='bm25')
            >>> print results['documents']
            [{'content': 'Huey is not very interested in UFOs.',
              'id': 2,
              'indexes': ['vault'],
              'metadata': {'type': 'huey'},
              'score': 0.6194637905555267},
             {'content': 'The Rendlesham forest incident is one of the most interesting UFO accounts.',
              'id': 1,
              'indexes': ['vault'],
              'metadata': {'type': 'ufo'},
              'score': 0.48797383501308006}]

        The same search with a filter on ``type``:

        .. code-block:: pycon

            >>> results = scout.search('vault', 'interesting', type='huey')
            >>> print results['documents']
            [{'content': 'Huey is not very interested in UFOs.',
              'id': 2,
              'indexes': ['vault'],
              'metadata': {'type': 'huey'},
              'score': 0.5}]

        To use a filter with multiple values, you can pass in a list. The resulting filter will use ``OR`` logic to combine the expressions. The resulting query searches for the word "interesting" and then filters the results such that the metadata type contains either the substring 'huey' or 'ufo':

        .. code-block:: pycon

            >>> results = scout.search('vault', 'interesting', type__contains=['huey', 'ufo'])
            >>> print results['documents']
            [{'content': 'Huey is not very interested in UFOs.',
              'id': 2,
              'indexes': ['vault'],
              'metadata': {'type': 'huey'},
              'score': 0.6194637905555267},
             {'content': 'The Rendlesham forest incident is one of the most interesting UFO accounts.',
              'id': 1,
              'indexes': ['vault'],
              'metadata': {'type': 'ufo'},
              'score': 0.48797383501308006}]
