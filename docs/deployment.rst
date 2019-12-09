.. _deployment:

Deployment
==========

When scout is run from the command-line, it will use the multi-threaded Werkzeug WSGI server. While this server is perfect for development and small installations, you may want to use a high-performance WSGI server to deploy Scout.

Scout provides a WSGI app, so you can use any WSGI server for deployment. Popular choices are:

* `Gevent <http://www.gevent.org/>`_
* `Gunicorn <http://gunicorn.org/>`_
* `uWSGI <https://uwsgi-docs.readthedocs.io/en/latest/>`_

The Flask documentation also provides a list of popular WSGI servers and how to integrate them with Flask apps. Since Scout is a Flask application, all of these examples should work with minimal modification:

http://flask.pocoo.org/docs/0.10/deploying/wsgi-standalone/

Gevent
------

Here is an example wrapper script for running Scout using the Gevent WSGI server:

.. code-block:: python

    from gevent import monkey
    monkey.patch_all()

    from gevent.pywsgi import WSGIServer
    from scout.server import parse_options

    # Parse command-line options and return a Flask app.
    app = parse_options()

    # Run the WSGI server on localhost:8000.
    WSGIServer(('127.0.0.1', 8000), app).serve_forever()

You could then run the wrapper script using a tool like `supervisord <http://supervisord.org/>`_ or another process manager.

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

uWSGI
-----

Here is an example wrapper script for uWSGI.

.. code-block:: python

    # Wrapper script to initialize database.
    from scout import parse_options
    app = parse_options()

Here is how you might run using the above wrapper script:

.. code-block:: console

    $ uwsgi --http :8000 --wsgi-file wrapper.py --master --processes 4 --threads 2

It is common to run uWSGI behind Nginx. For more information `check out the uWSGI docs <https://uwsgi-docs.readthedocs.io/en/latest/WSGIquickstart.html>`_.
