.. _deployment:

Deployment
==========

When Scout is run from the command-line, it will use the multi-threaded
Werkzeug WSGI server. While this server is perfect for development and small
installations, you may want to use a high-performance WSGI server to deploy
Scout.

Scout provides a WSGI app, so you can use any WSGI server for deployment.
Popular choices are:

* `Gevent <http://www.gevent.org/>`_
* `Gunicorn <http://gunicorn.org/>`_
* `uWSGI <https://uwsgi-docs.readthedocs.io/en/latest/>`_

The Flask documentation also provides a list of popular WSGI servers and how to
integrate them with Flask apps. Since Scout is a Flask application, all of
these examples should work with minimal modification:

https://flask.palletsprojects.com/en/latest/deploying/

Environment variables
---------------------

The following environment variables can be used to configure Scout in any deployment scenario:

* ``SCOUT_DATABASE``: path to the SQLite database file. Equivalent to passing
  the database path as a command-line argument.
* ``SCOUT_CONFIG``: path to a Python configuration file. Equivalent to
  the ``-c`` / ``--config`` command-line option. See :ref:`config-file` for details.
* ``SCOUT_MAX_CONNECTIONS``: maximum number of concurrent connections for the
  built-in gevent server. Defaults to 128. Only applies when using ``scout_wsgi``.

Gevent
------

Scout comes with a production-ready gevent WSGI server. To run this server:

.. code-block:: console

    $ scout_wsgi /path/to/database.db

The built-in gevent server uses a connection pool to limit concurrency. You can
control the pool size via the ``SCOUT_MAX_CONNECTIONS`` environment variable:

.. code-block:: console

    $ SCOUT_MAX_CONNECTIONS=256 scout_wsgi /path/to/database.db

If you wish to have more control over the server implementation, this example
wrapper script can get you started:

.. code-block:: python

    from gevent import monkey
    monkey.patch_all()

    from gevent.pywsgi import WSGIServer
    from scout.server import parse_options

    # Parse command-line options and return a Flask app.
    app = parse_options()

    # Run the WSGI server on localhost:8000.
    WSGIServer(('127.0.0.1', 8000), app).serve_forever()

You could then run the wrapper script using a tool like `supervisord <http://supervisord.org/>`_
or another process manager.

Gunicorn
--------

Here is an example wrapper script for running Scout using Gunicorn.

.. code-block:: python

    # Wrapper script to initialize database.
    from scout.server import parse_options
    app = parse_options()

Here is how to run gunicorn using the above wrapper script:

.. code-block:: console

    $ gunicorn --workers=4 --bind=127.0.0.1:8000 --worker-class=gevent wrapper:app

.. note::
    The ``--worker-class=gevent`` option requires `gevent <http://www.gevent.org/>`_
    to be installed (``pip install gevent``). You can omit this flag to use
    Gunicorn's default synchronous workers instead.

uWSGI
-----

Here is an example wrapper script for uWSGI.

.. code-block:: python

    # Wrapper script to initialize database.
    from scout.server import parse_options
    app = parse_options()

Here is how you might run using the above wrapper script:

.. code-block:: console

    $ uwsgi --http :8000 --wsgi-file wrapper.py --master --processes 4 --threads 2

It is common to run uWSGI behind Nginx. For more information `check out the uWSGI docs <https://uwsgi-docs.readthedocs.io/en/latest/WSGIquickstart.html>`_.
