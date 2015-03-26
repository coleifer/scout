import json
import urllib
import urllib2
import urlparse


ENDPOINT = None
KEY = None


class Scout(object):
    def __init__(self, endpoint=ENDPOINT, key=KEY):
        self.endpoint = endpoint
        self.key = key

    def get_full_url(self, url):
        return urlparse.urljoin(self.endpoint, url)

    def get(self, url, **kwargs):
        headers = {'Content-Type': 'application/json'}
        if self.key:
            headers['key'] = self.key
        if kwargs:
            if '?' not in url:
                url += '?'
            url += urllib.urlencode(kwargs, True)
        request = urllib2.Request(self.get_full_url(url), headers=headers)
        fh = urllib2.urlopen(request)
        return json.loads(fh.read())

    def post(self, url, data=None):
        headers = {'Content-Type': 'application/json'}
        if self.key:
            headers['key'] = self.key
        request = urllib2.Request(
            self.get_full_url(url),
            data=json.dumps(data or {}),
            headers=headers)
        fh = urllib2.urlopen(request)
        return json.loads(fh.read())

    def delete(self, url):
        headers = {}
        if self.key:
            headers['key'] = self.key
        request = urllib2.Request(self.get_full_url(url))
        request.get_method = lambda: 'DELETE'
        fh = urllib2.urlopen(request)
        return json.loads(fh.read())

    def get_indexes(self):
        return self.get('/')['indexes']

    def create_index(self, name):
        return self.post('/', {'name': name})

    def rename_index(self, old_name, new_name):
        return self.post('/%s/' % old_name, {'name': new_name})

    def delete_index(self, name):
        return self.delete('/%s/' % name)

    def get_documents(self, **kwargs):
        return self.get('/documents/', **kwargs)

    def store_document(self, content, indexes, **metadata):
        if not isinstance(indexes, (list, tuple)):
            indexes = [indexes]
        return self.post('/documents/', {
            'content': content,
            'indexes': indexes,
            'metadata': metadata})

    def update_document(self, document_id, content=None, indexes=None,
                        metadata=None):
        data = {}
        if content is not None:
            data['content'] = content
        if indexes is not None:
            if not isinstance(indexes, (list, tuple)):
                indexes = [indexes]
            data['indexes'] = indexes
        if metadata is not None:
            data['metadata'] = metadata

        if not data:
            raise ValueError('Nothing to update.')

        return self.post('/documents/%s/' % document_id, data)

    def delete_document(self, document_id):
        return self.delete('/documents/%s/' % document_id)

    def search(self, index, query, **kwargs):
        kwargs['q'] = query
        return self.get('/%s/search/' % index, **kwargs)
