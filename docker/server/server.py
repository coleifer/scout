from gevent import monkey; monkey.patch_all()

import os
import sys
from scout.server import parse_options


# Create WSGI app using command-line options.
app = parse_options()

if __name__ == '__main__':
    # Serve app using gevent WSGI server.
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
