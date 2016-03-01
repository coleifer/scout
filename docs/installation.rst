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
    python setup.py install

.. note::
    On some systems you may need to use ``sudo python setup.py install`` to
    install scout system-wide.

Dependencies
------------

Scout has the following Python dependencies:

* `Flask <http://flask.pocoo.org>`_
* `Peewee <http://docs.peewee-orm.com>`_

If you installed Scout using ``pip`` then the dependencies will have automatically been installed for you. Otherwise be sure to install ``flask`` and ``peewee``.

Scout also depends on SQLite and the SQLite full-text search extension. SQLite is installed by default on most operating systems, and is generally compiled with FTS, so typically no additional installation is necessary.

If you wish, you can also run Scout using the `gevent <http://www.gevent.org/>`_ WSGI server. This process is described in the :ref:`hacks` document.

Running tests
-------------

You can test your installation by running the test suite.

.. code-block:: console

    python tests.py
