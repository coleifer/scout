.. _server:

Scout Server
============

Scout server is a RESTful Flask application that provides endpoints for managing indexes, documents, metadata and performing searches. To get started with Scout, you can simply run the server from the command-line and specify the path to a SQLite database file which will act as the search index.

.. note:: If the database does not exist, it will be created.

.. code-block:: console

    $ python scout.py my_search_index.db
     * Running on http://127.0.0.1:8000/ (Press CTRL+C to quit)

This will run Scout locally on port 8000 using the Werkzeug multi-threaded WSGI server. The werkzeug server is perfect for getting started and small deployments. You can find examples of using high performance WSGI servers in the :ref:`deployment section <deployment>`.

API Endpoints
-------------

There are three main concepts in Scout:

* Indexes
* Documents
* Metadata

*Indexes* have a name and may contain any number of documents.

*Documents* have content, which is indexed for search, and may be associated with any number of indexes.

Documents also can have *metadata*, arbitrary key/value pairs. Besides full-text search, Scout allows complex filtering based on metadata values. So in addition to storing useful things alongside your documents, you can also use metadata to provide an additional layer of filtering.

For example a blog might have an index to store every post, and a separate index to store comments. The blog entry metadata might contain the ID of the entry, or the entry's title and URL for easy link generation. The comment metadata might store the comment's timestamp as metadata to allow searching for comments made in a specific time-frame.

A news site might have an index for articles, an index for local events, and a "master" index containing both.

Index list: "/"
---------------

The index list endpoint returns the list of indexes and the number of documents contained within each. The list is not paginated and will display all available indexes. New indexes can be created by POST-ing a name to this URL.

Example GET request and response:

.. code-block:: console

    $ curl localhost:8000/

Response:

.. code-block:: javascript

    {
      "indexes": [
        {
          "documents": 114,
          "id": 1,
          "name": "blog"
        },
        {
          "documents": 36,
          "id": 2,
          "name": "photos"
        }
      ]
    }

Example POST request and response:

.. code-block:: console

    $ curl -H "Content-Type: application/json" -d '{"name": "test-index"}' localhost:8000/

Response:

.. code-block:: javascript

    {
      "documents": [],
      "id": 3,
      "name": "test-index",
      "page": 1,
      "pages": 0
    }

The POST response corresponds to the serialized index detail for the newly-created index.

Index detail: "/:index-name/"
-----------------------------

The index detail returns the name and ID of the index, as well as a paginated list of documents associated with the index. The index can be re-named by POSTing a ``name`` to this URL.

To paginate the documents, you can append ``?page=X`` to the URL.

Example ``GET`` request and response.

.. code-block:: console

    $ curl localhost:8000/test-index/

Response:

.. code-block:: javascript

    {
      "documents": [
        {
          "content": "test charlie document",
          "id": 115,
          "indexes": [
            "test-index"
          ],
          "metadata": {
            "is_kitty": "no"
          }
        },
        {
          "content": "test huey document",
          "id": 116,
          "indexes": [
            "test-index"
          ],
          "metadata": {
            "is_kitty": "yes"
          }
        },
        {
          "content": "test mickey document",
          "id": 117,
          "indexes": [
            "test-index"
          ],
          "metadata": {
            "is_kitty": "no"
          }
        }
      ],
      "id": 3,
      "name": "test-index",
      "page": 1,
      "pages": 1
    }

``POST`` requests update the ``name`` of the index, and like the *index_list* view, accept a ``name`` parameter. For example request and response, see the above section on creating a new index.

``DELETE`` requests will delete the index, but all documents will be preserved in the database.

Example of deleting an index:

.. code-block:: console

    $ curl -X DELETE localhost:8000/photos/

Response:

.. code-block:: javascript

    {"success": true}

Index search: "/:index-name/search/"
------------------------------------

Perform a search of documents associated with the given index. Results are returned as a paginated list of documents.

Search queries are placed in the q GET parameter. You can also filter on document metadata by passing arbitrary key/value pairs corresponding to the metadata you wish to filter by. Check out the `SQLite FTS query documentation <http://sqlite.org/fts3.html#section_3>`_ for example search queries and an overview of search capabilities.

Parameters:

* ``q``: contains the search query.
* ``page``: the page number of results to display. If not present, the first page will be displayed.
* ``ranking``: the ranking algorithm to use for scoring the entries. By default the simple method will be used, but if you are using a newer version of SQLite that supports FTS4, you can also use the bm25 algorithm.

  * ``simple`` (default): use a simple, efficient ranking algorithm.
  * ``bm25``: use the `Okapi BM25 algorithm <http://en.wikipedia.org/wiki/Okapi_BM25>`_. This is only available if your version of SQLite supports FTS4.

* Arbitrary key/value pairs: used to match document *metadata*. Only documents whose metadata matches the key/value pairs will be included.
* Metadata searches match on equality by default, but other types of expressions can be formed by appending ``'__<operation>'`` to the metadata key. For more information, see :ref:`the advance query section <advanced-query>`.

Example search:

.. code-block:: console

    $ curl "localhost:8000/test-index/search/?q=huey+OR+mickey"

Response:

.. code-block:: javascript

    {
      "documents": [
        {
          "content": "test mickey document",
          "id": 117,
          "indexes": [
            "test-index"
          ],
          "metadata": {
            "is_kitty": "no"
          },
          "score": 0.16666666666666666
        },
        {
          "content": "test huey document",
          "id": 116,
          "indexes": [
            "test-index"
          ],
          "metadata": {
            "is_kitty": "yes"
          },
          "score": 0.022727272727272728
        }
      ],
      "page": 1,
      "pages": 1
    }

We can also search using metadata. We'll use the same query as above, but also include ``&is_kitty=yes``.

.. code-block:: console

    $ curl "localhost:8000/test-index/search/?q=huey+OR+mickey&is_kitty=yes"

Response:

.. code-block:: javascript

    {
      "documents": [
        {
          "content": "test huey document",
          "id": 116,
          "indexes": [
            "test-index"
          ],
          "metadata": {
            "is_kitty": "yes"
          },
          "score": 0.022727272727272728
        }
      ],
      "page": 1,
      "pages": 1
    }

.. _advanced-query:

Using advanced query filters
----------------------------

Suppose we have an index that contains all of our contacts. The search content consists of the person's name, address, city, and state. We also have stored quite a bit of metadata about each person. A person record might look like this:

.. code-block:: javascript

    {'content': "Huey Leifer 123 Main Street Lawrence KS 66044"}

The metadata for this record consists of the following:

.. code-block:: javascript

    {'metadata': {
      'dob': '2010-06-01',
      'city': 'Lawrence',
      'state': 'KS',
    }}

Let's say we want to search our index for all people who were born in 1983. We could use the following URL:

``/contacts-index/search/?q=*&dob__ge=1983-01-01&dob__lt=1984-01-01``

To search for all people who live in Lawrence or Topeka, KS we could use the following URL:

``/contacts-index/search/?q=*&city__in=Lawrence,Topeka&state=KS``

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

.. note:: In these examples we're using the asterisk ("``*``") to return all records. This option is disabled by default, but you can enable it by specifying ``STAR_ALL=True`` in your :ref:`config file <config-file>`.


Document list: "/documents/"
----------------------------

The document list endpoint returns a paginated list of all documents, regardless of index. New documents are indexed by ``POST``-ing the content, index(es) and optional metadata.

``POST`` requests should have the following parameters:

* ``content`` (required): the document content.
* ``index`` or ``indexes`` (required): the name(s) of the index(es) the document should be associated with.
* ``metadata`` (optional): arbitrary key/value pairs.

Example GET request and response:

.. code-block:: console

    $ curl localhost:8000/documents/

Response (truncated):

.. code-block:: javascript

    {
      "documents": [
        {
          "content": "test charlie document",
          "id": 115,
          "indexes": [
            "test-index"
          ],
          "metadata": {
            "is_kitty": "no"
          }
        },
        {
          "content": "test huey document",
          "id": 116,
          "indexes": [
            "test-index"
          ],
          "metadata": {
            "is_kitty": "yes"
          }
        },
        ...
      ],
      "page": 1,
      "pages": 3
    }

Example ``POST`` request creating a new document:

.. code-block:: console

    $ curl \
        -H "Content-Type: application/json" \
        -d '{"content": "New document", "indexes": ["test-index"]}' \
        http://localhost:8000/documents/

Response on creating a new document:

.. code-block:: javascript

    {
      "content": "New document",
      "id": 121,
      "indexes": [
        "test-index"
      ],
      "metadata": {}
    }

Document detail: "/documents/:document-id/"
-------------------------------------------

The document detail endpoint returns document content, indexes, and metadata. Documents can be updated or deleted by using ``POST`` and ``DELETE`` requests, respectively. When updating a document, you can update the ``content``, ``index(es)``, and/or ``metadata``.

.. warning:: If you choose to update metadata, all current metadata for the document will be removed, so it's really more of a "replace" than an "update".

Example ``GET`` request and response:

.. code-block:: console

    $ curl localhost:8000/documents/118/

Response:

.. code-block:: javascript

    {
      "content": "test zaizee document",
      "id": 118,
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

Response:

.. code-block:: javascript

    {
      "content": "test zaizee updated",
      "id": 118,
      "indexes": [
        "blog",
        "test-index"
      ],
      "metadata": {
        "is_kitty": "yes"
      }
    }

``DELETE`` requests can be used to completely remove a document.

Example ``DELETE`` request and response:

.. code-block:: console

  $ curl -X DELETE localhost:8000/documents/121/

Response:

.. code-block:: javascript

    {"success": true}

Example of using Authentication
-------------------------------

Scout provides very basic key-based authentication. You can specify a single, global key which must be specified in order to access the API.

To specify the API key, you can pass it in on the command-line or specify it in a configuration file (described below).

Example of running scout with an API key:

.. code-block:: console

    $ python scout.py -k secret /path/to/search.db

If we try to access the API without specifying the key, we get a ``401`` response stating Invalid API key:

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

Configuration and Command-Line Options
--------------------------------------

The easiest way to run Scout is to invoke it directly from the command-line, passing the database in as the last argument:

.. code-block:: console

    $ python scout.py /path/to/search.db

The database file can also be specified using the SCOUT_DATABASE environment variable:

.. code-block:: console

    $ SCOUT_DATABASE=/path/to/search.db python scout.py

Scout supports a handful of configuration options to control it's behavior when run from the command-line. The following table describes these options:

* ``-H``, ``--host``: set the hostname to listen on. Defaults to ``127.0.0.1``
* ``-p``, ``--port``: set the port to listen on. Defaults to ``8000``.
* ``-s``, ``--stem``: set the stemming algorithm. Valid options are ``simple`` and ``porter``. Defaults to ``porter`` stemmer. This option only will be in effect when a new database is created, as the stemming algorithm is part of the table definition.
* ``-k``, ``--api-key``: set the API key required to access Scout. By default no authentication is required.
* ``--paginate-by``: set the number of documents displayed per page of results. Default is 50.
* ``-c``, ``--config``: set the configuration file (a Python module). See the configuration options for available settings.
* ``--paginate-by``: set the number of documents displayed per page of results. Defaults to 50.
* ``-d``, ``--debug``: boolean flag to run Scout in debug mode.

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
* ``SEARCH_EXTENSION``, manually specify the FTS extension version. Scout defaults to the newest version available based on your installed SQLite, but you can force an older version with this option.
* ``SECRET_KEY``, which is used internally by Flask to encrypt client-side session data stored in cookies.
* ``STAR_ALL``, when the search term is "*", return all records. This option is disabled by default.
* ``STEM`` (same as ``-s`` or ``--stem``).

.. note:: Options specified on the command-line will override any options specified in the configuration file.

Example configuration file:

.. code-block:: python

    # search_config.py
    AUTHENTICATION = 'my-secret-key'
    DATABASE = 'my_search.db'
    HOST = '0.0.0.0'
    PORT = 1234
    STEM = 'porter'

Example of running Scout with the above config file. Note that since we specified the database in the config file, we do not need to pass one in on the command-line.

.. code-block:: console

    $ python scout.py -c search_config.py

You can also specify the configuration file using the ``SCOUT_CONFIG`` environment variable:

.. code-block:: console

    $ SCOUT_CONFIG=search_config.py python scout.py
