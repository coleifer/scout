.. Scout documentation master file, created by
   sphinx-quickstart on Sat Mar 28 11:51:29 2015.
   You can adapt this file completely to your liking, but it should at least
   contain the root `toctree` directive.

scout
=====

.. image:: http://media.charlesleifer.com/blog/photos/scout-logo.png

**scout** is a restful search server written in python with a focus on using
lightweight components:

* search powered by `sqlite's full-text search extension <https://sqlite.org/fts5.html>`_
* database access coordinated using `peewee ORM <https://docs.peewee-orm.com/>`_
* web application built with `flask <https://flask.palletsproject.com/>`_ framework

Scout aims to be a lightweight, RESTful search server in the spirit of
`ElasticSearch <https://www.elastic.co>`_, powered by the SQLite full-text
search extension. In addition to search, Scout can be used as a document
database, supporting complex filtering operations. Arbitrary files can be
attached to documents and downloaded through the REST API.

Scout is simple to use, simple to deploy and *just works*.

Features
--------

* multiple search indexes present in a single database.
* restful design for easy indexing and searching.
* simple key-based authentication (optional).
* lightweight, low resource utilization, minimal setup required.
* store search content and arbitrary metadata.
* attach files or BLOBs to indexed documents.
* BM25 result ranking, porter stemmer.
* besides full-text search, perform complex filtering based on metadata values.
* global attachment search and filtering.
* comprehensive unit-tests.
* powered by SQLite `FTS5 <http://sqlite.org/fts5.html>`_ for full-text search.

Table of contents
-----------------

Contents:

.. toctree::
   :maxdepth: 2
   :glob:

   installation
   server
   client
   search-queries
   example
   deployment
   hacks

named in honor of the best dog ever,

.. image:: http://media.charlesleifer.com/blog/photos/p1473037171.1.JPG

Indices and tables
==================

* :ref:`genindex`
* :ref:`modindex`
* :ref:`search`
