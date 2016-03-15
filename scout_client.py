import base64
import json
import mimetools
import mimetypes
import os
import urllib
import urllib2
import urlparse
import zlib


ENDPOINT = None
KEY = None


class Scout(object):
    def __init__(self, endpoint=ENDPOINT, key=KEY):
        self.endpoint = endpoint
        self.key = key

    def get_full_url(self, url):
        return urlparse.urljoin(self.endpoint, url)

    def get_raw(self, url, **kwargs):
        headers = {'Content-Type': 'application/json'}
        if self.key:
            headers['key'] = self.key
        if kwargs:
            if '?' not in url:
                url += '?'
            url += urllib.urlencode(kwargs, True)
        request = urllib2.Request(self.get_full_url(url), headers=headers)
        fh = urllib2.urlopen(request)
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
        request = urllib2.Request(
            self.get_full_url(url),
            data=json.dumps(data or {}),
            headers=headers)
        fh = urllib2.urlopen(request)
        return json.loads(fh.read())

    def post_files(self, url, json_data, files=None):
        if not files or not isinstance(files, dict):
            raise ValueError('One or more files is required. Files should be '
                             'passed as a dictionary of filename: file-like-'
                             'object.')
        boundary = mimetools.choose_boundary()
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
        request = urllib2.Request(
            self.get_full_url(url),
            data='\r\n'.join(parts),
            headers=headers)
        fh = urllib2.urlopen(request)
        return json.loads(fh.read())

    def delete(self, url):
        headers = {}
        if self.key:
            headers['key'] = self.key
        request = urllib2.Request(self.get_full_url(url), headers=headers)
        request.get_method = lambda: 'DELETE'
        fh = urllib2.urlopen(request)
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
        return self.post_filese('/documents/%s/attachments/%s/' %
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
