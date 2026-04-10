.. _hacks:

Hacks
=====

In this document you will find some of the hacks users of Scout have come up
with to do novel things.

Most of these techniques involve wrapping the Scout server application with an
additional module. Since Scout server is a normal Python module, and the WSGI
app is just an object within that module, there is no magic needed to extend
the behavior of Scout.

Adding CORS headers
-------------------

To query a Scout index from JavaScript running on a different host, you need to
add CORS headers to each response from the API (`more info on CORS
<https://developer.mozilla.org/en-US/docs/Web/HTTP/Access_control_CORS>`_).

To accomplish this, create a wrapper module that wraps the Scout server Flask
app and implements a special ``after_request`` hook:

.. code-block:: python

    from scout.server import parse_options

    app = parse_options()

    @app.after_request
    def add_cors_header(response):
        response.headers['Access-Control-Allow-Origin'] = 'http://myhost.com'
        response.headers['Access-Control-Allow-Headers'] = 'key,Content-Type'
        response.headers['Access-Control-Allow-Methods'] = 'GET,POST,DELETE'
        return response

Adding custom logging
---------------------

.. note::
    For basic file logging, you can use the ``-l`` / ``--logfile`` command-line
    option (see :ref:`command-line-options`). The technique below is useful
    when you need more control over log levels, formatting, or multiple
    handlers.

To log exceptions within the Scout server with a custom configuration, create a
wrapper module that adds a handler to Flask's built-in app logger:

.. code-block:: python

    import logging
    import os

    from scout.server import parse_options

    app = parse_options()

    cur_dir = os.path.realpath(os.path.dirname(__file__))
    log_dir = os.path.join(cur_dir, 'logs')

    handler = logging.FileHandler(os.path.join(log_dir, 'scout-error.log'))
    handler.setLevel(logging.ERROR)
    app.logger.addHandler(handler)
