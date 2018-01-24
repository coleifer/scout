import json
import sys

from flask import request

from scout.constants import PROTECTED_KEYS
from scout.exceptions import error
from scout.models import Index


if sys.version_info[0] == 2:
    json_load = lambda d: json.loads(d)
else:
    json_load = lambda d: json.loads(d.decode('utf-8') if isinstance(d, bytes)
                                     else d)


class RequestValidator(object):
    def parse_post(self, required_keys=None, optional_keys=None):
        """
        Clean and validate POSTed JSON data by defining sets of required and
        optional keys.
        """
        if request.headers.get('content-type') == 'application/json':
            data = request.data
        elif 'data' not in request.form:
            error('Missing correct content-type or missing "data" field.')
        else:
            data = request.form['data']

        if data:
            try:
                data = json_load(data)
            except ValueError:
                error('Unable to parse JSON data from request.')
        else:
            data = {}

        required = set(required_keys or ())
        optional = set(optional_keys or ())
        all_keys = required | optional
        keys_present = set(key for key in data if data[key] not in ('', None))

        missing = required - keys_present
        if missing:
            error('Missing required fields: %s' % ', '.join(sorted(missing)))

        invalid_keys = keys_present - all_keys
        if invalid_keys:
            error('Invalid keys: %s' % ', '.join(sorted(invalid_keys)))

        return data

    def validate_indexes(self, data, required=True):
        if data.get('index'):
            index_names = (data['index'],)
        elif data.get('indexes'):
            index_names = data['indexes']
        elif ('index' in data or 'indexes' in data) and not required:
            return ()
        else:
            return None

        indexes = list(Index.select().where(Index.name << index_names))

        # Validate that all the index names exist.
        observed_names = set(index.name for index in indexes)
        invalid_names = []
        for index_name in index_names:
            if index_name not in observed_names:
                invalid_names.append(index_name)

        if invalid_names:
            error('The following indexes were not found: %s.' %
                  ', '.join(invalid_names))

        return indexes

    def extract_get_params(self):
        return dict(
            (key, request.args.getlist(key))
            for key in request.args
            if key not in PROTECTED_KEYS)
