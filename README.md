![](http://media.charlesleifer.com/blog/photos/scout-logo.png)

**scout** is a restful search server written in python with a focus on using
lightweight components:

* search powered by [sqlite's full-text search extension](https://sqlite.org/fts5.html)
* database access coordinated using [peewee ORM](https://docs.peewee-orm.com/)
* web application built with [flask](https://flask.palletsprojects.com/) framework

Scout aims to be a lightweight, RESTful search server in the spirit of
[ElasticSearch](https://www.elastic.co), powered by the SQLite full-text search
extension. In addition to search, Scout can be used as a document database,
supporting complex filtering operations. Arbitrary files can be attached to
documents and downloaded through the REST API.

Scout is simple to use, simple to deploy and *just works*.

Features:

* multiple search indexes present in a single database.
* restful design for easy indexing and searching.
* simple key-based authentication (optional).
* lightweight, low resource utilization, minimal setup required.
* store search content and arbitrary metadata.
* attach files or BLOBs to indexed documents.
* BM25 result ranking, porter stemmer.
* filtering based on metadata values.
* attachment search and filtering.
* powered by SQLite [FTS5](http://sqlite.org/fts5.html).
* [documentation hosted on rtd](https://scout.readthedocs.io/en/latest/).

## Installation

Scout requires **Python 3.8+** and a version of SQLite compiled with the
**FTS5** extension (included by default since SQLite 3.9.0, released 2015). You
can verify FTS5 support by running:

```console
python -c "import sqlite3; sqlite3.connect(':memory:').execute('CREATE VIRTUAL TABLE t USING fts5(x)')"
```

If this command fails, your SQLite build does not include FTS5 and you will
need to install or compile a version that does.

Scout can be installed from PyPI using `pip` or from source using `git`. Should
you install from PyPI you will run the latest version, whereas installing from
`git` ensures you have the latest changes.

Alternatively, you can run `scout` using [docker](https://www.docker.com/) and
the provided [Dockerfile](https://github.com/coleifer/scout/blob/master/docker/Dockerfile).

Installation using pip:

```console
pip install scout
```

You can also install the latest `master` branch using pip:

```console
pip install -e git+https://github.com/coleifer/scout.git#egg=scout
```

If you wish to install from source, first clone the code and run `setup.py install`:

```console
git clone https://github.com/coleifer/scout.git
cd scout/
pip install .
```

Using either of the above methods will also ensure the project's Python
dependencies are installed: [flask](https://flask.palletsprojects.com/) and
[peewee](https://docs.peewee-orm.com).

[Check out the documentation](https://scout.readthedocs.io/en/latest/) for more information about the project.

## Running scout

If you installed using `pip`, you should be able to simply run:

```console
scout /path/to/search-index.db
```

If you've just got a copy of the source code, you can run:

```console
python scout/ /path/to/search-index.db
```

### Production-ready server

Scout comes with a production-ready WSGI server powered by gevent. To use this
server instead, you can run:

```console
scout_wsgi /path/to/search-index.db
```

## Docker

The Docker image runs Scout on port **9004** (rather than the default 8000)
using the built-in gevent WSGI server. The database path defaults to
`/data/search-index.db` and is controlled by the `SCOUT_DATABASE` environment
variable. The `/data` directory is declared as a volume.

To run scout using docker, you can use the provided Dockerfile or simply pull
the `coleifer/scout` image:

```console
docker run -d \
    --name scout \
    -p 9004:9004 \
    -v /path/to/data:/data \
    ghcr.io/coleifer/scout:latest
# scout is now running on localhost:9004
```

> **Note:** Always mount a volume to `/data` (as shown above) to persist your
> search index across container restarts.

Build your own image locally and run it:

```console
cd scout/docker
docker build -t scout .
docker run -d \
    --name my-scout-server \
    -p 9004:9004 \
    -v /path/to/data:/data \
    scout
```

### Overriding settings

You can pass additional Scout CLI flags by appending them to `docker run`:

```console
docker run -d \
    -p 9004:9004 \
    -v /path/to/data:/data \
    ghcr.io/coleifer/scout:latest \
    -k my-secret-api-key \
    --paginate-by 100
```

You can override the database location with the `SCOUT_DATABASE` environment
variable:

```console
docker run -d \
    -p 9004:9004 \
    -e SCOUT_DATABASE=/data/my-index.db \
    -v /path/to/data:/data \
    ghcr.io/coleifer/scout:latest
```

### Migrating an existing database

If you are upgrading from an older Scout version that used FTS4, you can run
the migration inside the container:

```console
docker run --rm \
    -v /path/to/data:/data \
    ghcr.io/coleifer/scout:latest --migrate
```
