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
        :param page: page number of results to retrieve
        :param **filters: Arbitrary key/value pairs used to filter the metadata.

        The :ref:`metadata_filters` section describes how to use key/value pairs t construct filters on the document's metadata.

        See :ref:`index_detail` for more information.

    .. py:method:: create_document(content, indexes[, identifier=None[, attachments=None[, **metadata]]])

        Store a document in the specified index(es).

        :param str content: Text content to expose for search.
        :param indexes: Either the name of an index or a list of index names.
        :param identifier: Optional alternative user-defined identifier for document.
        :param attachments: An optional mapping of filename to file-like object, which should be uploaded and stored as attachments on the given document.
        :param metadata: Arbitrary key/value pairs to store alongside the document content.

    .. py:method:: update_document([document_id=None[, content=None[, indexes=None[, metadata=None[, identifier=None[, attachments=None]]]]]])

        Update one or more attributes of a document that's stored in the database.

        :param int document_id: The integer document ID (required).
        :param str content: Text content to expose for search (optional).
        :param indexes: Either the name of an index or a list of index names (optional).
        :param metadata: Arbitrary key/value pairs to store alongside the document content (optional).
        :param identifier: Optional alternative user-defined identifier for document.
        :param attachments: An optional mapping of filename to file-like object, which should be uploaded and stored as attachments on the given document. If a filename already exists, it will be over-written with the new attachment.

        .. note:: If you specify metadata when updating a document, existing metadata will be replaced by the new metadata. To simply clear out the metadata for an existing document, pass an empty ``dict``.

    .. py:method:: delete_document(document_id)

        Remove a document from the database, as well as all indexes.

        :param int document_id: The integer document ID.

    .. py:method:: get_document(document_id)

        Retrieve content for the given document.

        :param int document_id: The integer document ID.

    .. py:method:: get_documents(**kwargs)

        Retrieve a paginated list of all documents in the database, regardless of index. This method can also be used to perform full-text search queries across the entire database of documents, or a subset of indexes.

        The following optional parameters are supported:

        :param q: full-text search query to be run over the documents in this index.
        :param ordering: columns to sort results by. By default, when you perform a search the results will be ordered by relevance.
        :param index: one or more index names to restrict the results to.
        :param ranking: ranking algorithm to use. By default this is ``bm25``, however you can specify ``simple`` or ``none``.
        :param page: page number of results to retrieve
        :param **filters: Arbitrary key/value pairs used to filter the metadata.

        The :ref:`metadata_filters` section describes how to use key/value pairs t construct filters on the document's metadata.

        See :ref:`document_list` for more information.

    .. py:method:: attach_files(document_id, attachments)

        :param document_id: The integer ID of the document.
        :param attachments: A dictionary mapping filename to file-like object.

        Upload the attachments and associate them with the given document.

        For more information, see :ref:`attachment_list`.

    .. py:method:: detach_file(document_id, filename)

        :param document_id: The integer ID of the document.
        :param filename: The filename of the attachment to remove.

        Detach the specified file from the document.

    .. py:method:: update_file(document_id, filename, file_object)

        :param document_id: The integer ID of the document.
        :param filename: The filename of the attachment to update.
        :param file_object: A file-like object.

        Replace the contents of the current attachment with the contents of ``file_object``.

    .. py:method:: get_attachments(document_id, **kwargs)

        Retrieve a paginated list of attachments associated with the given document.

        The following optional parameters are supported:

        :param ordering: columns to use when sorting attachments.
        :param page: page number of results to retrieve

        For more information, see :ref:`attachment_list`.

    .. py:method:: get_attachment(document_id, filename)

        Retrieve data about the given attachment.

        For more information, see :ref:`attachment_detail`.

    .. py:method:: download_attachment(document_id, filename)

        Download the specified attachment.

        For more information, see :ref:`attachment_download`.
