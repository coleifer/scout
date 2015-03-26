![](http://media.charlesleifer.com/blog/photos/scout.png)

scout is a RESTful search server written in Python. The search is powered by [SQLite's full-text search extension](http://sqlite.org/fts3.html), and the web application utilizes the [Flask](http://flask.pocoo.org) framework.

Features:

* Multiple search indexes present in a single database.
* RESTful design for easy indexing and searching.
* Simple key-based authentication (optional).
* Lightweight, low resource utilization, minimal setup required.
* Store search content and arbitrary metadata.
* Multiple result ranking algorithms, porter stemmer.
* Comprehensive unit-tests.

## Installation

Scout can be installed from PyPI using `pip` or from source using `git`. Should you install from PyPI you will run the latest version, whereas installing from `git` ensures you have the latest changes.

Installation using pip:

```console
$ pip install scout
```

You can also install the latest `master` branch using pip:

```console
$ pip install -e git+https://github.com/coleifer/scout.git#egg=scout
```

If you wish to install from source, first clone the code and run `setup.py install`:

```console
$ git clone https://github.com/coleifer/scout.git
$ cd scout/
$ python setup.py install
```

Using either of the above methods will also ensure the project's Python dependencies are installed: [flask](http://flask.pocoo.org) and [peewee](http://docs.peewee-orm.com).

### Dependencies

Scout depends on SQLite compiled with full-text search (default on most systems) and two Python libraries, `peewee` and `flask`. If you installed using `pip` or `python setup.py install` then the Python dependencies should have been installed automatically.

To manually install the Python dependencies, you can use `pip`:

```console
$ pip install flask peewee
```

## Getting started

To get started with Scout, you can simply run it from the command line and specify the path to a SQLite database file which will act as your search index. If the database does not exist, it will be created.

```console
$ python scout.py my_search_index.db
 * Running on http://127.0.0.1:8000/ (Press CTRL+C to quit)
```

This will run Scout locally on port 8000 using the Werkzeug multi-threaded WSGI server. The werkzeug server is perfect for getting started and small deployments. You can find examples of using high performance WSGI servers in the [deployment section](#user-content-deployment).

## API endpoints

There are three main concepts in Scout:

* Indexes
* Documents
* Metadata

*Indexes* have a name and may contain any number of documents.

*Documents* have content, which is indexed for search, and may be associated with any number of indexes.

Documents also can have *metadata*, arbitrary key/value pairs.

For example a blog might have a single index containing documents for each post. The document metadata might contain the ID of the entry, or the entry's title and URL for easy link generation.

A news site might have an index for articles, an index for local events, and a "master" index containing both.

### Index list: "/"

The index list endpoint returns the list of indexes and the number of documents contained within each. The list is not paginated and will display all available indexes. New indexes can be created by POST-ing a `name` to this URL.

Example `GET` request and response:

```console
$ curl localhost:8000/
```

Response:

```json
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
```

Example `POST` request and response:

```console
$ curl -H "Content-Type: application/json" -d '{"name": "test-index"}' localhost:8000/
```

Response:

```json
{
  "documents": [],
  "id": 3,
  "name": "test-index",
  "page": 1,
  "pages": 0
}
```

The `POST` response corresponds to the serialized index detail for the newly-created index.

### Index detail: "/:index-name/"

The index detail returns the name and ID of the index, as well as a paginated list of documents associated with the index. The index can be re-named by POSTing a `name` to this URL.

To paginate the documents, you can append `?page=X` to the URL.

Example `GET` request and response.

```console
$ curl localhost:8000/test-index/
```

Response:

```json
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
```

`POST` requests update the `name` of the index, and like the *index_list* view, accept a `name` parameter. For example request and response, see the above section on creating a new index.

`DELETE` requests will delete the index, but all documents will be preserved in the database.

Example of deleting an index:

```console
$ curl -X DELETE localhost:8000/photos/
```

Response:

```json
{"success": true}
```

### Index search: "/:index-name/search/"

Perform a search of documents associated with the given index. Results are returned as a paginated list of documents.

Search queries are placed in the `q` GET parameter. You can also filter on document metadata by passing arbitrary key/value pairs corresponding to the metadata you wish to filter by. Check out the [SQLite FTS query documentation](http://sqlite.org/fts3.html#section_3) for example search queries and an overview of search capabilities.

Parameters:

* `q`: contains the search query.
* `page`: the page number of results to display. If not present, the first page will be displayed.
* `ranking`: the ranking algorithm to use for scoring the entries. By default the `simple` method will be used, but if you are using a newer version of SQLite that supports *FTS4*, you can also use the [bm25 algorithm](http://en.wikipedia.org/wiki/Okapi_BM25).
    * `simple` (default): use a simple, efficient ranking algorithm.
    * `bm25`: use the Okapi BM25 algorithm. This is only available if your version of SQLite supports *FTS4*.
* arbitrary key/value pairs: used to match document metadata. Only documents whose metadata matches the key/value pairs will be included.

Example search:

```console
$ curl "localhost:8000/test-index/search/?q=huey+OR+mickey"
```

Response:

```json
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
```

We can also search using metadata. We'll use the same query as above, but also include `&is_kitty=yes`.

```console
$ curl "localhost:8000/test-index/search/?q=huey+OR+mickey&is_kitty=yes"
```

Response:

```json
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
```

### Document list: "/documents/"

The document list endpoint returns a paginated list of all documents, regardless of index. New documents are indexed by `POST`-ing the content, index(es) and optional metadata.

`POST` requests should have the following parameters:

* `content` (required): the document content.
* `index` or `indexes` (required): the name(s) of the index(es) the document should be associated with.
* `metadata` (optional): arbitrary key/value pairs.

Example `GET` request and response:

```console
$ curl localhost:8000/documents/
```

Response (truncated):

```json
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
```

Example `POST` request creating a new document:

```console
$ curl \
    -H "Content-Type: application/json" \
    -d '{"content": "New document", "indexes": ["test-index"]}' \
    http://localhost:8000/documents/
```

Response on creating a new document:

```json
{
  "content": "New document",
  "id": 121,
  "indexes": [
    "test-index"
  ],
  "metadata": {}
}
```

### Document detail: "/documents/:document-id/"

The document detail endpoint returns document content, indexes, and metadata. Documents can be updated or deleted by using `POST` and `DELETE` requests, respectively. When updating a document, you can update the `content`, `index(es)`, and/or `metadata`. If you choose to update metadata, all current metadata for the document will be removed, so it's really more of a "replace" than an "update".

Example `GET` request and response:

```console
$ curl localhost:8000/documents/118/
```

Response:

```json
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
```

Here is an example of updating the content and indexes using a `POST` request:

```console
$ curl \
    -H "Content-Type: application/json" \
    -d '{"content": "test zaizee updated", "indexes": ["test-index", "blog"]}' \
    http://localhost:8000/documents/118/
```

Response:

```json
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
```

`DELETE` requests can be used to completely remove a document.

Example `DELETE` request and response:

```console
$ curl -X DELETE localhost:8000/documents/121/
```

Response:

```json
{"success": true}
```

### Example of using Authentication

Scout provides very basic key-based authentication. You can specify a single, global key which must be specified in order to access the API.

To specify the API key, you can pass it in on the command-line or specify it in a configuration file (described below).

Example of running scout with an API key:

```console
$ python scout.py -k secret /path/to/search.db
```

If we try to access the API without specifying the key, we get a `401` response stating *Invalid API key*:

```console
$ curl localhost:8000/
Invalid API key
```

We can specify the key as a header:

```console
$ curl -H "key: secret" localhost:8000/
{
  "indexes": []
}
```

Alternatively, the key can be specified as a `GET` argument:

```console
$ curl localhost:8000/?key=secret
{
  "indexes": []
}
```

## Configuration and Command-line Options

The easiest way to run Scout is to invoke it directly from the command-line, passing the database in as the last argument:

```console
$ python scout.py /path/to/search.db
```

The database file can also be specified using the `SCOUT_DATABASE` environment variable:

```console
$ SCOUT_DATABASE=/path/to/search.db python scout.py
```

Scout supports a handful of configuration options to control it's behavior when run from the command-line. The following table describes these options:

* `-H`, `--host`: set the hostname to listen on. Defaults to `127.0.0.1`
* `-p`, `--port`: set the port to listen on. Defaults to `8000`.
* `-s`, `--stem`: set the stemming algorithm. Valid options are `simple` and `porter`. Defaults to `porter` stemmer. This option only will be in effect when a new database is created, as the stemming algorithm is part of the table definition.
* `-k`, `--api-key`: set the API key required to access Scout. By default no authentication is required.
* `--paginate-by`: set the number of documents displayed per page of results. Default is 50.
* `-c`, `--config`: set the configuration file (a Python module). See the [configuration options](#user-content-configuration) for available settings.
* `--paginate-by`: set the number of documents displayed per page of results. Defaults to 50.
* `-d`, `--debug`: boolean flag to run Scout in debug mode.

### Python Configuration File

For more control, you can override certain settings and configuration values by specifying them in a Python module to use as a configuration file.

The following options can be overridden:

* `AUTHENTICATION` (same as `-k` or `--api-key`).
* `DATABASE`, the path to the SQLite database file containing the search index. This file will be created if it does not exist.
* `DEBUG` (same as `-d` or `--debug`).
* `HOST` (same as `-H` or `--host`).
* `PAGINATE_BY` (same as `--paginate-by`).
* `PORT` (same as `-p` or `--port`).
* `SECRET_KEY`, which is used internally by Flask to encrypt client-side session data stored in cookies.
* `STEM` (same as `-s` or `--stem`).

**Note**: options specified on the command-line will override any options specified in the configuration file.

Example configuration file:

```python
# search_config.py
AUTHENTICATION = 'my-secret-key'
DATABASE = 'my_search.db'
HOST = '0.0.0.0'
PORT = 1234
STEM = 'porter'
```

Example of running Scout with the above config file. Note that since we specified the database in the config file, we do not need to pass one in on the command-line.

```console
$ python scout.py -c search_config.py
```

You can also specify the configuration file using the `SCOUT_CONFIG` environment variable:

```console
$ SCOUT_CONFIG=search_config.py python scout.py
```

## Deployment

When scout is run from the command-line, it will use the multi-threaded Werkzeug WSGI server. While this server is perfect for development and small installations, you may want to use a high-performance WSGI server to deploy Scout.

Scout provides a WSGI app, so you can use any WSGI server for deployment. Popular choices are:

* [Gevent](http://www.gevent.org/)
* [Gunicorn](http://gunicorn.org/)
* [uWSGI](https://uwsgi-docs.readthedocs.org/en/latest/)

The Flask documentation also provides a list of popular WSGI servers and how to integrate them with Flask apps. Since Scout is a Flask application, all of these examples should work with minimal modification:

http://flask.pocoo.org/docs/0.10/deploying/wsgi-standalone/

### Gevent

Here is an example wrapper script for running Scout using the Gevent WSGI server:

```python
from gevent import monkey
monkey.patch_all()

from gevent.wsgi import WSGIServer
from scout import app, initialize_database

# Initialize the search index and create the tables if they don't exist.
initialize_database('/path/to/search-index.db')

# Run the WSGI server on localhost:8000.
WSGIServer(('127.0.0.1', 8000), app).serve_forever()
```

You could then run the wrapper script using a tool like [supervisord](http://supervisord.org/) or another process manager.

### Gunicorn

Here is an example wrapper script for running Scout using Gunicorn.

```python
# Wrapper script to initialize database.
from scout import app, initialize_database
initialize_database('/path/to/search-index.db')
```

Here is how to run gunicorn using the above wrapper script:

```console
$ gunicorn --workers=4 --bind=127.0.0.1:8000 --worker-class=gevent wrapper:app
```

### uWSGI

Here is an example wrapper script for uWSGI.

```python
# Wrapper script to initialize database.
from scout import app, initialize_database
initialize_database('/path/to/search-index.db')
```

Here is how you might run using the above wrapper script:

```console
$ uwsgi --http :8000 --wsgi-file wrapper.py --master --processes 4 --threads 2
```

It is common to run uWSGI behind Nginx. For more information [check out the uWSGI docs](http://uwsgi-docs.readthedocs.org/en/latest/WSGIquickstart.html).
