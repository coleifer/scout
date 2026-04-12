.. _client:

Scout Client
============

Scout comes with a simple Python client. This document describes the client API.

.. py:class:: Scout(endpoint[, key=None])

    The :py:class:`Scout` class provides a simple, Pythonic API for interacting
    with and querying a Scout server.

    :param endpoint: The base URL the Scout server is running on.
    :param key: The authentication key (if used) required to access the Scout server.

    Example of initializing the client:

    .. code-block:: pycon

        >>> from scout.client import Scout
        >>> scout = Scout('https://search.my-site.com/', key='secret!')

    Index methods
    -------------

    .. py:method:: get_indexes(**kwargs)

        Return the list of indexes available on the server.

        See :ref:`index_list` for more information.

    .. py:method:: create_index(name)

        Create a new index with the given name. If an index with that name already exists, you will receive a 400 response.

        See the POST section of :ref:`index_list` for more information.

    .. py:method:: rename_index(old_name, new_name)

        Rename an existing index.

    .. py:method:: delete_index(name)

        Delete an existing index. Any documents associated with the index will **not** be deleted.

    .. py:method:: get_index(name, **kwargs)

        Return the details about the particular index, along with a paginated list of all documents stored in the given index.

        The following optional parameters are supported:

        :param q: full-text search query to be run over the documents in this index.
        :param ordering: columns to sort results by. By default, when you perform a search the results will be ordered by relevance.
        :param ranking: ranking algorithm to use. By default this is ``bm25``, however you can specify ``simple`` or ``none``.
        :param page: page number of results to retrieve.
        :param **filters: Arbitrary key/value pairs used to filter the metadata.

        The :ref:`metadata_filters` section describes how to use key/value pairs to construct filters on the document's metadata.

        See :ref:`index_detail` for more information.

    Document methods
    ----------------

    .. py:method:: create_document(content, indexes[, identifier=None[, attachments=None[, **metadata]]])

        Store a document in the specified index(es). If an ``identifier`` is provided and a document with that identifier already exists, the existing document will be updated.

        :param str content: Text content to expose for search.
        :param indexes: Either the name of an index or a list of index names.
        :param identifier: Optional alternative user-defined identifier for document.
        :param attachments: An optional mapping of filename to file-like object, which should be uploaded and stored as attachments on the given document.
        :param metadata: Arbitrary key/value pairs to store alongside the document content.

    .. py:method:: update_document(document_id[, content=None[, indexes=None[, metadata=None[, identifier=None[, attachments=None]]]]])

        Update one or more attributes of a document that's stored in the database.

        :param document_id: The integer document ID or a string identifier for the document to update.
        :param str content: Text content to expose for search (optional).
        :param indexes: Either the name of an index or a list of index names (optional).
        :param metadata: Arbitrary key/value pairs to store alongside the document content (optional).
        :param identifier: Set or change the document's identifier. This only updates the stored identifier - it is not used for looking up the document (use ``document_id`` for that).
        :param attachments: An optional mapping of filename to file-like object, which should be uploaded and stored as attachments on the given document. If a filename already exists, it will be over-written with the new attachment.

        .. note:: If you specify metadata when updating a document, existing metadata will be replaced by the new metadata. To simply clear out the metadata for an existing document, pass an empty ``dict``.

    .. py:method:: delete_document(document_id)

        Remove a document from the database, as well as all indexes, metadata, and attachments.

        :param document_id: The integer document ID, or a user-specified unique identifier.

    .. py:method:: get_document(document_id)

        Retrieve content for the given document.

        :param document_id: The integer document ID, or a user-specified unique identifier.

    .. py:method:: update_metadata(document_id, **metadata)

        Update metadata for the document by merging the new values into the
        existing metadata.

        :param document_id: The integer document ID, or a user-specified unique identifier.
        :param metadata: Arbitrary key/value metadata.

        Metadata is merged into the document's existing metadata using the
        following rules:

        Keys that exist will be overwritten with new user-provided values,
        unless the user-provided value is ``None`` in which case that key will
        be deleted (if it exists on the document). If no new data is specified
        then all existing document metadata will be cleared.

        Example:

        .. code-block:: python

            # Assume Document 1's metadata is empty to begin with: {}

            client.update_metadata(1, k1='v1', k2='v2')
            # metadata = {'k1': 'v1', 'k2': 'v2'}

            client.update_metadata(1, k1='v1x', k3='v3')
            # metadata = {'k1': 'v1x', 'k2': 'v2', 'k3': 'v3'}

            client.update_metadata(1, k1=None, k4='v4', k99=None)
            # metadata = {'k2': 'v2', 'k3': 'v3', 'k4': 'v4'}

            client.update_metadata(1)  # Clears metadata.
            # metadata = {}

    .. py:method:: get_documents(**kwargs)

        Retrieve a paginated list of all documents in the database, regardless of index. This method can also be used to perform full-text search queries across the entire database of documents, or a subset of indexes.

        The following optional parameters are supported:

        :param q: full-text search query to be run over the documents in this index.
        :param ordering: columns to sort results by. By default, when you perform a search the results will be ordered by relevance.
        :param index: one or more index names to restrict the results to.
        :param ranking: ranking algorithm to use. By default this is ``bm25``, however you can specify ``simple`` or ``none``.
        :param page: page number of results to retrieve.
        :param **filters: Arbitrary key/value pairs used to filter the metadata.

        The :ref:`metadata_filters` section describes how to use key/value pairs to construct filters on the document's metadata.

        See :ref:`document_list` for more information.

    Attachment methods
    ------------------

    .. py:method:: attach_files(document_id, attachments)

        :param document_id: The integer document ID or the user-specified document ``identifier``.
        :param attachments: A dictionary mapping filename to file-like object.

        Upload the attachments and associate them with the given document.

        For more information, see :ref:`attachment_list`.

    .. py:method:: detach_file(document_id, filename)

        :param document_id: The integer document ID or the user-specified document ``identifier``.
        :param filename: The filename of the attachment to remove.

        Detach the specified file from the document.

    .. py:method:: update_file(document_id, filename, file_object)

        :param document_id: The integer document ID or the user-specified document ``identifier``.
        :param filename: The filename of the attachment to update.
        :param file_object: A file-like object.

        Replace the contents of the current attachment with the contents of ``file_object``.

    .. py:method:: get_attachments(document_id, **kwargs)

        :param document_id: The integer document ID or the user-specified document ``identifier``.

        Retrieve a paginated list of attachments associated with the given document.

        The following optional parameters are supported:

        :param ordering: columns to use when sorting attachments.
        :param page: page number of results to retrieve.

        For more information, see :ref:`attachment_list`.

    .. py:method:: get_attachment(document_id, filename)

        :param document_id: The integer document ID or the user-specified document ``identifier``.
        :param filename: The filename of the attachment.

        Retrieve data about the given attachment.

        For more information, see :ref:`attachment_detail`.

    .. py:method:: download_attachment(document_id, filename)

        :param document_id: The integer document ID or the user-specified document ``identifier``.
        :param filename: The filename of the attachment.

        Download the specified attachment. Returns the raw file bytes.

        For more information, see :ref:`attachment_download`.

    .. py:method:: search_attachments(**kwargs)

        Search and filter attachments across all documents in the database.

        The following optional parameters are supported:

        :param ordering: columns to use when sorting attachments.
        :param page: page number of results to retrieve.
        :param index: restrict results to attachments on documents in the specified index.
        :param filename: filter by exact filename.
        :param mimetype: filter by exact MIME type.

        For more information, see :ref:`global_attachment_list`.

        Example:

        .. code-block:: pycon

            >>> results = scout.search_attachments(mimetype='image/jpeg')
            >>> for attachment in results['attachments']:
            ...     print(attachment['filename'])


SearchProvider and SearchSite
-----------------------------

The client module also provides helper classes for integrating Scout with
application models. These make it easy to automatically index and remove
objects.

.. py:class:: SearchProvider

    Abstract base class that defines how to extract searchable data from an application object.

    .. py:method:: content(obj)

        Return the text content for the given object to be indexed for search. **Required.**

    .. py:method:: identifier(obj)

        Return a unique identifier string for the given object. Optional; if
        not implemented, no identifier will be stored.

    .. py:method:: metadata(obj)

        Return a dictionary of metadata key/value pairs for the given object.
        Optional; if not implemented, no metadata will be stored.

.. py:class:: SearchSite(client, index)

    Manages a registry of model classes and their search providers, and provides methods to store and remove objects from a Scout index.

    :param client: A :py:class:`Scout` client instance.
    :param index: The name of the index to use for all operations.

    .. py:method:: register(model_class, search_provider)

        Register a :py:class:`SearchProvider` subclass for the given model
        class. Multiple providers can be registered for the same model class.

        :param model_class: The class of objects to be indexed.
        :param search_provider: A :py:class:`SearchProvider` subclass (not an instance).

    .. py:method:: unregister(model_class[, search_provider=None])

        Remove a search provider registration. If ``search_provider`` is
        ``None``, all providers for the given model class are removed.

        :param model_class: The class to unregister.
        :param search_provider: Optional specific provider class to remove.

    .. py:method:: store(obj)

        Index the given object using all registered providers for its type.
        Returns ``True`` if the object's type was registered, ``False``
        otherwise.

        :param obj: The object to index.

    .. py:method:: remove(obj)

        Remove the given object from the search index. Returns ``True`` if the
        object's type was registered, ``False`` otherwise.

        :param obj: The object to remove.

    Example usage:

    .. code-block:: python

        from scout.client import Scout, SearchProvider, SearchSite

        class BlogPostProvider(SearchProvider):
            def content(self, post):
                return '%s\n%s' % (post.title, post.body)

            def identifier(self, post):
                return str(post.id)

            def metadata(self, post):
                return {
                    'title': post.title,
                    'published': str(post.is_published),
                }

        scout = Scout('http://localhost:8000')
        site = SearchSite(scout, 'blog-posts')
        site.register(BlogPost, BlogPostProvider)

        # Index a blog post.
        site.store(my_post)

        # Remove a blog post from the index.
        site.remove(my_post)
