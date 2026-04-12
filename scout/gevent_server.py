from gevent import monkey; monkey.patch_all()

import os
import sys
from scout.server import parse_options


# Module-level app creation: parse_options() reads sys.argv and returns a
# configured Flask app.  This runs on import so that external WSGI servers
# can reference the app object directly (e.g. gunicorn gevent_server:app).
app = parse_options()


def main():
    from gevent.pool import Pool
    from gevent.pywsgi import WSGIServer

    MAX_CONNECTIONS = int(os.environ.get('SCOUT_MAX_CONNECTIONS') or 128)
    pool = Pool(MAX_CONNECTIONS)
    try:
        (WSGIServer((app.config['HOST'], app.config['PORT']), app, spawn=pool)
         .serve_forever())
    except KeyboardInterrupt:
        app.logger.info('Shutting down!')
        sys.exit(0)


if __name__ == '__main__':
    main()
