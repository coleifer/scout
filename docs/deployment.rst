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

Scout includes a ``Dockerfile`` for containerized deployments. The default
image uses the built-in gevent server on port 9004 with a volume-mounted
database.

Building the image:

.. code-block:: console

    $ docker build -t scout .

Running the container:

.. code-block:: console

    $ docker run -d \
        -p 8000:9004 \
        -v /path/to/data:/data \
        --name scout \
        scout

The database file is stored at ``/data/search-index.db`` inside the container
(controlled by the ``SCOUT_DATABASE`` environment variable). Logs are written
to ``/data/scout.log``.

You can override any Scout option by appending flags to the ``docker run``
command:

.. code-block:: console

    $ docker run -d \
        -p 8000:9004 \
        -v /path/to/data:/data \
        -e SCOUT_DATABASE=/data/my-index.db \
        scout \
        --api-key secret --paginate-by 100

The image includes a health check that polls the index list endpoint every 30
seconds.

To use a custom configuration file, mount it into the container and set the
``SCOUT_CONFIG`` environment variable:

.. code-block:: console

    $ docker run -d \
        -p 8000:9004 \
        -v /path/to/data:/data \
        -v /path/to/config.py:/etc/scout/config.py \
        -e SCOUT_CONFIG=/etc/scout/config.py \
        scout
