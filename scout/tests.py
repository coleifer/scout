import json
import optparse
import sys
import unittest
try:
    from urllib.parse import urlencode
except ImportError:
    from urllib import urlencode
from io import BytesIO

from playhouse.sqlite_ext import *
from playhouse.test_utils import assert_query_count

from scout.constants import SEARCH_BM25
from scout.exceptions import InvalidRequestException
from scout.exceptions import InvalidSearchException
from scout.models import Attachment
from scout.models import BlobData
from scout.models import database
from scout.models import Document
from scout.models import Index
from scout.models import IndexDocument
from scout.models import Metadata
from scout.search import DocumentSearch
from scout.server import create_server


test_config = {
    'DATABASE': ':memory:',
    'PAGINATE_BY': 10,
}
app = create_server(test_config)
engine = DocumentSearch()


def get_option_parser():
    parser = optparse.OptionParser()
    parser.add_option(
        '-q',
        '--quiet',
        action='store_true',
        dest='quiet')
    return parser

def json_load(data):
    return json.loads(data.decode('utf-8'))


class BaseTestCase(unittest.TestCase):
    corpus = [
        ('A faith is a necessity to a man. Woe to him who believes in '
         'nothing.'),
        ('All who call on God in true faith, earnestly from the heart, '
         'will certainly be heard, and will receive what they have asked '
         'and desired.'),
        ('Be faithful in small things because it is in them that your '
         'strength lies.'),
        ('Faith consists in believing when it is beyond the power of '
         'reason to believe.'),
        ('Faith has to do with things that are not seen and hope with '
         'things that are not at hand.'),
    ]

    def setUp(self):
        if not database.is_closed():
            database.close()
        database.connect()
        database.foreign_keys = 0
        assert database.get_tables() == []
        database.create_tables([
            Attachment,
            BlobData,
            Document,
            Metadata,
            Index,
            IndexDocument])


class TestSearch(BaseTestCase):
    def setUp(self):
        super(TestSearch, self).setUp()
        self.app = app.test_client()
        self.index = Index.create(name='default')
        Index.create(name='unused-1')
        Index.create(name='unused-2')
        app.config['AUTHENTICATION'] = None

    def populate(self):
        k1 = ['k1-1', 'k1-2']
        k2 = ['k2-1', 'k2-2']
        k3 = ['k3-1', 'k3-2']
        messages = [
            'foo bar baz',
            'nuggie zaizee',
            'huey mickey',
            'googie',
        ]
        with database.atomic():
            for i in range(100):
                self.index.index(
                    content='testing %s' % i,
                    test='true',
                    k1=k1[i % 2],
                    k2=k2[i % 2],
                    k3=k3[i % 2],
                    idx='%02d' % i,
                    idx10=i % 10,
                    name=messages[i % 4],
                )

    def search(self, index, query, page=1, **filters):
        filters.setdefault('ranking', SEARCH_BM25)
        params = urlencode(dict(filters, q=query, page=page))
        response = self.app.get('/%s/?%s' % (index, params))
        return json_load(response.data)

    def test_model_search(self):
        self.populate()
        results = engine.search('testing 1*', index=self.index, k1='k1-1')
        clean = [(doc.content, doc.metadata['k1']) for doc in results]
        self.assertEqual(sorted(clean), [
            ('testing 10', 'k1-1'),
            ('testing 12', 'k1-1'),
            ('testing 14', 'k1-1'),
            ('testing 16', 'k1-1'),
            ('testing 18', 'k1-1'),
        ])

    def assertResults(self, filters, expected):
        results = engine.search('testing', index=self.index, **filters)
        results = sorted(results, key=lambda doc: doc.metadata['idx'])
        indexes = [doc.metadata['idx'] for doc in results]
        self.assertEqual(indexes, expected)
        return results

    def test_model_filtering(self):
        self.populate()
        self.assertResults(
            {'idx__ge': 95, 'idx10__in': '5,8,9,1, 3'},
            ['95', '98', '99'])

        results = self.assertResults(
            {'name__contains': 'gie', 'idx10__ge': 6, 'idx__lt': 30},
            ['07', '09', '17', '19', '27', '29'])

        names = [doc.metadata['name'] for doc in results]
        self.assertEqual(names, [
            'googie',
            'nuggie zaizee',
            'nuggie zaizee',
            'googie',
            'googie',
            'nuggie zaizee'])

        self.assertResults(
            {'name__regex': 'gie$', 'idx__gt': 90},
            ['91', '95', '99'])

    def test_filter_or(self):
        self.populate()
        self.assertResults(
            {'idx': ['03', '05', '99']},
            ['03', '05', '99'])

        crazy = {
            'idx10': ['1', '4', '7'],
            'idx__lt': '30',
            'name': ['huey mickey', 'nuggie zaizee']}
        results = self.assertResults(crazy, ['01', '14', '17', '21'])
        names = [doc.metadata['name'] for doc in results]
        self.assertEqual(names, ['nuggie zaizee', 'huey mickey',
                                 'nuggie zaizee', 'nuggie zaizee'])

    def test_docs_example(self):
        data = [
            ('huey', ('2010-06-01', 'Lawrence', 'KS')),
            ('mickey', ('2008-04-01', 'Lawrence', 'KS')),
            ('zaizee', ('2012-05-01', 'Lawrence', 'KS')),
            ('dodie', ('2014-09-01', 'Lawrence', 'KS')),
            ('harley', ('2008-04-20', 'Topeka', 'KS')),
            ('oreo', ('2009-01-01', 'Topeka', 'KS')),
            ('boo', ('2012-01-01', 'Kansas City', 'MO')),
            ('gray', ('2012-02-01', 'Kansas City', 'MO')),
            ('mackie', ('2007-02-01', 'Pittsburg', 'KS')),
        ]
        for name, (dob, city, state) in data:
            self.index.index(content=name, dob=dob, city=city, state=state)

        docs = engine.search('*', index=self.index, dob__gt='2009-01-01')
        self.assertEqual(sorted([doc.metadata['dob'] for doc in docs]), [
            '2010-06-01',
            '2012-01-01',
            '2012-02-01',
            '2012-05-01',
            '2014-09-01',
        ])

        docs = engine.search(
            '*', index=self.index, dob__ge='2008-01-01', dob__lt='2009-01-01')
        self.assertEqual(sorted([doc.metadata['dob'] for doc in docs]), [
            '2008-04-01',
            '2008-04-20',
        ])

        docs = engine.search('*', index=self.index, city__in='Topeka,Lawrence',
                             state='KS')
        self.assertEqual(sorted([doc.content for doc in docs]), [
            'dodie',
            'harley',
            'huey',
            'mickey',
            'oreo',
            'zaizee',
        ])

    def test_invalid_op(self):
        self.assertRaises(
            InvalidRequestException,
            lambda: engine.search('testing', index=self.index,
                                  name__xx='missing'))

    def test_search(self):
        self.populate()
        results = self.search('default', 'testing', k1='k1-1')
        self.assertEqual(results['pages'], 5)
        self.assertEqual(results['page'], 1)
        self.assertEqual([d['metadata']['k1'] for d in results['documents']],
                         ['k1-1'] * 10)

        results = self.search(
            'default',
            'testing',
            k1='k1-1',
            k2='k2-1',
            k3='k3-1')
        self.assertEqual(results['page'], 1)
        self.assertEqual(results['pages'], 5)
        self.assertEqual([d['metadata']['k1'] for d in results['documents']],
                         ['k1-1'] * 10)

    def test_search_queries(self):
        self.populate()
        with assert_query_count(9):
            results = self.search(
                'default',
                'testing',
                k1='k1-1',
                k2='k2-1',
                k3='k3-1')

        self.assertEqual(results['page'], 1)
        self.assertEqual(results['pages'], 5)
        self.assertEqual([d['metadata']['k1'] for d in results['documents']],
                         ['k1-1'] * 10)

class TestModelAPIs(BaseTestCase):
    def setUp(self):
        super(TestModelAPIs, self).setUp()
        self.index = Index.create(name='default')

    def test_index_document(self):
        """
        Basic test case ensuring that content can be indexed and that the
        many-to-many relationship between documents and indexes is set
        up correctly.
        """
        content = 'huey is a sweet little kitty'
        doc = self.index.index(content=content)

        # Verify document properties.
        self.assertEqual(doc.get_id(), 1)
        self.assertEqual(doc.content, content)
        self.assertEqual(doc.metadata, {})

        # Verify through relationship properties.
        self.assertEqual(IndexDocument.select().count(), 1)
        idx_doc = IndexDocument.get()
        self.assertEqual(idx_doc.__data__['document'], doc.get_id())
        self.assertEqual(idx_doc.__data__['index'], self.index.id)

    def test_index_with_metadata(self):
        """
        Test to ensure that content can be indexed with arbitrary key
        value metadata, which is stored as strings.
        """
        doc = self.index.index('test doc', foo='bar', nugget=33)
        self.assertEqual(doc.get_id(), 1)
        self.assertEqual(doc.metadata, {'foo': 'bar', 'nugget': '33'})

    def test_reindex(self):
        """
        Test that an existing document can be re-indexed, updating the
        content and metadata in the process.
        """
        doc = self.index.index('test doc', foo='bar', baze='nug')
        doc_db = (Document
                  .select(Document._meta.primary_key, Document.content)
                  .get())
        self.assertTrue(doc_db.get_id() is not None)
        self.assertEqual(doc_db.content, 'test doc')
        self.assertEqual(doc_db.metadata, {'foo': 'bar', 'baze': 'nug'})

        updated_doc = self.index.index(
            'updated doc',
            document=doc,
            foo='bazz',
            nug='x')
        self.assertEqual(Document.select().count(), 1)
        self.assertEqual(updated_doc.metadata, {'foo': 'bazz', 'nug': 'x'})

        u_doc_db = (Document
                    .select(Document._meta.primary_key, Document.content)
                    .get())
        self.assertEqual(u_doc_db.content, 'updated doc')
        self.assertEqual(u_doc_db.get_id(), doc_db.get_id())
        self.assertEqual(u_doc_db.metadata, {'foo': 'bazz', 'nug': 'x'})

        # Verify through relationship properties.
        self.assertEqual(IndexDocument.select().count(), 1)
        idx_doc = IndexDocument.get()
        self.assertEqual(idx_doc.__data__['document'], u_doc_db.get_id())
        self.assertEqual(idx_doc.__data__['index'], self.index.id)

    def test_multi_index(self):
        """
        Test that documents can be stored in multiple indexes.
        """
        self.index.delete_instance()

        indexes = [Index.create(name='idx-%s' % i) for i in range(3)]
        document = Document.create(content='hueybear')
        for index in indexes:
            index.index(
                document.content,
                document)

        self.assertEqual(Document.select().count(), 1)
        self.assertEqual(Index.select().count(), 3)
        self.assertEqual(IndexDocument.select().count(), 3)
        query = (IndexDocument
                 .select(Index.name, IndexDocument.document)
                 .join(Index)
                 .order_by(Index.name)
                 .dicts())
        idx_doc_data = [idx_doc for idx_doc in query]
        self.assertEqual(idx_doc_data, [
            {'document': document.get_id(), 'name': 'idx-0'},
            {'document': document.get_id(), 'name': 'idx-1'},
            {'document': document.get_id(), 'name': 'idx-2'},
        ])

    def test_search(self):
        """
        Basic tests for simple string searches of a single index. Use both
        the simple and bm25 ranking algorithms.
        """
        for idx, content in enumerate(self.corpus):
            self.index.index(content=content)

        def assertSearch(phrase, indexes, ranking=SEARCH_BM25):
            results = [
                doc.content
                for doc in
                engine.search(phrase, index=self.index, ranking=ranking)]
            self.assertEqual(results, [self.corpus[idx] for idx in indexes])

        assertSearch('believe', [3, 0])
        assertSearch('faith man', [0])
        assertSearch('faith thing', [4, 2])
        assertSearch('things', [4, 2])
        assertSearch('blah', [])
        self.assertRaises(InvalidSearchException, engine.search, '')

        assertSearch('believe', [3, 0], SEARCH_BM25)  # Same result.
        assertSearch('faith thing', [4, 2], SEARCH_BM25)  # Same.
        assertSearch('things', [4, 2], SEARCH_BM25)  # Same result.
        assertSearch('blah', [], SEARCH_BM25)  # No results, works.
        self.assertRaises(
            InvalidSearchException, engine.search, '', SEARCH_BM25)


class TestSearchViews(BaseTestCase):
    def setUp(self):
        super(TestSearchViews, self).setUp()
        self.app = app.test_client()
        app.config['AUTHENTICATION'] = None

    def post_json(self, url, data, parse_response=True):
        response = self.app.post(
            url,
            data=json.dumps(data),
            headers={'content-type': 'application/json'})
        if parse_response:
            return json_load(response.data)
        return response

    def test_create_index(self):
        data = self.post_json('/', {'name': 'TestIndex'})
        self.assertEqual(data['name'], 'TestIndex')
        self.assertEqual(data['documents'], [])
        self.assertEqual(Index.select().count(), 1)

    def test_create_missing_name(self):
        error = {'error': 'Missing required fields: name'}
        data = self.post_json('/', {})
        self.assertEqual(data, error)

        data = self.post_json('/', {'name': None})
        self.assertEqual(data, error)

    def test_create_invalid_json(self):
        response = self.app.post('/', data='not json')
        data = json_load(response.data)
        self.assertEqual(
            data,
            {'error': 'Missing correct content-type or missing "data" field.'})

        response = self.app.post(
            '/',
            data='not json',
            headers={'content-type': 'application/json'})
        data = json_load(response.data)
        self.assertEqual(
            data,
            {'error': 'Unable to parse JSON data from request.'})

    def test_index_list(self):
        for i in range(3):
            Index.create(name='i%s' % i)

        response = self.app.get('/')
        data = json_load(response.data)
        self.assertEqual(data['indexes'], [
            {'document_count': 0, 'documents': '/i0/', 'id': 1, 'name': 'i0'},
            {'document_count': 0, 'documents': '/i1/', 'id': 2, 'name': 'i1'},
            {'document_count': 0, 'documents': '/i2/', 'id': 3, 'name': 'i2'},
        ])

    def test_index_missing(self):
        response = self.app.get('/missing/')
        self.assertEqual(response.status_code, 404)

    def test_index_detail(self):
        idx_a = Index.create(name='idx-a')
        idx_b = Index.create(name='idx-b')
        for i in range(11):
            idx_a.index('document-%s' % i, foo='bar-%s' % i)

        b_doc = idx_b.index('both-doc')
        idx_a.index(b_doc.content, b_doc)

        response = self.app.get('/idx-a/')
        data = json_load(response.data)
        self.assertEqual(data['page'], 1)
        self.assertEqual(data['pages'], 2)
        self.assertEqual(len(data['documents']), 10)
        doc = data['documents'][0]
        self.assertEqual(doc, {
            'attachments': [],
            'content': 'document-0',
            'id': 1,
            'identifier': None,
            'indexes': ['idx-a'],
            'metadata': {'foo': 'bar-0'}})

        response = self.app.get('/idx-a/?page=2')
        data = json_load(response.data)
        self.assertEqual(data['page'], 2)
        self.assertEqual(data['pages'], 2)
        self.assertEqual(len(data['documents']), 2)

        response = self.app.get('/idx-b/')
        data = json_load(response.data)
        self.assertEqual(data['page'], 1)
        self.assertEqual(data['pages'], 1)
        self.assertEqual(len(data['documents']), 1)
        doc = data['documents'][0]
        self.assertEqual(doc, {
            'attachments': [],
            'content': 'both-doc',
            'id': 12,
            'identifier': None,
            'indexes': ['idx-b', 'idx-a'],
            'metadata': {}})

    def test_index_update_delete(self):
        idx = Index.create(name='idx')
        alt_idx = Index.create(name='alt-idx')
        doc = idx.index(content='foo')
        alt_idx.index(doc.content, doc)
        idx.index('idx only')
        alt_idx.index('alt only')

        response = self.post_json('/idx/', {'name': 'idx-updated'})
        self.assertEqual(response['id'], idx.id)
        self.assertEqual(response['name'], 'idx-updated')
        self.assertEqual(
            [doc['content'] for doc in response['documents']],
            ['foo', 'idx only'])

        response = self.app.delete('/idx-updated/')
        data = json_load(response.data)
        self.assertEqual(data, {'success': True})

        self.assertEqual(Document.select().count(), 3)
        self.assertEqual(IndexDocument.select().count(), 2)
        self.assertEqual(Index.select().count(), 1)

    def test_index_document(self):
        idx_a = Index.create(name='idx-a')
        idx_b = Index.create(name='idx-b')
        response = self.post_json('/documents/', {
            'content': 'doc 1',
            'index': 'idx-a',
            'metadata': {'k1': 'v1', 'k2': 'v2'}})

        self.assertEqual(response, {
            'attachments': [],
            'content': 'doc 1',
            'id': 1,
            'identifier': None,
            'indexes': ['idx-a'],
            'metadata': {'k1': 'v1', 'k2': 'v2'}})

        response = self.post_json('/documents/', {
            'content': 'doc 2',
            'indexes': ['idx-a', 'idx-b']})
        self.assertEqual(response, {
            'attachments': [],
            'content': 'doc 2',
            'id': 2,
            'identifier': None,
            'indexes': ['idx-a', 'idx-b'],
            'metadata': {}})

    def test_index_document_attachments(self):
        idx_a = Index.create(name='idx-a')
        json_data = json.dumps({
            'content': 'doc a',
            'index': 'idx-a',
            'metadata': {'k1': 'v1-a', 'k2': 'v2-a'},
        })
        response = self.app.post('/documents/', data={
            'data': json_data,
            'file_0': (BytesIO(b'testfile1'), 'test1.txt'),
            'file_1': (BytesIO(b'testfile2'), 'test2.jpg')})

        a1 = Attachment.get(Attachment.filename == 'test1.txt')
        a2 = Attachment.get(Attachment.filename == 'test2.jpg')
        a1_data = {
            'data': '/documents/1/attachments/test1.txt/download/',
            'data_length': 9,
            'mimetype': 'text/plain',
            'timestamp': str(a1.timestamp),
            'filename': 'test1.txt'}
        a2_data = {
            'data': '/documents/1/attachments/test2.jpg/download/',
            'data_length': 9,
            'mimetype': 'image/jpeg',
            'timestamp': str(a2.timestamp),
            'filename': 'test2.jpg'}

        resp_data = json_load(response.data)
        self.assertEqual(resp_data, {
            'attachments': [a1_data, a2_data],
            'content': 'doc a',
            'id': 1,
            'identifier': None,
            'indexes': ['idx-a'],
            'metadata': {'k1': 'v1-a', 'k2': 'v2-a'}})

        Attachment.update(timestamp='2016-02-01 01:02:03').execute()

        with assert_query_count(3):
            resp = self.app.get('/documents/1/attachments/')

        self.assertEqual(json_load(resp.data), {
            'ordering': [],
            'pages': 1,
            'page': 1,
            'attachments': [
                {
                    'mimetype': 'text/plain',
                    'timestamp': '2016-02-01 01:02:03',
                    'data_length': 9,
                    'filename': 'test1.txt',
                    'document': '/documents/1/',
                    'data': '/documents/1/attachments/test1.txt/download/',
                },
                {
                    'mimetype': 'image/jpeg',
                    'timestamp': '2016-02-01 01:02:03',
                    'data_length': 9,
                    'filename': 'test2.jpg',
                    'document': '/documents/1/',
                    'data': '/documents/1/attachments/test2.jpg/download/',
                },
            ],
        })

    def test_index_document_validation(self):
        idx = Index.create(name='idx')
        response = self.post_json('/documents/', {'content': 'foo'})
        self.assertEqual(
            response['error'],
            'You must specify either an "index" or "indexes".')

        response = self.post_json('/documents/', {'content': 'x', 'index': ''})
        self.assertEqual(
            response['error'],
            'You must specify either an "index" or "indexes".')

        response = self.post_json('/documents/', {
            'content': 'foo',
            'index': 'missing'})
        self.assertEqual(
            response['error'],
            'The following indexes were not found: missing.')

        response = self.post_json('/documents/', {
            'content': 'foo',
            'indexes': ['missing', 'idx', 'blah']})
        self.assertEqual(
            response['error'],
            'The following indexes were not found: missing, blah.')
        self.assertEqual(Document.select().count(), 0)

    def test_document_detail_get(self):
        idx = Index.create(name='idx')
        doc = idx.index('test doc', foo='bar')
        alt_doc = idx.index('alt doc')

        response = self.app.get('/documents/%s/' % doc.docid)
        data = json_load(response.data)
        self.assertEqual(data, {
            'attachments': [],
            'content': 'test doc',
            'id': doc.get_id(),
            'identifier': None,
            'indexes': ['idx'],
            'metadata': {'foo': 'bar'}})

    def refresh_doc(self, doc):
        return (Document
                .all()
                .where(Document._meta.primary_key == doc.get_id())
                .get())

    def test_document_detail_post(self):
        idx = Index.create(name='idx')
        alt_idx = Index.create(name='alt-idx')
        doc = idx.index('test doc', foo='bar', nug='baze')
        alt_doc = idx.index('alt doc')

        url = '/documents/%s/' % doc.get_id()

        def assertDoc(doc, content, metadata=None, indexes=None):
            doc_db = self.refresh_doc(doc)
            self.assertEqual(doc_db.content, content)
            self.assertEqual(
                [idx.name for idx in doc_db.get_indexes()],
                indexes or [])
            self.assertEqual(doc_db.metadata, metadata or {})

        # Update the content.
        response = self.post_json(url, {'content': 'updated'})
        assertDoc(doc, 'updated', {'foo': 'bar', 'nug': 'baze'}, ['idx'])

        # Test updating metadata.
        response = self.post_json(url, {'metadata': dict(
            doc.metadata, nug='baz', herp='derp')})
        assertDoc(
            doc,
            'updated',
            {'foo': 'bar', 'nug': 'baz', 'herp': 'derp'},
            ['idx'])

        # Test clearing metadata.
        response = self.post_json(url, {'metadata': None})
        assertDoc(doc, 'updated', {}, ['idx'])

        # Test updating indexes.
        response = self.post_json(url, {'indexes': ['idx', 'alt-idx']})
        assertDoc(doc, 'updated', {}, ['alt-idx', 'idx'])

        # Test clearing indexes.
        response = self.post_json(url, {'indexes': []})
        assertDoc(doc, 'updated', {}, [])

        # Ensure alt_doc has not been affected.
        assertDoc(alt_doc, 'alt doc', {}, ['idx'])

        # Sanity check.
        self.assertEqual(Document.select().count(), 2)

    def test_document_detail_update_attachments(self):
        idx = Index.create(name='idx')
        doc = idx.index('test doc', foo='bar', nug='baze')
        doc.attach('foo.jpg', 'empty')
        url = '/documents/%s/' % doc.docid

        json_data = json.dumps({'content': 'test doc-edited'})
        response = self.app.post(url, data={
            'data': json_data,
            'file_0': (BytesIO(b'xx'), 'foo.jpg'),
            'file_1': (BytesIO(b'yy'), 'foo2.jpg')})

        resp_data = json_load(response.data)
        a1 = Attachment.get(Attachment.filename == 'foo.jpg')
        a2 = Attachment.get(Attachment.filename == 'foo2.jpg')
        a1_data = {
            'mimetype': 'image/jpeg',
            'data_length': 2,
            'data': '/documents/%s/attachments/foo.jpg/download/' % doc.docid,
            'timestamp': str(a1.timestamp),
            'filename': 'foo.jpg'}
        a2_data = {
            'mimetype': 'image/jpeg',
            'data_length': 2,
            'data': '/documents/%s/attachments/foo2.jpg/download/' % doc.docid,
            'timestamp': str(a2.timestamp),
            'filename': 'foo2.jpg'}
        self.assertEqual(resp_data, {
            'attachments': [a1_data, a2_data],
            'content': 'test doc-edited',
            'id': 1,
            'identifier': None,
            'indexes': ['idx'],
            'metadata': {'foo': 'bar', 'nug': 'baze'}})

        self.assertEqual(Attachment.select().count(), 2)
        self.assertEqual(BlobData.select().count(), 3)

        # Existing file updated, new file added.
        foo, foo2 = Attachment.select().order_by(Attachment.filename)
        self.assertEqual(foo.blob.data, b'xx')
        self.assertEqual(foo2.blob.data, b'yy')

    def test_document_detail_delete(self):
        idx = Index.create(name='idx')
        alt_idx = Index.create(name='alt-idx')

        d1 = idx.index('doc 1', k1='v1', k2='v2')
        d2 = idx.index('doc 2', k3='v3')
        d2.attach('foo.jpg', 'bar')

        alt_idx.add_to_index(d1)
        alt_idx.add_to_index(d2)

        self.assertEqual(Metadata.select().count(), 3)
        self.assertEqual(Attachment.select().count(), 1)

        response = self.app.delete('/documents/%s/' % d2.get_id())
        data = json_load(response.data)
        self.assertEqual(data, {'success': True})

        self.assertEqual(Metadata.select().count(), 2)
        self.assertEqual(Attachment.select().count(), 0)

        response = self.app.delete('/documents/%s/' % d2.get_id())
        self.assertEqual(response.status_code, 404)

        self.assertEqual(Document.select().count(), 1)
        self.assertEqual(IndexDocument.select().count(), 2)
        self.assertEqual(
            [d.get_id() for d in idx.documents],
            [d1.get_id()])
        self.assertEqual(
            [d.get_id() for d in alt_idx.documents],
            [d1.get_id()])

    def test_attachment_views(self):
        idx = Index.create(name='idx')
        doc = idx.index('doc 1')
        doc.attach('foo.jpg', 'x')
        doc.attach('bar.png', 'x')
        Attachment.update(timestamp='2016-01-02 03:04:05').execute()

        resp = self.app.get('/documents/1/attachments/')
        resp_data = json_load(resp.data)
        self.assertEqual(resp_data['attachments'], [
            {
                'mimetype': 'image/png',
                'timestamp': '2016-01-02 03:04:05',
                'data_length': 1,
                'filename': 'bar.png',
                'document': '/documents/1/',
                'data': '/documents/1/attachments/bar.png/download/',
            },
            {
                'mimetype': 'image/jpeg',
                'timestamp': '2016-01-02 03:04:05',
                'data_length': 1,
                'filename': 'foo.jpg',
                'document': '/documents/1/',
                'data': '/documents/1/attachments/foo.jpg/download/',
            },
        ])

        resp = self.app.get('/documents/1/attachments/foo.jpg/')
        resp_data = json_load(resp.data)
        self.assertEqual(resp_data, {
            'mimetype': 'image/jpeg',
            'timestamp': '2016-01-02 03:04:05',
            'data_length': 1,
            'filename': 'foo.jpg',
            'document': '/documents/1/',
            'data': '/documents/1/attachments/foo.jpg/download/',
        })

        resp = self.app.delete('/documents/1/attachments/foo.jpg/')
        self.assertEqual(Attachment.select().count(), 1)

        resp = self.app.post('/documents/1/attachments/bar.png/', data={
            'data': '',
            'file_0': (BytesIO(b'zz'), 'bar.png')})
        resp_data = json_load(resp.data)
        self.assertEqual(resp_data['data_length'], 2)

        resp = self.app.get('/documents/1/attachments/bar.png/download/')
        self.assertEqual(resp.data, b'zz')

    def search(self, index, query, page=1, **filters):
        filters.setdefault('ranking', SEARCH_BM25)
        params = urlencode(dict(filters, q=query, page=page))
        response = self.app.get('/%s/?%s' % (index, params))
        return json_load(response.data)

    def test_search(self):
        idx = Index.create(name='idx')
        phrases = ['foo', 'bar', 'baz', 'nug nugs', 'blah nuggie foo', 'huey',
                   'zaizee']
        for phrase in phrases:
            idx.index('document %s' % phrase, special=True)

        for i in range(10):
            idx.index('document %s' % i, special=False)

        response = self.search('idx', 'docum*')
        self.assertEqual(response['page'], 1)
        self.assertEqual(response['pages'], 2)
        self.assertEqual(len(response['documents']), 10)

        response = self.search('idx', 'document', 2)
        self.assertEqual(len(response['documents']), 7)

        response = self.search('idx', 'doc* nug*')
        self.assertEqual(response['page'], 1)
        self.assertEqual(response['pages'], 1)
        self.assertEqual(len(response['documents']), 2)
        doc1, doc2 = response['documents']

        self.assertEqual(doc1, {
            'attachments': [],
            'content': 'document nug nugs',
            'id': doc1['id'],
            'identifier': None,
            'indexes': ['idx'],
            'metadata': {'special': 'True'},
            'score': doc1['score']})

        self.assertEqual(round(doc1['score'], 4), -2.1995)

        self.assertEqual(doc2, {
            'attachments': [],
            'content': 'document blah nuggie foo',
            'id': doc2['id'],
            'identifier': None,
            'indexes': ['idx'],
            'metadata': {'special': 'True'},
            'score': doc2['score']})

        self.assertEqual(round(doc2['score'], 4), -1.2948)

        response = self.search('idx', 'missing')
        self.assertEqual(len(response['documents']), 0)

        response = self.search('idx', 'nug', ranking='bm25')
        doc = response['documents'][0]
        self.assertEqual(doc['content'], 'document nug nugs')
        self.assertEqual(round(doc['score'], 3), -2.891)

    def test_search_filters(self):
        idx = Index.create(name='idx')
        data = (
            ('huey document', {'name': 'huey', 'kitty': 'yes'}),
            ('zaizee document', {'name': 'zaizee', 'kitty': 'yes'}),
            ('little huey bear', {'name': 'huey', 'kitty': 'yes'}),
            ('uncle huey', {'kitty': 'no'}),
            ('michael nuggie document', {'name': 'mickey', 'kitty': 'no'}),
        )
        for content, metadata in data:
            idx.index(content, **metadata)

        def assertResults(query, metadata, expected):
            results = self.search('idx', query, **metadata)
            content = [document['content']
                       for document in results['documents']]
            self.assertEqual(content, expected)

        results = ['huey document', 'uncle huey', 'little huey bear']

        assertResults('huey', {}, results)
        assertResults(
            'huey',
            {'kitty': 'yes'},
            ['huey document', 'little huey bear'])
        assertResults(
            'huey',
            {'kitty': 'yes', 'name': 'huey'},
            ['huey document', 'little huey bear'])
        assertResults(
            'docu*',
            {'kitty': 'yes'},
            ['huey document', 'zaizee document'])

    def test_query_count(self):
        idx_a = Index.create(name='idx-a')
        idx_b = Index.create(name='idx-b')
        phrases = ['foo', 'bar', 'baze', 'nug', 'nuggie']
        for phrase in phrases:
            phrase = 'document ' + phrase
            doc = idx_a.index(phrase)
            idx_b.index(phrase, doc, foo='bar', baze='nug')

        for idx in ['idx-a', 'idx-b']:
            for query in ['nug', 'nug*', 'document', 'missing']:
                with assert_query_count(9):
                    # 1. Get index.
                    # 2. Get # of docs in index.
                    # 3. Prefetch indexes.
                    # 4. Prefetch index documents.
                    # 5. Prefetch metadata
                    # 6. Fetch documents (top of prefetch).
                    # 7. COUNT(*) for pagination.
                    # 8. COUNT(*) for pagination.
                    self.search(idx, query)

                with assert_query_count(9):
                    self.search(idx, query, foo='bar')

        with assert_query_count(9):
            # Same as above.
            data = self.app.get('/idx-a/').data

        with assert_query_count(8):
            # Same as above minus first query for index.
            self.app.get('/documents/')

        for i in range(10):
            Index.create(name='idx-%s' % i)

        with assert_query_count(2):
            # 2 queries, one for list, one for pagination.
            self.app.get('/')

    def test_authentication(self):
        Index.create(name='idx')

        app.config['AUTHENTICATION'] = 'test'
        resp = self.app.get('/')
        self.assertEqual(resp.status_code, 401)
        self.assertEqual(resp.data.decode('utf-8'), 'Invalid API key')

        resp = self.app.get('/?key=tesss')
        self.assertEqual(resp.status_code, 401)

        resp = self.app.get('/', headers={'key': 'tesss'})
        self.assertEqual(resp.status_code, 401)

        resp = self.app.get('/?key=test')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(json_load(resp.data)['indexes'], [{
            'id': 1, 'name': 'idx', 'document_count': 0, 'documents': '/idx/'
        }])

        resp = self.app.get('/', headers={'key': 'test'})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(json_load(resp.data)['indexes'], [{
            'id': 1, 'name': 'idx', 'document_count': 0, 'documents': '/idx/'
        }])


def main():
    option_parser = get_option_parser()
    options, args = option_parser.parse_args()
    unittest.main(argv=sys.argv, verbosity=not options.quiet and 2 or 0)


if __name__ == '__main__':
    main()
