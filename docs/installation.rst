.. _installation:

Installing and Testing
======================

Most users will want to simply install the latest version, hosted on PyPI:

.. code-block:: console

    pip install scout


Installing with git
-------------------

The project is hosted at https://github.com/coleifer/scout and can be installed
using git:

.. code-block:: console

    git clone https://github.com/coleifer/scout.git
    cd scout
    pip install .

Dependencies
------------

Scout has the following Python dependencies:

* `Flask <https://flask.palletsproject.com/>`_
* `Peewee <https://docs.peewee-orm.com/>`_

If you installed Scout using ``pip`` then the dependencies will have
automatically been installed for you. Otherwise be sure to install ``flask``
and ``peewee``.

Scout also depends on SQLite and the SQLite **FTS5** full-text search extension.
SQLite is installed by default on most operating systems, and is generally
compiled with FTS5 support (available since SQLite 3.9.0, released 2015), so
typically no additional installation is necessary. You can verify FTS5 support
by running:

.. code-block:: console

    python -c "import sqlite3; sqlite3.connect(':memory:').execute('CREATE VIRTUAL TABLE t USING fts5(x)')"

If this command fails, your SQLite build does not include FTS5 and you will
need to install or compile a version that does.

Optional dependencies
^^^^^^^^^^^^^^^^^^^^^

* `requests <https://docs.python-requests.org/>`_ -- if installed, the :ref:`Scout client <client>`
  will use ``requests`` for file uploads instead of manually constructing multipart
  requests with ``urllib``. This is recommended for reliability.
* `gevent <http://www.gevent.org/>`_ -- required if you want to use the built-in
  production WSGI server (``scout_wsgi``). See :ref:`deployment` for details.

Running tests
-------------

You can test your installation by running the test suite.

.. code-block:: console

    python runtests.py
