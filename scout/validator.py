import json
import re

from flask import request

from scout.constants import PROTECTED_KEYS
from scout.exceptions import error
from scout.models import Index


json_load = lambda d: json.loads(d.decode('utf-8') if isinstance(d, bytes)
                                 else d)
identifier_re = re.compile(r'^[a-zA-Z0-9_\-\.:]+$')


class RequestValidator(object):
    def parse_post(self, required_keys=None, optional_keys=None):
        """
        Clean and validate POSTed JSON data by defining sets of required and
        optional keys.
        """
        if request.is_json:
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

        # Keys that carry a meaningful value (for required-field checks).
        keys_present = set(key for key in data if data[key] not in ('', None))
        # All keys in the payload (for unknown-key checks).
        all_keys_in_payload = set(data.keys())

        missing = required - keys_present
        if missing:
            error('Missing required fields: %s' % ', '.join(sorted(missing)))

        invalid_keys = all_keys_in_payload - all_keys
        if invalid_keys:
            error('Invalid keys: %s' % ', '.join(sorted(invalid_keys)))

        if data.get('identifier'):
            identifier = data.get('identifier')
            if not identifier_re.match(identifier):
                error('Identifier may only consist of the following: '
                      'letters, numbers, "_", "-", ".", ":"')

        return data

    def normalize_get_indexes(self, data):
        if data.get('index'):
            index_names = data.getlist('index')
        elif data.get('indexes'):
            index_names = data.getlist('indexes')
        else:
            return ()
        return self._validate_index_names(index_names)

    def validate_indexes(self, data, required=True):
        has_index_key = 'index' in data or 'indexes' in data
        if data.get('index'):
            index_names = (data['index'],)
        elif data.get('indexes'):
            index_names = data['indexes']
        elif has_index_key and not required:
            return ()  # Key present but not required -> clear indexes.
        elif has_index_key and required:
            return None  # Will trigger error.
        else:
            return None  # Key not present at all.

        return self._validate_index_names(index_names)

    def _validate_index_names(self, index_names):
        indexes = list(Index.select().where(Index.name.in_(index_names)))

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
