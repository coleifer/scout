import base64
import json
try:
    from email.generator import _make_boundary as choose_boundary
except ImportError:
    from mimetools import choose_boundary
import mimetypes
import os
try:
    from urllib.parse import urlencode
except ImportError:
    from urllib import urlencode
try:
    from urllib.request import Request
    from urllib.request import urlopen
except ImportError:
    from urllib2 import Request
    from urllib2 import urlopen
import zlib


ENDPOINT = None
KEY = None


class Scout(object):
    def __init__(self, endpoint=ENDPOINT, key=KEY):
        self.endpoint = endpoint.rstrip('/')
        self.key = key

    def get_full_url(self, url):
        return self.endpoint + url

    def get_raw(self, url, **kwargs):
        headers = {'Content-Type': 'application/json'}
        if self.key:
            headers['key'] = self.key
        if kwargs:
            if '?' not in url:
                url += '?'
            url += urlencode(kwargs, True)
        request = Request(self.get_full_url(url), headers=headers)
        fh = urlopen(request)
        return fh.read()

    def get(self, url, **kwargs):
        return json.loads(self.get_raw(url, **kwargs))

    def post(self, url, data=None, files=None):
        if files:
            return self.post_files(url, data, files)
        else:
            return self.post_json(url, data)

    def post_json(self, url, data=None):
        headers = {'Content-Type': 'application/json'}
        if self.key:
            headers['key'] = self.key
        data = json.dumps(data or {})
        if not isinstance(data, bytes):
            data = data.encode('utf-8')
        request = Request(self.get_full_url(url), data=data, headers=headers)
        return json.loads(urlopen(request).read().decode('utf8'))

    def post_files(self, url, json_data, files=None):
        if not files or not isinstance(files, dict):
            raise ValueError('One or more files is required. Files should be '
                             'passed as a dictionary of filename: file-like-'
                             'object.')
        boundary = choose_boundary()
        form_files = []
        for i, (filename, file_obj) in enumerate(files.items()):
            try:
                data = file_obj.read()
            except AttributeError:
                data = bytes(file_obj)
            mimetype = mimetypes.guess_type(filename)[0]
            form_files.append((
                'file_%s' % i,
                filename,
                mimetype or 'application/octet-stream',
                data))

        part_boundary = '--' + boundary
        parts = [
            part_boundary,
            'Content-Disposition: form-data; name="data"',
            '',
            json.dumps(json_data)]
        for field_name, filename, mimetype, data in form_files:
            parts.extend((
                part_boundary,
                'Content-Disposition: file; name="%s"; filename="%s"' % (
                    field_name, filename),
                'Content-Type: %s' % mimetype,
                '',
                data))
        parts.append('--' + boundary + '--')
        parts.append('')

        headers = {'Content-Type': 'multipart/form-data; boundary=%s' %
                   boundary}
        if self.key:
            headers['key'] = self.key

        data = '\r\n'.join(parts)
        if not isinstance(data, bytes):
            data = data.encode('utf-8')

        request = Request(self.get_full_url(url), data=data, headers=headers)
        return json.loads(urlopen(request).read())

    def delete(self, url):
        headers = {}
        if self.key:
            headers['key'] = self.key
        request = Request(self.get_full_url(url), headers=headers)
        request.get_method = lambda: 'DELETE'
        fh = urlopen(request)
        return json.loads(fh.read())

    def get_indexes(self, **kwargs):
        return self.get('/', **kwargs)['indexes']

    def create_index(self, name):
        return self.post('/', {'name': name})

    def rename_index(self, old_name, new_name):
        return self.post('/%s/' % old_name, {'name': new_name})

    def delete_index(self, name):
        return self.delete('/%s/' % name)

    def get_index(self, name, **kwargs):
        return self.get('/%s/' % name, **kwargs)

    def get_documents(self, **kwargs):
        return self.get('/documents/', **kwargs)

    def create_document(self, content, indexes, identifier=None,
                        attachments=None, **metadata):
        if not isinstance(indexes, (list, tuple)):
            indexes = [indexes]
        post_data = {
            'content': content,
            'identifier': identifier,
            'indexes': indexes,
            'metadata': metadata}
        return self.post('/documents/', post_data, attachments)

    def update_document(self, document_id=None, content=None, indexes=None,
                        metadata=None, identifier=None, attachments=None):
        if not document_id and not identifier:
            raise ValueError('`document_id` must be provided.')

        data = {}
        if content is not None:
            data['content'] = content
        if indexes is not None:
            if not isinstance(indexes, (list, tuple)):
                indexes = [indexes]
            data['indexes'] = indexes
        if metadata is not None:
            data['metadata'] = metadata

        if not data and not attachments:
            raise ValueError('Nothing to update.')

        return self.post('/documents/%s/' % document_id, data, attachments)

    def delete_document(self, document_id=None):
        if not document_id:
            raise ValueError('`document_id` must be provided.')

        return self.delete('/documents/%s/' % document_id)

    def get_document(self, document_id=None):
        if not document_id:
            raise ValueError('`document_id` must be provided.')

        return self.get('/documents/%s/' % document_id)

    def attach_files(self, document_id, attachments):
        return self.post_files('/documents/%s/attachments/' % document_id,
                               {}, attachments)

    def detach_file(self, document_id, filename):
        return self.delete('/documents/%s/attachments/%s/' %
                           (document_id, filename))

    def update_file(self, document_id, filename, file_object):
        return self.post_files('/documents/%s/attachments/%s/' %
                               (document_id, filename),
                               {}, {filename: file_object})

    def get_attachments(self, document_id, **kwargs):
        return self.get('/documents/%s/attachments/' % document_id, **kwargs)

    def get_attachment(self, document_id, filename):
        return self.get('/documents/%s/attachments/%s/' %
                        (document_id, filename))

    def download_attachment(self, document_id, filename):
        return self.get_raw('/documents/%s/attachments/%s/download/' %
                            (document_id, filename))

    def search_attachments(self, **kwargs):
        return self.get('/documents/attachments/', **kwargs)


class SearchProvider(object):
    def content(self, obj):
        raise NotImplementedError

    def identifier(self, obj):
        raise NotImplementedError

    def metadata(self, obj):
        raise NotImplementedError


class SearchSite(object):
    def __init__(self, client, index):
        self.client = client
        self.index = index
        self.registry = {}

    def register(self, model_class, search_provider):
        self.registry.setdefault(model_class, [])
        self.registry[model_class].append(search_provider())

    def unregister(self, model_class, search_provider=None):
        if search_provider is None:
            self.registry.pop(model_class, None)
        elif model_class in self.registry:
            self.registry[model_class] = [
                sp for sp in self.registry[model_class]
                if not isinstance(sp, search_provider)]

    def store(self, obj):
        if type(obj) not in self.registry:
            return False

        for provider in self.registry[type(obj)]:
            content = provider.content(obj)
            try:
                metadata = provider.metadata(obj)
            except NotImplementedError:
                metadata = {}

            try:
                identifier = provider.identifier(obj)
            except NotImplementedError:
                pass
            else:
                metadata['identifier'] = identifier

            self.client.create_document(content, self.index, **metadata)

        return True

    def remove(self, obj):
        if type(obj) not in self.registry:
            return False

        for provider in self.registry[type(obj)]:
            self.client.delete_document(provider.identifier(obj))

        return True
