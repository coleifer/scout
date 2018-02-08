.. Scout documentation master file, created by
   sphinx-quickstart on Sat Mar 28 11:51:29 2015.
   You can adapt this file completely to your liking, but it should at least
   contain the root `toctree` directive.

scout
=====

.. image:: http://media.charlesleifer.com/blog/photos/scout-logo.png

**scout** is a RESTful search server written in Python with a focus on using
lightweight components:

* search powered by `sqlite's full-text search extension <http://sqlite.org/fts3.html>`_
* database access coordinated using `peewee ORM <http://docs.peewee-orm.com/>`_
* web application built with `flask <http://flask.pocoo.org>`_ framework

Scout aims to be a lightweight, RESTful search server in the spirit of
[ElasticSearch](https://www.elastic.co), powered by the SQLite full-text search
extension. In addition to search, Scout can be used as a document database,
supporting complex filtering operations. Arbitrary files can be attached to
documents and downloaded through the REST API.

Scout is simple to use, simple to deploy and *just works*.

Features
--------

* multiple search indexes present in a single database.
* restful design for easy indexing and searching.
* simple key-based authentication (optional).
* lightweight, low resource utilization, minimal setup required.
* store search content and arbitrary metadata.
* attach files or BLOBs to indexed documents.
* multiple result ranking algorithms, porter stemmer.
* besides full-text search, perform complex filtering based on metadata values.
* comprehensive unit-tests.
* supports SQLite `FTS4 <http://sqlite.org/fts3.html>`_.

named in honor of the best dog ever,

.. image:: http://media.charlesleifer.com/blog/photos/p1473037171.1.JPG

Table of contents
-----------------

Contents:

.. toctree::
   :maxdepth: 2
   :glob:

   installation
   server
   client
   deployment
   hacks


Indices and tables
==================

* :ref:`genindex`
* :ref:`modindex`
* :ref:`search`

