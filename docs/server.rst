.. _server:

Scout Server
============

Scout server is a RESTful Flask application that provides endpoints for
managing indexes, documents, metadata and performing searches. To get started
with Scout, you can simply run the server from the command-line and specify the
path to a SQLite database file which will act as the search index.

.. note:: If the database does not exist, it will be created.

.. code-block:: console

    $ scout my_search_index.db
     * Running on http://127.0.0.1:8000/ (Press CTRL+C to quit)

This will run Scout locally on port 8000 using the Werkzeug multi-threaded WSGI
server. The werkzeug server is perfect for getting started and small deployments.
For a production-ready server powered by `gevent <https://www.gevent.org/>`_,
you can instead run:

.. code-block:: console

    $ scout_wsgi my_search_index.db

You can find examples of using other high performance WSGI servers in the
:ref:`deployment section <deployment>`.

All of the examples below show raw HTTP requests using ``curl`` as well as the
equivalent call using the :ref:`Scout Python client <client>`. To initialize
the client:

.. code-block:: python

    from scout.client import Scout
    scout = Scout('http://localhost:8000')

    # If authentication is enabled:
    scout = Scout('http://localhost:8000', key='secret')

API Endpoints
-------------

There are four main concepts in Scout:

* Indexes
* Documents
* Attachments
* Metadata

**Indexes**
   named collection of searchable documents.

**Documents**
   searchable content, may be associated with any number of indexes.

**Attachments**
   arbitrary files which are associated with a document. For instance, if you
   were using Scout to provide search over a library of PDFs, your **Document**
   might contain the key search terms from the PDF and the actual PDF would be
   linked to the document as an attachment. A document may have any number of
   attachments, or none at all.

Documents also can have **metadata**, arbitrary key/value pairs. Besides
full-text search, Scout allows complex filtering based on metadata values. So
in addition to storing useful things alongside your documents, you can also use
metadata to provide an additional layer of filtering.

.. _index_list:

Index list: "/"
---------------

The index list endpoint returns a paginated list of indexes and the number of
documents contained within each. New indexes can be created by POST-ing a name
to this URL.

Valid GET parameters:

* ``page``: which page of results to fetch, by default 1.
* ``ordering``: order in which to return the indexes. By default they are
  returned ordered by name. Valid values are ``name``, ``id``, and
  ``document_count``. By prefixing the name with a *minus* sign ("-") you can
  indicate the results should be ordered descending.

Example GET request and response:

.. code-block:: console

    $ curl localhost:8000/

Using the Python client:

.. code-block:: python

    indexes = scout.get_indexes()

Response:

.. code-block:: javascript

    {
      "indexes": [
        {
          "document_count": 75,
          "documents": "/blog/",
          "id": 1,
          "name": "blog"
        },
        {
          "document_count": 36,
          "documents": "/photos/",
          "id": 2,
          "name": "photos"
        }
      ],
      "ordering": [],
      "page": 1,
      "pages": 1,
      "next_url": null,
      "previous_url": null
    }

.. note::
    The ``get_indexes()`` method returns just the ``"indexes"`` list from the
    response, not the full paginated envelope.

Example POST request and response:

.. code-block:: console

    $ curl -H "Content-Type: application/json" -d '{"name": "test-index"}' localhost:8000/

Using the Python client:

.. code-block:: python

    new_index = scout.create_index('test-index')

Response:

.. code-block:: javascript

    {
      "document_count": 0,
      "documents": [],
      "id": 3,
      "name": "test-index",
      "page": 1,
      "pages": 0,
      "next_url": null,
      "previous_url": null
    }

The POST response corresponds to the serialized index detail for the
newly-created index.

.. _index_detail:

Index detail: "/:index-name/"
-----------------------------

The index detail returns the name and ID of the index, as well as a paginated list of documents associated with the index. The index can be re-named by POSTing a ``name`` to this URL.

Valid GET parameters:

* ``q``: full-text search query.
* ``page``: which page of results to fetch, by default 1.
* ``ordering``: order in which to return the documents. By default they are returned in arbitrary order, unless a search query is present, in which case they are ordered by relevance. Valid choices are ``id``, ``identifier``, ``content``, and ``score``. By prefixing the name with a *minus* sign ("-") you can indicate the results should be ordered descending. **Note**: this parameter can appear multiple times.
* ``ranking``: when a full-text search query is specified, this parameter determines the ranking algorithm. Valid choices are:

  * ``bm25``: use the `Okapi BM25 algorithm <http://en.wikipedia.org/wiki/Okapi_BM25>`_,
    which is natively supported by SQLite FTS5.
  * ``none``: do not use any ranking algorithm. Search results will not have a
    *score* attribute.

* **Arbitrary metadata filters**. See :ref:`metadata_filters` for a description of metadata filtering.

When a search query is present, each returned document will have an additional
field named ``score``. This field contains the numerical value the scoring
algorithm gave to the document. To disable scores when searching, you can
specify ``ranking=none``.

Example ``GET`` request and response.

.. code-block:: console

    $ curl localhost:8000/test-index/?q=test

Using the Python client:

.. code-block:: python

    results = scout.get_index('test-index', q='test')

Response:

.. code-block:: javascript

    {
      "document_count": 3,
      "documents": [
        {
          "attachments": [],
          "content": "test charlie document",
          "id": 115,
          "identifier": null,
          "indexes": [
            "test-index"
          ],
          "metadata": {
            "is_kitty": "no"
          },
          "score": -0.022727272727272728
        },
        {
          "attachments": [
            {
              "data": "/documents/116/attachments/example.jpg/download/",
              "data_length": 31337,
              "filename": "example.jpg",
              "mimetype": "image/jpeg",
              "timestamp": "2016-01-04 13:37:00"
            }
          ],
          "content": "test huey document",
          "id": 116,
          "identifier": null,
          "indexes": [
            "test-index"
          ],
          "metadata": {
            "is_kitty": "yes"
          },
          "score": -0.022727272727272728
        },
        {
          "attachments": [],
          "content": "test mickey document",
          "id": 117,
          "identifier": null,
          "indexes": [
            "test-index"
          ],
          "metadata": {
            "is_kitty": "no"
          },
          "score": -0.022727272727272728
        }
      ],
      "filtered_count": 3,
      "filters": {},
      "id": 3,
      "name": "test-index",
      "ordering": [],
      "page": 1,
      "pages": 1,
      "next_url": null,
      "previous_url": null,
      "ranking": "bm25",
      "search_term": "test"
    }

``POST`` requests update the ``name`` of the index, and like the *index_list*
view, accept a ``name`` parameter. For example request and response, see the
above section on creating a new index.

Example of renaming an index:

.. code-block:: console

    $ curl -H "Content-Type: application/json" -d '{"name": "new-name"}' localhost:8000/test-index/

Using the Python client:

.. code-block:: python

    renamed = scout.rename_index('test-index', 'new-name')

``DELETE`` requests will delete the index, but all documents will be preserved in the database.

Example of deleting an index:

.. code-block:: console

    $ curl -X DELETE localhost:8000/photos/

Using the Python client:

.. code-block:: python

    scout.delete_index('photos')

Response:

.. code-block:: javascript

    {"success": true}

.. _metadata_filters:

Filtering on Metadata
---------------------

Suppose we have an index that contains all of our contacts. The search content
consists of the person's name, address, city, and state. We also have stored
quite a bit of metadata about each person. A person record might look like
this:

.. code-block:: javascript

    {'content': "Huey Leifer 123 Main Street Lawrence KS 66044"}

The metadata for this record consists of the following:

.. code-block:: javascript

    {'metadata': {
      'dob': '2010-06-01',
      'city': 'Lawrence',
      'state': 'KS',
    }}

To search for all my relatives living in Kansas, I could use the following URL:

``/contacts-index/?q=Leifer+OR+Morgan&state=KS``

Using the Python client:

.. code-block:: python

    results = scout.get_index('contacts-index', q='Leifer OR Morgan', state='KS')

Let's say we want to search our contacts index for all people who were born in
1983. We could use the following URL:

``/contacts-index/?dob__ge=1983-01-01&dob__lt=1984-01-01``

Using the Python client:

.. code-block:: python

    results = scout.get_index(
        'contacts-index',
        q='*',
        dob__ge='1983-01-01',
        dob__lt='1984-01-01')

To search for all people who live in Lawrence or Topeka, KS we could use the
following URL:

``/contacts-index/?city__in=Lawrence,Topeka&state=KS``

Using the Python client:

.. code-block:: python

    results = scout.get_index(
        'contacts-index',
        q='*',
        city__in='Lawrence,Topeka',
        state='KS')

Scout will take all filters and return only those records that match all of the
given conditions. However, when the same key is used multiple times, Scout will
use ``OR`` to join those clauses. For example, another way we could query for
people who live in Lawrence or Topeka would be:

``/contacts-index/?q=*&city=Lawrence&city=Topeka&state=KS``

As you can see, we're querying ``city=XXX`` twice. Scout will interpret that as
meaning ``(city=Lawrence OR city=Topeka) AND state=KS``.

Query operations
^^^^^^^^^^^^^^^^

There are a number of operations available for use when querying metadata. Here is the complete list:

* ``keyname__eq``: Default (when only the key name is supplied). Returns documents whose metadata contains the given key/value pair.
* ``keyname__ne``: Not equals.
* ``keyname__ge``: Greater-than or equal-to.
* ``keyname__gt``: Greater-than.
* ``keyname__le``: Less-than or equal-to.
* ``keyname__lt``: Less-than.
* ``keyname__in``: In. The value should be a comma-separated list of values to match.
* ``keyname__contains``: Substring search.
* ``keyname__startswith``: Prefix search.
* ``keyname__endswith``: Suffix search.
* ``keyname__regex``: Search using a regular expression.

.. _document_list:

Document list: "/documents/"
----------------------------

The document list endpoint returns a paginated list of all documents,
regardless of index. New documents are created by ``POST``-ing the content,
index(es) and optional metadata.

Valid GET parameters:

* ``q``: full-text search query.
* ``page``: which page of documents to fetch, by default 1.
* ``index``: the name of an index to restrict the results to. **Note**: this parameter can appear multiple times. When multiple indexes are specified, the ``document_count`` reflects the number of distinct documents across those indexes (a document belonging to multiple filtered indexes is only counted once).
* ``ordering``: order in which to return the documents. By default they are returned in arbitrary order, unless a search query is present, in which case they are ordered by relevance. Valid choices are ``id``, ``identifier``, ``content``, and ``score``. By prefixing the name with a *minus* sign ("-") you can indicate the results should be ordered descending. **Note**: this parameter can appear multiple times.
* ``ranking``: when a full-text search query is specified, this parameter determines the ranking algorithm. Valid choices are:

  * ``bm25``: use the `Okapi BM25 algorithm <http://en.wikipedia.org/wiki/Okapi_BM25>`_, which is
    natively supported by SQLite FTS5.
  * ``none``: do not use any ranking algorithm. Search results will not have a *score* attribute.

* **Arbitrary metadata filters**. See :ref:`metadata_filters` for a description of metadata filtering.

When a search query is present, each returned document will have an additional
field named ``score``. This field contains the numerical value the scoring
algorithm gave to the document. To disable scores when searching, you can
specify ``ranking=none``.

Example ``GET`` request and response. In the request below we are searching for
the string *"test"* in the ``photos``, ``articles`` and ``videos`` indexes.

.. code-block:: console

    $ curl localhost:8000/documents/?q=test&index=photos&index=articles&index=videos

Using the Python client:

.. code-block:: python

    results = scout.get_documents(q='test', index=['photos', 'articles', 'videos'])

Response:

.. code-block:: javascript

    {
      "document_count": 207,
      "documents": [
        {
          "attachments": [
            {
              "data": "/documents/72/attachments/example.jpg/download/",
              "data_length": 31337,
              "filename": "example.jpg",
              "mimetype": "image/jpeg",
              "timestamp": "2016-03-01 13:37:00"
            }
          ],
          "content": "test photo",
          "id": 72,
          "identifier": null,
          "indexes": [
            "photos"
          ],
          "metadata": {
            "timestamp": "2016-03-01 13:37:00"
          },
          "score": -0.01304
        },
        {
          "attachments": [
            {
              "data": "/documents/61/attachments/movie.mp4/download/",
              "data_length": 3131337,
              "filename": "movie.mp4",
              "mimetype": "video/mp4",
              "timestamp": "2016-03-02 13:37:00"
            }
          ],
          "content": "test video upload",
          "id": 61,
          "identifier": null,
          "indexes": [
            "videos"
          ],
          "metadata": {
            "timestamp": "2016-03-02 13:37:00"
          },
          "score": -0.01407
        }
      ],
      "filtered_count": 2,
      "filters": {},
      "ordering": [],
      "page": 1,
      "pages": 1,
      "next_url": null,
      "previous_url": null,
      "ranking": "bm25",
      "search_term": "test"
    }

``POST`` requests should have the following parameters:

* ``content`` (required): the document content.
* ``index`` or ``indexes`` (required): the name(s) of the index(es) the document should be associated with.
* ``identifier`` (optional): an application-defined identifier for the document. If a document with the same identifier already exists, the existing document will be updated instead of creating a new one.
* ``metadata`` (optional): arbitrary key/value pairs.

.. warning::
    Identifiers should not be purely numeric strings (e.g. ``"42"``). When
    looking up a document, Scout first checks the ``identifier`` field, then
    falls back to matching by internal ``id``. A numeric identifier could
    collide with the internal ID of an unrelated document, leading to
    unexpected results.

Example ``POST`` request creating a new document:

.. code-block:: console

    $ curl \
        -H "Content-Type: application/json" \
        -d '{"content": "New document", "indexes": ["test-index"]}' \
        http://localhost:8000/documents/

Using the Python client:

.. code-block:: python

    doc = scout.create_document('New document', 'test-index')

    # With multiple indexes, an identifier, and metadata:
    doc = scout.create_document(
        'New document',
        ['test-index', 'blog'],
        identifier='my-doc-1',
        author='somebody',
        published='true')

Response on creating a new document:

.. code-block:: javascript

    {
      "attachments": [],
      "content": "New document",
      "id": 121,
      "identifier": null,
      "indexes": [
        "test-index"
      ],
      "metadata": {}
    }


.. _document_detail:

Document detail: "/documents/:document-id/"
-------------------------------------------

The document detail endpoint returns document content, indexes, and metadata.
Documents can be updated or deleted by using ``POST`` and ``DELETE`` requests,
respectively. When updating a document, you can update the ``content``,
``index(es)``, ``identifier``, and/or ``metadata``.

The ``:document-id`` parameter is resolved in the following order:

1. Scout first attempts to find a document whose user-defined ``identifier``
   matches the given value.
2. If no match is found **and** the value is numeric, Scout falls back to
   looking up the document by its internal ``id`` (rowid).

This means a purely numeric ``identifier`` like ``"42"`` is ambiguous. If no
document has that identifier, the request will silently resolve to whichever
document has internal ID 42. For this reason, user-defined identifiers should
include at least one non-numeric character (e.g. ``"doc-42"``, ``"post:42"``).

.. warning::
    If you choose to update metadata, all current metadata for the document
    will be removed, so it's really more of a "replace" than an "update". To
    clear all metadata for a document, pass ``"metadata": null`` or
    ``"metadata": {}``.

.. note::
    When updating a document, omitting a field preserves its current value. For
    example, omitting ``indexes`` from a POST will leave the document's index
    associations unchanged. However, passing an empty list (``"indexes": []``)
    will explicitly clear all index associations.

Example ``GET`` request and response:

.. code-block:: console

    $ curl localhost:8000/documents/118/

Using the Python client:

.. code-block:: python

    doc = scout.get_document(118)

Response:

.. code-block:: javascript

    {
      "attachments": [],
      "content": "test zaizee document",
      "id": 118,
      "identifier": null,
      "indexes": [
        "test-index"
      ],
      "metadata": {
        "is_kitty": "yes"
      }
    }

Here is an example of updating the content and indexes using a ``POST`` request:

.. code-block:: console

    $ curl \
        -H "Content-Type: application/json" \
        -d '{"content": "test zaizee updated", "indexes": ["test-index", "blog"]}' \
        http://localhost:8000/documents/118/

Using the Python client:

.. code-block:: python

    updated = scout.update_document(
        document_id=118,
        content='test zaizee updated',
        indexes=['test-index', 'blog'])

    # Update metadata only (replaces all existing metadata):
    updated = scout.update_document(
        document_id=118,
        metadata={'is_kitty': 'yes', 'color': 'gray'})

    # Clear all metadata:
    updated = scout.update_document(document_id=118, metadata={})

Response:

.. code-block:: javascript

    {
      "attachments": [],
      "content": "test zaizee updated",
      "id": 118,
      "identifier": null,
      "indexes": [
        "blog",
        "test-index"
      ],
      "metadata": {
        "is_kitty": "yes"
      }
    }

``DELETE`` requests can be used to completely remove a document. Deleting a document will also remove all of its metadata, index associations, and attachments. Orphaned attachment data (BLOBs not referenced by any other document) will be cleaned up automatically.

Example ``DELETE`` request and response:

.. code-block:: console

  $ curl -X DELETE localhost:8000/documents/121/

Using the Python client:

.. code-block:: python

    scout.delete_document(121)

Response:

.. code-block:: javascript

    {"success": true}

.. _document_identifiers:

Working with Document Identifiers
----------------------------------

Every document in Scout has an auto-generated integer ``id``. Optionally, you
can also assign a user-defined ``identifier``, an application-specific string
that lets you reference documents without tracking Scout's internal IDs.

Identifiers are useful because they decouple your application's data model from
Scout's storage. Instead of storing Scout document IDs in your application
database, you can derive the identifier from something you already have (a
primary key, a URL slug, a UUID, or any other unique string). This means your
application can create, update, retrieve, and delete documents using its own
natural keys.

Creating a document with an identifier
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

.. code-block:: console

    $ curl \
        -H "Content-Type: application/json" \
        -d '{"content": "My blog post about cats", "indexes": ["blog"], "identifier": "post-42"}' \
        http://localhost:8000/documents/

Using the Python client:

.. code-block:: python

    scout.create_document(
        'My blog post about cats',
        'blog',
        identifier='post-42')

Retrieving and updating by identifier
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Once a document has an identifier, you can use it anywhere a document ID is
accepted - in the URL path for ``GET``, ``POST``, and ``DELETE`` requests:

.. code-block:: console

    $ curl localhost:8000/documents/post-42/

Using the Python client:

.. code-block:: python

    doc = scout.get_document('post-42')

Updates work the same way:

.. code-block:: python

    scout.update_document(
        document_id='post-42',
        content='My updated blog post about cats and dogs',
        metadata={'tags': 'pets'})

Upsert behavior
^^^^^^^^^^^^^^^

When you create a document with an ``identifier`` that already exists, Scout
updates the existing document instead of creating a duplicate. This gives you
upsert semantics - your application can push content to Scout without checking
whether the document already exists:

.. code-block:: python

    # First call creates the document.
    scout.create_document('Draft v1', 'blog', identifier='post-99')

    # Second call with the same identifier updates it.
    scout.create_document('Draft v2 — now with more content', 'blog',
                          identifier='post-99')

    # There is still only one document with identifier "post-99".
    doc = scout.get_document('post-99')
    print(doc['content'])  # Draft v2 — now with more content

This is especially convenient when re-indexing content. You can re-run your
indexing script without worrying about creating duplicate documents. As long as
you provide consistent identifiers, Scout will update in place.

Deleting by identifier
^^^^^^^^^^^^^^^^^^^^^^

.. code-block:: console

    $ curl -X DELETE localhost:8000/documents/post-42/

Using the Python client:

.. code-block:: python

    scout.delete_document('post-42')

.. _update_metadata:

Update metadata: "/documents/:document-id/metadata/"
-----------------------------------------------------

The update metadata endpoint merges new metadata into a document's existing
metadata, rather than replacing it entirely (as happens when you include
``metadata`` in a document update via :ref:`document_detail`). This is useful
when you need to add or change individual keys without re-supplying the full
set.

``POST`` or ``PUT`` a JSON object with a ``metadata`` key. The value should be
an object of key/value pairs to merge. The merge follows these rules:

* Keys that already exist on the document are overwritten with the new values.
* New keys are added.
* Keys whose value is ``null`` are deleted from the document's metadata (if
  they exist).
* If ``metadata`` is empty (``{}``), all existing metadata is cleared.

Example ``POST`` request:

.. code-block:: console

    $ curl \
        -H "Content-Type: application/json" \
        -d '{"metadata": {"k1": "v1", "k2": "v2"}}' \
        http://localhost:8000/documents/118/metadata/

Using the Python client:

.. code-block:: python

    scout.update_metadata(118, k1='v1', k2='v2')

Response:

.. code-block:: javascript

    {
      "attachments": [],
      "content": "test zaizee document",
      "id": 118,
      "identifier": null,
      "indexes": [
        "test-index"
      ],
      "metadata": {
        "k1": "v1",
        "k2": "v2"
      }
    }

Subsequent calls merge into the existing metadata. For example, after the
request above:

.. code-block:: console

    $ curl \
        -H "Content-Type: application/json" \
        -d '{"metadata": {"k1": "v1-updated", "k3": "v3"}}' \
        http://localhost:8000/documents/118/metadata/

Using the Python client:

.. code-block:: python

    scout.update_metadata(118, k1='v1-updated', k3='v3')

The resulting metadata would be ``{"k1": "v1-updated", "k2": "v2", "k3": "v3"}``.

To delete a specific key, set its value to ``null``:

.. code-block:: console

    $ curl \
        -H "Content-Type: application/json" \
        -d '{"metadata": {"k2": null}}' \
        http://localhost:8000/documents/118/metadata/

Using the Python client:

.. code-block:: python

    scout.update_metadata(118, k2=None)

The resulting metadata would be ``{"k1": "v1-updated", "k3": "v3"}``.

To clear all metadata, pass an empty object:

.. code-block:: console

    $ curl \
        -H "Content-Type: application/json" \
        -d '{"metadata": {}}' \
        http://localhost:8000/documents/118/metadata/

Using the Python client:

.. code-block:: python

    scout.update_metadata(118)

.. note::
    This endpoint differs from updating metadata through the
    :ref:`document detail <document_detail>` endpoint. The document detail
    endpoint **replaces** all metadata, while this endpoint **merges** new
    values into the existing metadata.

.. _attachment_list:

Attachment list: "/documents/:document-id/attachments/"
-------------------------------------------------------

The attachment list endpoint returns a paginated list of all attachments associated with a given document. New attachments are created by ``POST``-ing a file to this endpoint.

Valid GET parameters:

* ``page``: which page of attachments to fetch, by default 1.
* ``ordering``: order in which to return the attachments. By default they are returned by filename. Valid choices are ``id``, ``hash``, ``filename``, ``mimetype``, and ``timestamp``. By prefixing the name with a *minus* sign ("-") you can indicate the results should be ordered descending. **Note**: this parameter can appear multiple times.

Example ``GET`` request and response.

.. code-block:: console

    $ curl localhost:8000/documents/13/attachments/?ordering=timestamp

Using the Python client:

.. code-block:: python

    attachments = scout.get_attachments(13, ordering='timestamp')

Response:

.. code-block:: javascript

    {
      "attachments": [
        {
          "data": "/documents/13/attachments/banner.jpg/download/",
          "data_length": 135350,
          "document": "/documents/13/",
          "filename": "banner.jpg",
          "mimetype": "image/jpeg",
          "timestamp": "2016-03-01 13:37:01"
        },
        {
          "data": "/documents/13/attachments/background.jpg/download/",
          "data_length": 25039,
          "document": "/documents/13/",
          "filename": "background.jpg",
          "mimetype": "image/jpeg",
          "timestamp": "2016-03-01 13:37:02"
        }
      ],
      "ordering": ["timestamp"],
      "page": 1,
      "pages": 1,
      "next_url": null,
      "previous_url": null
    }

``POST`` requests should contain the attachments as form-encoded files. The
:ref:`Scout client <client>` will handle this automatically for you.

Example ``POST`` request uploading a new attachment:

.. code-block:: console

    $ curl \
        -H "Content-Type: multipart/form-data" \
        -F 'data=""' \
        -F "file_0=@/path/to/image.jpg" \
        -X POST \
        http://localhost:8000/documents/13/attachments/

Using the Python client:

.. code-block:: python

    from io import BytesIO

    result = scout.attach_files(13, {
        'image.jpg': open('/path/to/image.jpg', 'rb'),
    })

    # Multiple files at once:
    result = scout.attach_files(13, {
        'photo.jpg': open('/path/to/photo.jpg', 'rb'),
        'notes.txt': BytesIO(b'Some notes about this document'),
    })

Response on creating a new attachment:

.. code-block:: javascript

    {
      "attachments": [
        {
          "data": "/documents/13/attachments/some-image.jpg/download/",
          "data_length": 18912,
          "document": "/documents/13/",
          "filename": "some-image.jpg",
          "mimetype": "image/jpeg",
          "timestamp": "2016-03-14 13:38:00"
        }
      ]
    }

.. note:: You can upload multiple attachments at the same time.

Attachments can also be included when creating or updating a document:

.. code-block:: python

    doc = scout.create_document(
        'Document with files',
        'my-index',
        attachments={
            'readme.txt': BytesIO(b'Read me!'),
            'data.csv': open('/path/to/data.csv', 'rb'),
        },
        author='alice')

.. _attachment_detail:

Attachment detail: "/documents/:document-id/attachments/:filename/"
-------------------------------------------------------------------

The attachment detail endpoint returns basic information about the attachment,
as well as a link to download the actual attached file. Attachments can be
updated or deleted by using ``POST`` and ``DELETE`` requests, respectively.
When you update an attachment, the original is deleted and a new attachment
created for the uploaded content.

Example ``GET`` request and response:

.. code-block:: console

    $ curl localhost:8000/documents/13/attachments/test-image.png/

Using the Python client:

.. code-block:: python

    attachment = scout.get_attachment(13, 'test-image.png')

Response:

.. code-block:: javascript

    {
      "data": "/documents/13/attachments/test-image.png/download/",
      "data_length": 3710133,
      "document": "/documents/13/",
      "filename": "test-image.png",
      "mimetype": "image/png",
      "timestamp": "2016-03-14 22:10:00"
    }

Example of updating (replacing) an attachment:

.. code-block:: console

    $ curl \
        -H "Content-Type: multipart/form-data" \
        -F 'data=""' \
        -F "file_0=@/path/to/new-image.png" \
        -X POST \
        http://localhost:8000/documents/13/attachments/test-image.png/

Using the Python client:

.. code-block:: python

    scout.update_file(13, 'test-image.png', open('/path/to/new-image.png', 'rb'))

``DELETE`` requests are used to **detach** a file from a document.

Example ``DELETE`` request and response:

.. code-block:: console

  $ curl -X DELETE localhost:8000/documents/13/attachments/test-image.png/

Using the Python client:

.. code-block:: python

    scout.detach_file(13, 'test-image.png')

Response:

.. code-block:: javascript

    {"success": true}

.. _attachment_download:

Attachment download: "/documents/:document-id/attachments/:filename/download/"
------------------------------------------------------------------------------

The attachment download endpoint is a special URL that returns the attached
file as a downloadable HTTP response. This is the only way to access an
attachment's underlying file data.

To download an attachment, simply send a ``GET`` request to the attachment's "data" URL:

.. code-block:: console

    $ curl http://localhost:8000/documents/13/attachments/banner.jpg/download/

Using the Python client:

.. code-block:: python

    raw_bytes = scout.download_attachment(13, 'banner.jpg')

    # Save to a file:
    with open('banner.jpg', 'wb') as fh:
        fh.write(raw_bytes)

.. _global_attachment_list:

Global attachment list: "/attachments/"
---------------------------------------

The global attachment list endpoint returns a paginated list of all attachments
across all documents in the database. This is useful for browsing or searching
all uploaded files without knowing which document they belong to.

Valid GET parameters:

* ``page``: which page of results to fetch, by default 1.
* ``ordering``: order in which to return the attachments. By default they are returned by filename. Valid choices are ``filename``, ``mimetype``, ``timestamp``, and ``id``. By prefixing the name with a *minus* sign ("-") you can indicate the results should be ordered descending.
* ``index``: restrict results to attachments on documents belonging to the specified index. **Note**: this parameter can appear multiple times.
* ``filename``: filter by exact filename.
* ``mimetype``: filter by exact MIME type.

Example ``GET`` request and response:

.. code-block:: console

    $ curl localhost:8000/attachments/?mimetype=image/jpeg

Using the Python client:

.. code-block:: python

    results = scout.search_attachments(mimetype='image/jpeg')

Response:

.. code-block:: javascript

    {
      "attachments": [
        {
          "data": "/documents/1/attachments/photo.jpg/download/",
          "data_length": 31337,
          "document": "/documents/1/",
          "filename": "photo.jpg",
          "mimetype": "image/jpeg",
          "timestamp": "2016-03-01 13:37:00"
        }
      ],
      "ordering": [],
      "page": 1,
      "pages": 1,
      "next_url": null,
      "previous_url": null
    }

Example filtering by index:

.. code-block:: console

    $ curl localhost:8000/attachments/?index=blog&index=photos

Using the Python client:

.. code-block:: python

    results = scout.search_attachments(index='blog')

    # Filter by index and filename:
    results = scout.search_attachments(index='blog', filename='header.png')

This will return all attachments belonging to documents in the ``blog`` or ``photos`` indexes.

Example of using Authentication
-------------------------------

Scout provides very basic key-based authentication. You can specify a single,
global key which must be specified in order to access the API.

To specify the API key, you can pass it in on the command-line or specify it in
a configuration file (described below).

Example of running scout with an API key:

.. code-block:: console

    $ scout -k secret /path/to/search.db

If we try to access the API without specifying the key, we get a ``401``
response stating Invalid API key:

.. code-block:: console

    $ curl localhost:8000/
    Invalid API key

We can specify the key as a header:

.. code-block:: console

    $ curl -H "key: secret" localhost:8000/
    {
      "indexes": []
    }

Alternatively, the key can be specified as a ``GET`` argument:

.. code-block:: console

    $ curl localhost:8000/?key=secret
    {
      "indexes": []
    }

Using the Python client, the key is passed when initializing the client and is
automatically included with every request:

.. code-block:: python

    scout = Scout('http://localhost:8000', key='secret')
    indexes = scout.get_indexes()  # Key is sent automatically.

.. _command-line-options:

Configuration and Command-Line Options
--------------------------------------

The easiest way to run Scout is to invoke it directly from the command-line,
passing the database in as the last argument:

.. code-block:: console

    $ scout /path/to/search.db

The database file can also be specified using the ``SCOUT_DATABASE`` environment variable:

.. code-block:: console

    $ SCOUT_DATABASE=/path/to/search.db scout

Scout supports a handful of configuration options to control its behavior when run from the command-line. The following table describes these options:

* ``-H``, ``--host``: set the hostname to listen on. Defaults to ``127.0.0.1``.
* ``-p``, ``--port``: set the port to listen on. Defaults to ``8000``.
* ``-u``, ``--url-prefix``: URL path to prefix Scout API with, e.g. ``/search``.
* ``-s``, ``--stem``: set the stemming algorithm. Valid options are ``simple`` and ``porter``. Defaults to ``porter`` stemmer. This option only takes effect when a new database is created, as the stemming algorithm is part of the table definition.
* ``-d``, ``--debug``: boolean flag to run Scout in debug mode.
* ``-c``, ``--config``: set the configuration file (a Python module). See the configuration options for available settings.
* ``--paginate-by``: set the number of documents displayed per page of results. Default is 50. Must be between 1 and 1000.
* ``-k``, ``--api-key``: set the API key required to access Scout. By default no authentication is required.
* ``-C``, ``--cache-size``: set the size of the SQLite page cache (in MB), defaults to 64.
* ``-f``, ``--fsync``: require fsync after every SQLite transaction is committed. By default synchronous writes are disabled for performance.
* ``-j``, ``--journal-mode``: specify SQLite journal-mode. Default is ``wal`` (recommended).
* ``-l``, ``--logfile``: configure file for log output.
* ``-m``, ``--max-request-size``: maximum size of request body in bytes. Default is 64MB (67108864 bytes).

.. _config-file:

Python Configuration File
-------------------------

For more control, you can override certain settings and configuration values by specifying them in a Python module to use as a configuration file.

The following options can be overridden:

* ``AUTHENTICATION`` (same as ``-k`` or ``--api-key``).
* ``DATABASE``, the path to the SQLite database file containing the search index. This file will be created if it does not exist.
* ``DEBUG`` (same as ``-d`` or ``--debug``).
* ``HOST`` (same as ``-H`` or ``--host``).
* ``PAGINATE_BY`` (same as ``--paginate-by``).
* ``PORT`` (same as ``-p`` or ``--port``).
* ``STEM`` (same as ``-s`` or ``--stem``).
* ``SQLITE_PRAGMAS``, a list of 2-tuples specifying SQLite pragmas to set on the database connection (e.g. ``[('journal_mode', 'wal'), ('cache_size', -65536)]``).
* ``MAX_CONTENT_LENGTH``, maximum request body size in bytes (same as ``-m`` or ``--max-request-size``).

.. note::
    Options specified on the command-line will override any options specified
    in the configuration file.

Example configuration file:

.. code-block:: python

    # search_config.py
    AUTHENTICATION = 'my-secret-key'
    DATABASE = 'my_search.db'
    HOST = '0.0.0.0'
    PORT = 1234
    STEM = 'porter'

Example of running Scout with the above config file. Note that since we
specified the database in the config file, we do not need to pass one in on the
command-line.

.. code-block:: console

    $ scout -c search_config.py

You can also specify the configuration file using the ``SCOUT_CONFIG`` environment variable:

.. code-block:: console

    $ SCOUT_CONFIG=search_config.py scout
