![](http://media.charlesleifer.com/blog/photos/scout-logo.png)

[scout](https://scout.readthedocs.io/en/latest/) is a RESTful search server
written in Python. The search is powered by [SQLite's full-text search extension](http://sqlite.org/fts3.html),
and the web application utilizes the [Flask](http://flask.pocoo.org) framework.

Scout aims to be a lightweight, RESTful search server in the spirit of
[ElasticSearch](https://www.elastic.co), powered by the SQLite full-text search
extension. In addition to search, Scout can be used as a document database,
supporting complex filtering operations. Arbitrary files can be attached to
documents and downloaded through the REST API.

Scout is simple to use, simple to deploy and *just works*.

Features:

* Multiple search indexes present in a single database.
* RESTful design for easy indexing and searching.
* Simple key-based authentication (optional).
* Lightweight, low resource utilization, minimal setup required.
* Store search content and arbitrary metadata.
* Multiple result ranking algorithms, porter stemmer.
* Besides full-text search, perform complex filtering based on metadata values.
* Comprehensive unit-tests.
* Supports SQLite [FTS4](http://sqlite.org/fts3.html).
* [Documentation hosted on ReadTheDocs](https://scout.readthedocs.io/en/latest/).

![](https://api.travis-ci.org/coleifer/scout.svg?branch=master)

## Installation

Scout can be installed from PyPI using `pip` or from source using `git`. Should
you install from PyPI you will run the latest version, whereas installing from
`git` ensures you have the latest changes.

Alternatively, you can run `scout` using [docker](https://www.docker.com/) and
the provided [Dockerfile](https://github.com/coleifer/scout/blob/master/docker/Dockerfile).

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

Using either of the above methods will also ensure the project's Python
dependencies are installed: [flask](http://flask.pocoo.org) and
[peewee](http://docs.peewee-orm.com).

[Check out the documentation](https://scout.readthedocs.io/en/latest/) for more information about the project.

## Running scout

If you installed using `pip`, you should be able to simply run:

```console
$ scout /path/to/search-index.db
```

If you've just got a copy of the source code, you can run:

```console
$ python scout/ /path/to/search-index.db
```

## Docker

To run scout using docker, you can use the provided Dockerfile or simply pull
the `coleifer/scout` image from dockerhub:

```console

$ docker run -it --rm -p 9004:9004 coleifer/scout
# scout is now running on 0.0.0.0:9004
```

Build your own image locally and run it:

```console

$ cd scout/docker
$ docker build -t scout .
$ docker run -d \
    --name my-scout-server \
    -p 9004:9004 \
    -v scout-data:/data \
    scout
```
