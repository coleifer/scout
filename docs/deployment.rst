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

Docker
------

Scout includes a ``Dockerfile`` for containerized deployments. The Docker image
runs Scout on port **9004** (rather than the default 8000) using the built-in
gevent WSGI server. The database path defaults to ``/data/search-index.db`` and
is controlled by the ``SCOUT_DATABASE`` environment variable. The ``/data``
directory is declared as a volume.

To run Scout using Docker, you can pull the ``coleifer/scout`` image from the
GitHub container registry:

.. code-block:: console

    $ docker run -d \
        --name scout \
        -p 9004:9004 \
        -v /path/to/data:/data \
        ghcr.io/coleifer/scout:latest

.. note::
    Always mount a host directory to ``/data`` (as shown above) to persist your
    search index across container restarts.

You can also build the image locally:

.. code-block:: console

    $ cd scout/docker
    $ docker build -t scout .
    $ docker run -d \
        --name scout \
        -p 9004:9004 \
        -v /path/to/data:/data \
        scout

The database file is stored at ``/data/search-index.db`` inside the container.
Logs are written to ``/data/scout.log``.

Overriding settings
^^^^^^^^^^^^^^^^^^^

You can pass additional Scout CLI flags by appending them to the ``docker run``
command:

.. code-block:: console

    $ docker run -d \
        -p 9004:9004 \
        -v /path/to/data:/data \
        ghcr.io/coleifer/scout:latest \
        -k my-secret-api-key \
        --paginate-by 100

You can override the database location with the ``SCOUT_DATABASE`` environment
variable:

.. code-block:: console

    $ docker run -d \
        -p 9004:9004 \
        -v /path/to/data:/data \
        -e SCOUT_DATABASE=/data/my-index.db \
        ghcr.io/coleifer/scout:latest

To use a custom configuration file, mount it into the container and set the
``SCOUT_CONFIG`` environment variable:

.. code-block:: console

    $ docker run -d \
        -p 9004:9004 \
        -v /path/to/data:/data \
        -v /path/to/config.py:/etc/scout/config.py \
        -e SCOUT_CONFIG=/etc/scout/config.py \
        ghcr.io/coleifer/scout:latest

The image includes a health check that polls the index list endpoint every 30
seconds.

Migrating an existing database
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

If you are upgrading from an older Scout version that used FTS4, you can run
the migration inside the container:

.. code-block:: console

    $ docker run --rm \
        -v /path/to/data:/data \
        ghcr.io/coleifer/scout:latest --migrate
