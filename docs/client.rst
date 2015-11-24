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

        Return the list of indexes available on the server. For each index, the name, id and number of documents is resturned.

        Example:

        .. code-block:: pycon

            >>> scout.get_indexes()
            [{u'documents': 132, u'id': 3, u'name': u'blog-entries'},
             {u'documents': 18, u'id': 2, u'name': u'test-index'},
             {u'documents': 830, u'id': 1, u'name': u'vault'}]

    .. py:method:: create_index(name)

        Create a new index with the given name.

        Example:

        .. code-block:: pycon

            >>> scout.create_index('new-index')
            {u'documents': [],
             u'id': 5,
             u'name': u'new-index',
             u'page': 1,
             u'pages': 0}

    .. py:method:: rename_index(old_name, new_name)

        Rename an existing index.

        Example:

        .. code-block:: pycon

            >>> scout.rename_index('new-index', 'renamed-index')
            {u'documents': [],
             u'id': 5,
             u'name': u'renamed-index',
             u'page': 1,
             u'pages': 0}

    .. py:method:: delete_index(name)

        Delete an existing index.

        Example:

        .. code-block:: pycon

            >>> scout.delete_index('renamed-index')
            {u'success': True}

    .. py:method:: get_documents(**kwargs)

        Return a paginated list of all documents stored in the database. Note in the documents below that they come from multiple different indexes. Additionally, the document `id`, `content` and `metadata` is serialized.

        If you wish to only retrieve documents from a particular index, you can pass the name of the index by specifying ``index='name-of-index'``.

        By default the results are paginated 50 documents-per-page. To retrieve a particular page of results, specify ``page=X``.

        Example:

        .. code-block:: pycon

            >>> scout.get_documents()

            {u'documents': [
                {u'content': u'The Rendlesham forest incident is one of the most interesting UFO accounts.',
                 u'id': 1,
                 u'identifier': None,
                 u'indexes': [u'vault'],
                 u'metadata': {u'type': u'ufo'}},
                {u'content': u'Huey is not very interested in UFOs.',
                 u'id': 2,
                 u'identifier': None,
                 u'indexes': [u'vault'],
                 u'metadata': {u'type': u'huey'}},
                {u'content': u'Sometimes I wonder if huey is an alien.',
                 u'id': 3,
                 u'identifier': None,
                 u'indexes': [u'vault'],
                 u'metadata': {u'type': u'huey'}},
                {u'content': u"The Chicago O'Hare UFO incident is also intriguing.",
                 u'id': 4,
                 u'identifier': None,
                 u'indexes': [u'vault'],
                 u'metadata': {u'type': u'ufo'}},
                {u'content': u'Testing the test index',
                 u'id': 5,
                 u'identifier': None,
                 u'indexes': [u'test-index'],
                 u'metadata': {}}
             ],
             u'page': 1,
             u'pages': 1}

    .. py:method:: store_document(content, indexes[, identifier=None[, **metadata]])

        Store a document in the specified index(es).

        :param str content: Text content to expose for search.
        :param indexes: Either the name of an index or a list of index names.
        :param identifier: Optional alternative user-defined identifier for document.
        :param metadata: Arbitrary key/value pairs to store alongside the document content.

        .. code-block:: pycon

            >>> scout.store_document('another test', 'test-index', foo='bar')

            {u'content': u'another test',
             u'id': 7,
             u'indexes': [u'test-index'],
             u'metadata': {u'foo': u'bar'}}

    .. py:method:: update_document([document_id=None[, content=None[, indexes=None[, metadata=None[, identifier=None]]]]])

        Update one or more attributes of a document that's stored in the database.

        :param int document_id: The integer document ID (required).
        :param str content: Text content to expose for search (optional).
        :param indexes: Either the name of an index or a list of index names (optional).
        :param metadata: Arbitrary key/value pairs to store alongside the document content (optional).
        :param identifier: Optional alternative user-defined identifier for document.

        .. note:: If you specify metadata when updating a document, existing metadata will be replaced by the new metadata. To simply clear out the metadata for an existing document, pass an empty ``dict``.

        .. note:: Either `document_id` or `identifier` must be provided.

        Example:

        .. code-block:: pycon

            >>> scout.update_document(document_id=7, content='updated content')

            {u'content': u'updated content',
             u'id': 7,
             u'indexes': [u'test-index'],
             u'metadata': {u'foo': u'bar'}}

    .. py:method:: delete_document([document_id=None[, identifier=None]])

        Remove a document from the database, as well as all indexes.

        :param int document_id: The integer document ID.
        :param identifier: Optional alternative user-defined identifier for document.

        .. note:: Either `document_id` or `identifier` must be provided.

        Example:

        .. code-block:: pycon

            >>> scout.delete_document(7)
            {u'success': True}

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
            [{u'content': u'Huey is not very interested in UFOs.',
              u'id': 2,
              u'indexes': [u'vault'],
              u'metadata': {u'type': u'huey'},
              u'score': 0.6194637905555267},
             {u'content': u'The Rendlesham forest incident is one of the most interesting UFO accounts.',
              u'id': 1,
              u'indexes': [u'vault'],
              u'metadata': {u'type': u'ufo'},
              u'score': 0.48797383501308006}]

        The same search with a filter on ``type``:

        .. code-block:: pycon

            >>> results = scout.search('vault', 'interesting', type='huey')
            >>> print results['documents']
            [{u'content': u'Huey is not very interested in UFOs.',
              u'id': 2,
              u'indexes': [u'vault'],
              u'metadata': {u'type': u'huey'},
              u'score': 0.5}]

        To use a filter with multiple values, you can pass in a list. The resulting filter will use ``OR`` logic to combine the expressions. The resulting query searches for the word "interesting" and then filters the results such that the metadata type contains either the substring 'huey' or 'ufo':

        .. code-block:: pycon

            >>> results = scout.search('vault', 'interesting', type__contains=['huey', 'ufo'])
            >>> print results['documents']
            [{u'content': u'Huey is not very interested in UFOs.',
              u'id': 2,
              u'indexes': [u'vault'],
              u'metadata': {u'type': u'huey'},
              u'score': 0.6194637905555267},
             {u'content': u'The Rendlesham forest incident is one of the most interesting UFO accounts.',
              u'id': 1,
              u'indexes': [u'vault'],
              u'metadata': {u'type': u'ufo'},
              u'score': 0.48797383501308006}]
