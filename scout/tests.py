import json
import optparse
import sys
import unittest
from io import BytesIO
from urllib.parse import urlencode

from playhouse.sqlite_ext import *
from playhouse.test_utils import assert_query_count

from scout.client import Scout
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

    def test_search_with_ranking_not_treated_as_metadata(self):
        self.populate()
        # 'ranking' is not passed into _build_filter_expression, so the results
        # work as expected.
        results = list(engine.search(
            'testing', index=self.index, ranking='bm25', k1='k1-1', page=1))
        self.assertTrue(len(results) > 0)

    def test_apply_sorting_string_ordering(self):
        self.populate()
        # Should not raise or silently ignore the ordering.
        results = list(engine.search(
            'testing', index=self.index, ordering='-id'))
        ids = [doc.rowid for doc in results]
        self.assertEqual(ids, sorted(ids, reverse=True))

        results2 = list(engine.search(
            'testing', index=self.index, ordering='id'))
        ids2 = [doc.rowid for doc in results2]
        self.assertEqual(ids2, sorted(ids2))

    def test_metadata_filter_like_exprs(self):
        self.populate()
        results = list(engine.search(
            'testing', index=self.index, name__contains='gie'))
        names = sorted(set(doc.metadata['name'] for doc in results))
        self.assertEqual(names, ['googie', 'nuggie zaizee'])

        results = list(engine.search(
            'testing', index=self.index, name__startswith='nug'))
        names = sorted(set(doc.metadata['name'] for doc in results))
        self.assertEqual(names, ['nuggie zaizee'])

        results = list(engine.search(
            'testing', index=self.index, name__endswith='key'))
        names = sorted(set(doc.metadata['name'] for doc in results))
        self.assertEqual(names, ['huey mickey'])


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

    def test_detach_cleans_up_orphaned_blobs(self):
        idx = Index.create(name='idx')
        doc = idx.index('test')
        doc.attach('file1.txt', b'unique content')
        self.assertEqual(BlobData.select().count(), 1)

        doc.detach('file1.txt')
        self.assertEqual(Attachment.select().count(), 0)
        self.assertEqual(BlobData.select().count(), 0)

    def test_detach_preserves_shared_blobs(self):
        idx = Index.create(name='idx')
        doc1 = idx.index('doc1')
        doc2 = idx.index('doc2')
        # Same content → same hash → same BlobData row.
        doc1.attach('a.txt', b'shared data')
        doc2.attach('b.txt', b'shared data')
        self.assertEqual(BlobData.select().count(), 1)

        doc1.detach('a.txt')
        self.assertEqual(Attachment.select().count(), 1)
        # Blob still referenced by doc2's attachment.
        self.assertEqual(BlobData.select().count(), 1)

        doc2.detach('b.txt')
        self.assertEqual(BlobData.select().count(), 0)


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
            'mimetype': 'text/plain',
            'timestamp': str(a1.timestamp),
            'filename': 'test1.txt'}
        a2_data = {
            'data': '/documents/1/attachments/test2.jpg/download/',
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
            'next_url': None,
            'previous_url': None,
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

    def test_document_detail_query_count_with_attachments(self):
        idx = Index.create(name='idx')
        doc = idx.index('test doc')
        for i in range(10):
            doc.attach('a%s.txt' % i, b'aaa')

        with assert_query_count(4):
            # 1. Get document
            # 2. Get attachments
            # 3. Get metadata
            # 4. Get indexes
            response = self.app.get('/documents/%s/' % doc.get_id())

        data = json_load(response.data)
        self.assertEqual(len(data['attachments']), 10)

        with assert_query_count(8) as ct:
            # Doc count
            # Prefetch doc index many-to-many
            # Prefetch index names
            # Prefetch metadata
            # Prefetch attachments
            # Get page
            # Get filtered count
            # Pagination
            response = self.app.get('/documents/')

        data = json_load(response.data)

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

    def test_parse_post_rejects_unknown_keys_with_none_value(self):
        idx = Index.create(name='idx')
        response = self.post_json('/documents/', {
            'content': 'test',
            'index': 'idx',
            'evil_key': None})
        self.assertIn('error', response)
        self.assertIn('evil_key', response['error'])
        self.assertEqual(Document.select().count(), 0)

    def test_parse_post_rejects_unknown_keys_with_empty_string(self):
        idx = Index.create(name='idx')
        response = self.post_json('/documents/', {
            'content': 'test',
            'index': 'idx',
            'bad': ''})
        self.assertIn('error', response)
        self.assertIn('bad', response['error'])

    def test_document_detail_get(self):
        idx = Index.create(name='idx')
        doc = idx.index('test doc', foo='bar')
        alt_doc = idx.index('alt doc')

        response = self.app.get('/documents/%s/' % doc.rowid)
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

    def test_create_with_existing_identifier_updates(self):
        idx = Index.create(name='idx')
        doc = idx.index('original', identifier='ident-1')
        doc.metadata = {'k': 'v'}

        response = self.post_json('/documents/', {
            'content': 'updated via create',
            'index': 'idx',
            'identifier': 'ident-1',
            'metadata': {'k': 'new-v'}})

        self.assertEqual(Document.select().count(), 1)
        self.assertEqual(response['content'], 'updated via create')
        self.assertEqual(response['metadata'], {'k': 'new-v'})

    def test_document_detail_update_attachments(self):
        idx = Index.create(name='idx')
        doc = idx.index('test doc', foo='bar', nug='baze')
        doc.attach('foo.jpg', 'empty')
        url = '/documents/%s/' % doc.rowid

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
            'data': '/documents/%s/attachments/foo.jpg/download/' % doc.rowid,
            'timestamp': str(a1.timestamp),
            'filename': 'foo.jpg'}
        a2_data = {
            'mimetype': 'image/jpeg',
            'data': '/documents/%s/attachments/foo2.jpg/download/' % doc.rowid,
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

    def test_document_delete_cleans_orphaned_blobs(self):
        idx = Index.create(name='idx')
        doc = idx.index('doc with files')
        doc.attach('a.txt', b'data-a')
        doc.attach('b.txt', b'data-b')
        self.assertEqual(BlobData.select().count(), 2)

        response = self.app.delete('/documents/%s/' % doc.get_id())
        self.assertEqual(json_load(response.data), {'success': True})
        self.assertEqual(Attachment.select().count(), 0)
        self.assertEqual(BlobData.select().count(), 0)

    def test_document_delete_preserves_shared_blobs(self):
        idx = Index.create(name='idx')
        d1 = idx.index('doc1')
        d2 = idx.index('doc2')
        d1.attach('f.txt', b'shared')
        d2.attach('g.txt', b'shared')
        self.assertEqual(BlobData.select().count(), 1)

        self.app.delete('/documents/%s/' % d1.get_id())
        # Blob still referenced by d2.
        self.assertEqual(BlobData.select().count(), 1)

    def test_validate_indexes_empty_list_clears(self):
        idx = Index.create(name='idx')
        doc = idx.index('test')
        url = '/documents/%s/' % doc.get_id()

        # Explicitly clear indexes.
        response = self.post_json(url, {'indexes': []})
        doc_db = (Document.all()
                  .where(Document._meta.primary_key == doc.get_id())
                  .get())
        self.assertEqual(list(doc_db.get_indexes()), [])

    def test_validate_indexes_absent_key_preserves(self):
        idx = Index.create(name='idx')
        doc = idx.index('test')
        url = '/documents/%s/' % doc.get_id()

        # Omitting indexes will preserve existing indexes.
        response = self.post_json(url, {'content': 'updated'})
        doc_db = (Document.all()
                  .where(Document._meta.primary_key == doc.get_id())
                  .get())
        self.assertEqual([i.name for i in doc_db.get_indexes()], ['idx'])

    def test_update_document_empty_content(self):
        idx = Index.create(name='idx')
        doc = idx.index('original content')
        url = '/documents/%s/' % doc.get_id()

        self.post_json(url, {'content': ''})
        doc_db = (Document.all()
                  .where(Document._meta.primary_key == doc.get_id())
                  .get())
        self.assertEqual(doc_db.content, '')

    def test_update_document_empty_identifier(self):
        idx = Index.create(name='idx')
        doc = idx.index('text', identifier='old-id')
        url = '/documents/%s/' % doc.get_id()

        self.post_json(url, {'identifier': 'new-id'})
        doc_db = (Document.all()
                  .where(Document._meta.primary_key == doc.get_id())
                  .get())
        self.assertEqual(doc_db.identifier, 'new-id')

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

        self.assertEqual(round(doc1['score'], 4), -2.2675)

        self.assertEqual(doc2, {
            'attachments': [],
            'content': 'document blah nuggie foo',
            'id': doc2['id'],
            'identifier': None,
            'indexes': ['idx'],
            'metadata': {'special': 'True'},
            'score': doc2['score']})

        self.assertEqual(round(doc2['score'], 4), -1.3588)

        response = self.search('idx', 'missing')
        self.assertEqual(len(response['documents']), 0)

        response = self.search('idx', 'nug', ranking='bm25')
        doc = response['documents'][0]
        self.assertEqual(doc['content'], 'document nug nugs')
        self.assertEqual(round(doc['score'], 3), -2.98)

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

    def test_document_count_filtered_by_index(self):
        # document_count at /documents/ should reflect the index filter.
        idx_a = Index.create(name='idx-a')
        idx_b = Index.create(name='idx-b')
        for i in range(5):
            idx_a.index('doc-a-%d' % i)
        for i in range(3):
            idx_b.index('doc-b-%d' % i)

        # No filter - total across all indexes.
        response = self.app.get('/documents/')
        data = json_load(response.data)
        self.assertEqual(data['document_count'], 8)

        # Filter to idx-a only.
        response = self.app.get('/documents/?index=idx-a')
        data = json_load(response.data)
        self.assertEqual(data['document_count'], 5)

        # Filter to idx-b only.
        response = self.app.get('/documents/?index=idx-b')
        data = json_load(response.data)
        self.assertEqual(data['document_count'], 3)

        # Filter to both - all 8.
        response = self.app.get('/documents/?index=idx-a&index=idx-b')
        data = json_load(response.data)
        self.assertEqual(data['document_count'], 8)

    def test_document_count_shared_document_not_double_counted(self):
        # A document in two filtered indexes should be counted once.
        idx_a = Index.create(name='idx-a')
        idx_b = Index.create(name='idx-b')
        doc = idx_a.index('shared doc')
        idx_b.add_to_index(doc)
        idx_a.index('a-only')

        response = self.app.get('/documents/?index=idx-a&index=idx-b')
        data = json_load(response.data)
        # 2 documents total, not 3.
        self.assertEqual(data['document_count'], 2)

    def test_pagination_urls_in_document_list(self):
        idx = Index.create(name='idx')
        for i in range(25):
            idx.index('doc %d' % i)

        # Page 1 of 3 (paginate_by=10).
        response = self.app.get('/documents/')
        data = json_load(response.data)
        self.assertEqual(data['page'], 1)
        self.assertEqual(data['pages'], 3)
        self.assertTrue(data['next_url'].endswith('/documents/?page=2'))
        self.assertIsNone(data['previous_url'])

        # Page 2.
        response = self.app.get('/documents/?page=2')
        data = json_load(response.data)
        self.assertEqual(data['page'], 2)
        self.assertIsNotNone(data['next_url'])
        self.assertTrue(data['next_url'].endswith('/documents/?page=3'))
        self.assertIsNotNone(data['previous_url'])
        self.assertTrue(data['previous_url'].endswith('/documents/?page=1'))

        # Page 3 (last).
        response = self.app.get('/documents/?page=3')
        data = json_load(response.data)
        self.assertEqual(data['page'], 3)
        self.assertIsNone(data['next_url'])
        self.assertIsNotNone(data['previous_url'])
        self.assertTrue(data['previous_url'].endswith('/documents/?page=2'))

    def test_pagination_urls_preserve_query_params(self):
        idx = Index.create(name='idx')
        for i in range(25):
            idx.index('document %d' % i, color='red')

        response = self.app.get('/idx/?q=document&color=red')
        data = json_load(response.data)
        next_url = data['next_url']
        self.assertIn('page=2', next_url)
        self.assertIn('q=document', next_url)
        self.assertIn('color=red', next_url)

    def test_pagination_urls_single_page(self):
        idx = Index.create(name='idx')
        idx.index('only doc')

        response = self.app.get('/idx/')
        data = json_load(response.data)
        self.assertIsNone(data['next_url'])
        self.assertIsNone(data['previous_url'])

    def test_pagination_urls_in_index_list(self):
        for i in range(25):
            Index.create(name='idx-%02d' % i)

        response = self.app.get('/')
        data = json_load(response.data)
        self.assertIn('next_url', data)
        self.assertIn('previous_url', data)

    def test_pagination_urls_in_attachment_list(self):
        idx = Index.create(name='idx')
        doc = idx.index('doc')
        for i in range(15):
            doc.attach('file_%02d.txt' % i, b'data')

        response = self.app.get('/documents/%s/attachments/' % doc.get_id())
        data = json_load(response.data)
        self.assertIn('next_url', data)
        self.assertIn('previous_url', data)

    def test_global_attachment_list(self):
        idx = Index.create(name='idx')
        d1 = idx.index('doc 1')
        d2 = idx.index('doc 2')
        d1.attach('photo.jpg', b'jpeg-data')
        d1.attach('notes.txt', b'text-data')
        d2.attach('logo.png', b'png-data')

        response = self.app.get('/attachments/')
        data = json_load(response.data)
        self.assertEqual(data['page'], 1)
        filenames = sorted(a['filename'] for a in data['attachments'])
        self.assertEqual(filenames, ['logo.png', 'notes.txt', 'photo.jpg'])

    def test_global_attachment_filter(self):
        idx = Index.create(name='idx')
        idx2 = Index.create(name='idx2')

        doc = idx.index('doc')
        doc.attach('photo.jpg', b'jpeg')
        doc.attach('notes.txt', b'text')
        doc.attach('logo.png', b'png')

        doc2 = idx2.index('doc')
        doc2.attach('d2.jpg', b'jpeg2')
        doc2.attach('notes.txt', b'text2')

        response = self.app.get('/attachments/?mimetype=image/jpeg')
        data = json_load(response.data)
        self.assertEqual(len(data['attachments']), 2)
        self.assertEqual(sorted([a['filename'] for a in data['attachments']]),
                         ['d2.jpg', 'photo.jpg'])

        response = self.app.get('/attachments/?filename=notes.txt')
        attachments = json_load(response.data)['attachments']
        self.assertEqual(len(attachments), 2)

        attachments.sort(key=lambda a: a['timestamp'])
        self.assertEqual([a['filename'] for a in attachments],
                         ['notes.txt', 'notes.txt'])
        self.assertEqual([a['data'] for a in attachments], [
            '/documents/%s/attachments/notes.txt/download/' % doc.rowid,
            '/documents/%s/attachments/notes.txt/download/' % doc2.rowid])

        response = self.app.get('/attachments/?index=idx2')
        data = json_load(response.data)
        self.assertEqual(len(data['attachments']), 2)
        self.assertEqual(sorted([a['filename'] for a in data['attachments']]),
                         ['d2.jpg', 'notes.txt'])

        response = self.app.get(
            '/attachments/?index=idx&index=idx2')
        data = json_load(response.data)
        self.assertEqual(len(data['attachments']), 5)

        response = self.app.get(
            '/attachments/?index=idx-not-here&index=idx-also-not-here')
        data = json_load(response.data)
        self.assertEqual(len(data['attachments']), 0)

    def test_global_attachment_ordering(self):
        idx = Index.create(name='idx')
        doc = idx.index('doc')
        doc.attach('b.txt', b'b')
        doc.attach('a.txt', b'a')
        doc.attach('c.txt', b'c')

        response = self.app.get('/attachments/')
        data = json_load(response.data)
        filenames = [a['filename'] for a in data['attachments']]
        self.assertEqual(filenames, ['a.txt', 'b.txt', 'c.txt'])

        response = self.app.get('/attachments/?ordering=-filename')
        data = json_load(response.data)
        filenames = [a['filename'] for a in data['attachments']]
        self.assertEqual(filenames, ['c.txt', 'b.txt', 'a.txt'])

    def test_global_attachment_empty(self):
        response = self.app.get('/attachments/')
        data = json_load(response.data)
        self.assertEqual(data['attachments'], [])
        self.assertEqual(data['page'], 1)
        self.assertEqual(data['pages'], 0)

    def test_global_attachment_list_requires_auth(self):
        app.config['AUTHENTICATION'] = 'secret'
        try:
            response = self.app.get('/attachments/')
            self.assertEqual(response.status_code, 401)

            response = self.app.get('/attachments/?key=secret')
            self.assertEqual(response.status_code, 200)
        finally:
            app.config['AUTHENTICATION'] = None


class FlaskScout(Scout):
    def __init__(self, flask_app, key=None):
        self.flask_client = flask_app.test_client()
        self.key = key
        self.endpoint = ''

    def _headers(self, extras=None):
        headers = {}
        if self.key:
            headers['key'] = self.key
        if extras:
            headers.update(extras)
        return headers

    def get_raw(self, url, **kwargs):
        if kwargs:
            if '?' not in url:
                url += '?'
            url += urlencode(kwargs, True)
        resp = self.flask_client.get(url, headers=self._headers())
        return resp.data

    def post_json(self, url, data=None):
        resp = self.flask_client.post(
            url,
            data=json.dumps(data or {}),
            headers=self._headers({'Content-Type': 'application/json'}))
        return json_load(resp.data)

    def post_files(self, url, json_data, files=None):
        form_data = {'data': json.dumps(json_data or {})}
        for i, (filename, file_obj) in enumerate(files.items()):
            try:
                raw = file_obj.read()
            except AttributeError:
                raw = bytes(file_obj)
            form_data['file_%s' % i] = (BytesIO(raw), filename)
        resp = self.flask_client.post(url, data=form_data,
                                      headers=self._headers())
        return json_load(resp.data)

    def delete(self, url):
        resp = self.flask_client.delete(url, headers=self._headers())
        return json_load(resp.data)


class TestScoutClient(BaseTestCase):
    def setUp(self):
        super(TestScoutClient, self).setUp()
        app.config['AUTHENTICATION'] = None
        self.scout = FlaskScout(app)

    def test_create_get_indexes(self):
        self.scout.create_index('idx-a')
        self.scout.create_index('idx-b')
        indexes = self.scout.get_indexes()
        names = [idx['name'] for idx in indexes]
        self.assertEqual(sorted(names), ['idx-a', 'idx-b'])

    def test_get_index_detail(self):
        self.scout.create_index('my-idx')
        detail = self.scout.get_index('my-idx')
        self.assertEqual(detail['name'], 'my-idx')
        self.assertEqual(detail['document_count'], 0)
        self.assertEqual(detail['page'], 1)
        self.assertEqual(detail['pages'], 0)

    def test_rename_index(self):
        self.scout.create_index('old-name')
        result = self.scout.rename_index('old-name', 'new-name')
        self.assertEqual(result['name'], 'new-name')
        names = [idx['name'] for idx in self.scout.get_indexes()]
        self.assertEqual(names, ['new-name'])

    def test_delete_index(self):
        self.scout.create_index('doomed')
        self.scout.delete_index('doomed')
        self.assertEqual(self.scout.get_indexes(), [])

    def test_delete_index_preserves_documents(self):
        self.scout.create_index('idx')
        self.scout.create_document('hello world', 'idx')
        self.scout.delete_index('idx')
        self.assertEqual(Document.select().count(), 1)

    def test_create_document_single_index(self):
        idx = self.scout.create_index('idx')
        doc = self.scout.create_document('test content', 'idx', k1='v1')
        self.assertEqual(doc['content'], 'test content')
        self.assertEqual(doc['indexes'], ['idx'])
        self.assertEqual(doc['metadata'], {'k1': 'v1'})

        self.assertEqual(self.scout.get_index('idx'), {
            'document_count': 1,
            'documents': [doc],
            'filtered_count': 1,
            'filters': {},
            'id': idx['id'],
            'name': 'idx',
            'ordering': [],
            'next_url': None,
            'page': 1,
            'pages': 1,
            'previous_url': None})

    def test_create_document_multiple_indexes(self):
        self.scout.create_index('a')
        self.scout.create_index('b')
        doc = self.scout.create_document('multi', ['a', 'b'])
        self.assertEqual(sorted(doc['indexes']), ['a', 'b'])

        rdoc = self.scout.get_document(doc['id'])
        self.assertEqual(doc, rdoc)

    def test_create_document_with_identifier(self):
        self.scout.create_index('idx')
        doc = self.scout.create_document('content', 'idx',
                                         identifier='custom-id')
        self.assertEqual(doc['identifier'], 'custom-id')

    def test_get_documents_filtered_by_multiple_indexes(self):
        self.scout.create_index('a')
        self.scout.create_index('b')
        self.scout.create_index('c')
        self.scout.create_document('in a', 'a')
        self.scout.create_document('in b', 'b')
        self.scout.create_document('in c', 'c')

        results = self.scout.get_documents(index=['a', 'b'])
        self.assertEqual(results['document_count'], 2)
        self.assertEqual(len(results['documents']), 2)
        contents = sorted(d['content'] for d in results['documents'])
        self.assertEqual(contents, ['in a', 'in b'])

    def test_get_document(self):
        self.scout.create_index('idx')
        created = self.scout.create_document('hello', 'idx')
        fetched = self.scout.get_document(created['id'])
        self.assertEqual(fetched['content'], 'hello')
        self.assertEqual(fetched['id'], created['id'])

    def test_update_document_content(self):
        self.scout.create_index('idx')
        doc = self.scout.create_document('original', 'idx')

        updated = self.scout.update_document(
            document_id=doc['id'], content='modified')
        self.assertEqual(updated['content'], 'modified')

        fetched = self.scout.get_document(doc['id'])
        self.assertEqual(fetched['content'], 'modified')

    def test_update_document_by_identifier(self):
        self.scout.create_index('idx')
        doc = self.scout.create_document('text', 'idx', identifier='my-id')
        updated = self.scout.update_document('my-id', content='updated text')
        self.assertEqual(updated['content'], 'updated text')
        self.assertEqual(updated['identifier'], 'my-id')

        fetched = self.scout.get_document(doc['id'])
        self.assertEqual(fetched['content'], 'updated text')

    def test_update_document_metadata(self):
        self.scout.create_index('idx')
        doc = self.scout.create_document('text', 'idx', color='red')
        self.assertEqual(doc['metadata'], {'color': 'red'})
        updated = self.scout.update_document(
            document_id=doc['id'], metadata={'color': 'blue', 'size': 'lg'})
        self.assertEqual(updated['metadata'], {'color': 'blue', 'size': 'lg'})

        fetched = self.scout.get_document(document_id=doc['id'])
        self.assertEqual(fetched['metadata'], updated['metadata'])

    def test_update_document_clear_metadata(self):
        self.scout.create_index('idx')
        doc = self.scout.create_document('text', 'idx', foo='bar')
        updated = self.scout.update_document(
            document_id=doc['id'], metadata={})
        self.assertEqual(updated['metadata'], {})

        fetched = self.scout.get_document(document_id=doc['id'])
        self.assertEqual(fetched['metadata'], {})

    def test_update_document_indexes(self):
        self.scout.create_index('a')
        self.scout.create_index('b')
        doc = self.scout.create_document('text', 'a')
        self.assertEqual(doc['indexes'], ['a'])
        updated = self.scout.update_document(
            document_id=doc['id'], indexes=['a', 'b'])
        self.assertEqual(sorted(updated['indexes']), ['a', 'b'])

        fetched = self.scout.get_document(document_id=doc['id'])
        self.assertEqual(sorted(fetched['indexes']), ['a', 'b'])

    def test_delete_document(self):
        self.scout.create_index('idx')
        doc = self.scout.create_document('bye', 'idx')
        result = self.scout.delete_document(doc['id'])
        self.assertEqual(result, {'success': True})
        self.assertEqual(Document.select().count(), 0)

    def test_validate_rowid_present(self):
        # Need rowid.
        self.assertRaises(ValueError, self.scout.delete_document)

        # Need rowid.
        self.assertRaises(ValueError, self.scout.get_document)

        self.scout.create_index('idx')
        doc = self.scout.create_document('text', 'idx')

        # Need data.
        self.assertRaises(
            ValueError,
            self.scout.update_document,
            document_id=doc['id'])

    def test_get_documents_list(self):
        self.scout.create_index('idx')
        for i in range(3):
            self.scout.create_document('doc %d' % i, 'idx')
        result = self.scout.get_documents()
        self.assertEqual(result['document_count'], 3)
        self.assertEqual(result['page'], 1)
        self.assertEqual(result['pages'], 1)
        self.assertEqual(len(result['documents']), 3)

        # Ensure results paginated.
        for i in range(10):
            self.scout.create_document('doc %d' % i, 'idx')

        result = self.scout.get_documents()
        self.assertEqual(result['document_count'], 13)
        self.assertEqual(result['page'], 1)
        self.assertEqual(result['pages'], 2)
        self.assertEqual(len(result['documents']), 10)

        # Get via index.
        result = self.scout.get_index('idx')
        self.assertEqual(result['document_count'], 13)
        self.assertEqual(result['page'], 1)
        self.assertEqual(result['pages'], 2)
        self.assertEqual(len(result['documents']), 10)

    def test_search_via_get_index(self):
        self.scout.create_index('idx')
        self.scout.create_document('alpha bravo charlie', 'idx')
        self.scout.create_document('delta echo foxtrot', 'idx')
        self.scout.create_document('bravo delta golf', 'idx')

        results = self.scout.get_index('idx', q='bravo')
        docs = results['documents']
        self.assertEqual(len(docs), 2)
        contents = sorted(d['content'] for d in docs)
        self.assertEqual(contents, [
            'alpha bravo charlie',
            'bravo delta golf'])

    def test_search_via_get_documents(self):
        self.scout.create_index('a')
        self.scout.create_index('b')
        self.scout.create_document('apple banana', 'a')
        self.scout.create_document('banana cherry', 'b')

        results = self.scout.get_documents(q='banana')
        self.assertEqual(len(results['documents']), 2)

        results = self.scout.get_documents(q='banana', index='a')
        self.assertEqual(len(results['documents']), 1)
        self.assertEqual(results['documents'][0]['content'], 'apple banana')

    def test_search_with_metadata_filter(self):
        self.scout.create_index('idx')
        self.scout.create_document('doc one', 'idx', color='red')
        self.scout.create_document('doc two', 'idx', color='blue')
        self.scout.create_document('doc three', 'idx', color='red')

        results = self.scout.get_index('idx', q='doc', color='red')
        self.assertEqual(sorted([d['content'] for d in results['documents']]),
                         ['doc one', 'doc three'])

    def test_search_with_ranking(self):
        self.scout.create_index('idx')
        self.scout.create_document('foo bar baz', 'idx')
        self.scout.create_document('foo foo foo', 'idx')

        results = self.scout.get_index('idx', q='foo', ranking='bm25')
        self.assertEqual(len(results['documents']), 2)
        for doc in results['documents']:
            self.assertIn('score', doc)

        results = self.scout.get_index('idx', q='foo', ranking='none')
        for doc in results['documents']:
            self.assertNotIn('score', doc)

    def test_attach_and_get_attachments(self):
        self.scout.create_index('idx')
        doc = self.scout.create_document('with file', 'idx')
        doc_id = doc['id']

        result = self.scout.attach_files(doc_id, {
            'hello.txt': BytesIO(b'hello world'),
        })
        self.assertEqual(len(result['attachments']), 1)
        self.assertEqual(result['attachments'][0]['filename'], 'hello.txt')

        attachments = self.scout.get_attachments(doc_id)
        self.assertEqual(len(attachments['attachments']), 1)
        att, = attachments['attachments']
        self.assertEqual(att['filename'], 'hello.txt')
        self.assertEqual(att['document'], '/documents/%d/' % doc_id)
        self.assertEqual(att['mimetype'], 'text/plain')

    def test_get_attachment_detail(self):
        self.scout.create_index('idx')
        doc = self.scout.create_document('doc', 'idx')
        self.scout.attach_files(doc['id'], {'pic.png': BytesIO(b'PNG\x00')})

        detail = self.scout.get_attachment(doc['id'], 'pic.png')
        self.assertEqual(detail['filename'], 'pic.png')
        self.assertEqual(detail['mimetype'], 'image/png')

    def test_upload_binary_file_with_crlf(self):
        self.scout.create_index('idx')
        evil_data = b'\r\n--boundary\r\nContent-Disposition: bad\r\n\r\nfake'
        doc = self.scout.create_document(
            'binary test', 'idx',
            identifier='evil-doc',
            attachments={'evil.bin': BytesIO(evil_data)})
        self.assertEqual(len(doc['attachments']), 1)

        downloaded = self.scout.download_attachment(doc['id'], 'evil.bin')
        self.assertEqual(downloaded, evil_data)

        downloaded = self.scout.download_attachment('evil-doc', 'evil.bin')
        self.assertEqual(downloaded, evil_data)

    def test_download_attachment(self):
        self.scout.create_index('idx')
        doc = self.scout.create_document('doc', 'idx')
        content = b'raw file bytes here\x00\x00\xff\xff'
        self.scout.attach_files(doc['id'], {'data.bin': BytesIO(content)})

        downloaded = self.scout.download_attachment(doc['id'], 'data.bin')
        self.assertEqual(downloaded, content)

    def test_detach_file(self):
        self.scout.create_index('idx')
        doc = self.scout.create_document('doc', 'idx')
        self.scout.attach_files(doc['id'], {'f.txt': BytesIO(b'x')})
        self.assertEqual(Attachment.select().count(), 1)

        result = self.scout.detach_file(doc['id'], 'f.txt')
        self.assertEqual(result, {'success': True})
        self.assertEqual(Attachment.select().count(), 0)

    def test_update_file(self):
        self.scout.create_index('idx')
        doc = self.scout.create_document('doc', 'idx')
        self.scout.attach_files(doc['id'], {'f.txt': BytesIO(b'old\xff')})

        self.scout.update_file(doc['id'], 'f.txt', BytesIO(b'new\xff'))
        downloaded = self.scout.download_attachment(doc['id'], 'f.txt')
        self.assertEqual(downloaded, b'new\xff')

    def test_create_document_with_attachments(self):
        self.scout.create_index('idx')
        doc = self.scout.create_document(
            'with attachment', 'idx',
            attachments={'readme.txt': BytesIO(b'read me')})
        self.assertEqual(len(doc['attachments']), 1)
        self.assertEqual(doc['attachments'][0]['filename'], 'readme.txt')

    def test_authentication_key_sent(self):
        app.config['AUTHENTICATION'] = 'my-secret'
        try:
            authed = FlaskScout(app, key='my-secret')
            authed.create_index('secure-idx')
            indexes = authed.get_indexes()
            self.assertEqual(len(indexes), 1)

            # Without key, should get 401 — the raw response is not JSON.
            no_key = FlaskScout(app, key=None)
            raw = no_key.get_raw('/')
            self.assertIn(b'Invalid API key', raw)
        finally:
            app.config['AUTHENTICATION'] = None

    def test_endpoint_normalization(self):
        from scout.client import Scout
        s1 = Scout('http://example.com/')
        self.assertEqual(s1.endpoint, 'http://example.com')

        s2 = Scout('http://example.com///')
        self.assertEqual(s2.endpoint, 'http://example.com')

        s3 = Scout('example.com:8000')
        self.assertEqual(s3.endpoint, 'http://example.com:8000')

    def test_full_lifecycle(self):
        self.scout.create_index('blog')

        doc = self.scout.create_document(
            'Python is great for web development',
            'blog',
            author='alice',
            published='true')
        doc_id = doc['id']

        # Search finds it.
        results = self.scout.get_index('blog', q='python')
        self.assertEqual(len(results['documents']), 1)

        # Update content.
        self.scout.update_document(
            document_id=doc_id,
            content='Python is excellent for web development')

        # Search with new term finds it.
        results = self.scout.get_index('blog', q='excellent')
        self.assertEqual(len(results['documents']), 1)

        # Old term still matches (stemming/FTS).
        results = self.scout.get_index('blog', q='python')
        self.assertEqual(len(results['documents']), 1)

        # Metadata filter works.
        results = self.scout.get_index('blog', q='python', author='alice')
        self.assertEqual(len(results['documents']), 1)
        results = self.scout.get_index('blog', q='python', author='bob')
        self.assertEqual(len(results['documents']), 0)

        # Delete.
        self.scout.delete_document(doc_id)
        results = self.scout.get_index('blog', q='python')
        self.assertEqual(len(results['documents']), 0)

    def test_search_attachments(self):
        self.scout.create_index('idx')
        self.scout.create_document(
            'with files', 'idx',
            attachments={
                'a.txt': BytesIO(b'aaa'),
                'b.jpg': BytesIO(b'bbb'),
            })

        results = self.scout.search_attachments()
        self.assertEqual(len(results['attachments']), 2)

        results = self.scout.search_attachments(mimetype='image/jpeg')
        self.assertEqual(len(results['attachments']), 1)
        self.assertEqual(results['attachments'][0]['filename'], 'b.jpg')

    def test_search_attachments_by_index(self):
        self.scout.create_index('a')
        self.scout.create_index('b')
        self.scout.create_document(
            'doc a', 'a', attachments={'fa.txt': BytesIO(b'a')})
        self.scout.create_document(
            'doc b', 'b', attachments={'fb.txt': BytesIO(b'b')})

        results = self.scout.search_attachments(index='a')
        self.assertEqual(len(results['attachments']), 1)
        self.assertEqual(results['attachments'][0]['filename'], 'fa.txt')


class FTS5TestCase(BaseTestCase):
    def setUp(self):
        super(FTS5TestCase, self).setUp()
        app.config['AUTHENTICATION'] = None
        self.app = app.test_client()
        self.index = Index.create(name='default')

    def _add(self, content, identifier=None, **metadata):
        return self.index.index(content=content, identifier=identifier,
                                **metadata)

    def _search(self, phrase, ranking=SEARCH_BM25, **k):
        results = engine.search(phrase, index=self.index, ranking=ranking, **k)
        return [doc.content for doc in results]

    def _http_search(self, phrase, **params):
        params['q'] = phrase
        params.setdefault('ranking', SEARCH_BM25)
        qs = urlencode(params, doseq=True)
        response = self.app.get('/default/?%s' % qs)
        return json_load(response.data), response.status_code

    def _http_search_docs(self, phrase, **params):
        params['q'] = phrase
        params['index'] = 'default'
        params.setdefault('ranking', SEARCH_BM25)
        qs = urlencode(params, doseq=True)
        response = self.app.get('/documents/?%s' % qs)
        return json_load(response.data), response.status_code

    def _contents(self, data):
        return [d['content'] for d in data['documents']]

    def assertCorpusResults(self, phrase, expected_indexes,
                            ranking=SEARCH_BM25):
        results = [doc.content for doc in
                   engine.search(phrase, index=self.index, ranking=ranking)]
        self.assertEqual(results, [self.corpus[i] for i in expected_indexes])


class TestScopeToContent(FTS5TestCase):
    """
    Verify that the ``identifier`` column is NOT searched.
    """
    def test_identifier_not_matched(self):
        self._add('the quick brown fox', identifier='secret-keyword-xyz')
        self.assertEqual(self._search('secret'), [])
        self.assertEqual(self._search('keyword'), [])
        self.assertEqual(self._search('xyz'), [])

    def test_content_still_matches(self):
        self._add('the quick brown fox', identifier='doc-001')
        self.assertEqual(self._search('quick'), ['the quick brown fox'])
        self.assertEqual(self._search('brown'), ['the quick brown fox'])

    def test_shared_term_in_both_columns(self):
        self._add('python tutorial for beginners', identifier='python tut')
        self.assertEqual(self._search('python'),
                         ['python tutorial for beginners'])

    def test_http_identifier_not_matched(self):
        self._add('secret formula', identifier='magic keyword')
        data, status = self._http_search('magic')
        self.assertEqual(status, 200)
        self.assertEqual(self._contents(data), [])

    def test_http_content_match(self):
        self._add('secret formula', identifier='magic keyword')
        data, status = self._http_search('secret')
        self.assertEqual(status, 200)
        self.assertEqual(self._contents(data), ['secret formula'])


class TestFTSQueries(FTS5TestCase):
    """
    Corpus:
        0: A faith is a necessity to a man. Woe to him who believes in nothing.
        1: All who call on God in true faith, earnestly from the heart, ...
        2: Be faithful in small things because it is in them that your ...
        3: Faith consists in believing when it is beyond the power of ...
        4: Faith has to do with things that are not seen and hope with ...
    """
    def setUp(self):
        super().setUp()
        for content in self.corpus:
            self._add(content)

    def test_bareword(self):
        self.assertCorpusResults('believe', [3, 0])
        self.assertCorpusResults('faith man', [0])
        self.assertCorpusResults('faith thing', [4, 2])

        # No result.
        self.assertCorpusResults('blah', [])

        # Case sensitivity.
        lower = self._search('faith')
        upper = self._search('FAITH')
        mixed = self._search('Faith')
        self.assertEqual(set(lower), set(upper))
        self.assertEqual(set(lower), set(mixed))

    def test_wildcard_returns_all(self):
        results = self._search('*')
        self.assertEqual(len(results), 5)

    def test_http_simple_term(self):
        data, status = self._http_search('believe')
        self.assertEqual(status, 200)
        self.assertEqual(len(data['documents']), 2)
        self.assertEqual(data['search_term'], 'believe')
        self.assertEqual(data['ranking'], 'bm25')

    def test_or(self):
        self.assertCorpusResults('man OR hope', [0, 4])
        self.assertCorpusResults('believe OR nothing', [0, 3])  # No dupes.

    def test_not(self):
        self.assertCorpusResults('believe NOT nothing', [3])
        self.assertCorpusResults('believe NOT believe', [])

    def test_explicit_and(self):
        self.assertCorpusResults('faith AND hope', [4])
        self.assertCorpusResults('faith AND thing', [4, 2])
        self.assertCorpusResults('thing AND faith', [4, 2])

    def test_and_is_default(self):
        implicit = set(self._search('faith hope'))
        explicit = set(self._search('faith AND hope'))
        self.assertEqual(implicit, explicit)

    def test_combined_boolean(self):
        self.assertCorpusResults('(man OR hope) NOT believe', [4])

    def test_http_or(self):
        data, _ = self._http_search('man OR hope')
        self.assertEqual(len(data['documents']), 2)

    def test_http_not(self):
        data, _ = self._http_search('believe NOT nothing')
        self.assertEqual(len(data['documents']), 1)
        self.assertEqual(data['documents'][0]['content'], self.corpus[3])

    def test_exact_phrase(self):
        self.assertCorpusResults('"true faith"', [1])
        self.assertCorpusResults('"small things"', [2])
        self.assertCorpusResults('"things small"', [])
        self.assertCorpusResults('"faith hope"', [])

        self.assertCorpusResults('"true faith" OR "small things"', [2, 1])
        self.assertCorpusResults('"true faith" heart', [1])

    def test_http_phrase(self):
        data, _ = self._http_search('"true faith"')
        self.assertEqual(len(data['documents']), 1)

    def test_prefix_fa(self):
        self.assertCorpusResults('fa*', [2, 3, 0, 4, 1])
        self.assertCorpusResults('beli*', [3, 0])
        self.assertCorpusResults('fa* NOT hope', [2, 3, 0, 1])
        self.assertCorpusResults('xyz*', [])

    def test_http_prefix(self):
        data, _ = self._http_search('beli*')
        self.assertEqual(len(data['documents']), 2)

    def test_near_default_distance(self):
        self.assertCorpusResults('NEAR(faith man)', [0])
        self.assertCorpusResults('NEAR(true faith, 1)', [1])
        self.assertCorpusResults('NEAR(call desired, 2)', [])
        self.assertCorpusResults('NEAR(call desired, 25)', [1])

    def test_http_near(self):
        data, _ = self._http_search('NEAR(true faith, 1)')
        self.assertEqual(len(data['documents']), 1)

    def test_initial_token_match(self):
        self.assertCorpusResults('^faith', [3, 4])
        self.assertCorpusResults('^hope', [])
        self.assertCorpusResults('^a', [0])

    def test_http_initial_token(self):
        data, _ = self._http_search('^faith')
        self.assertEqual(len(data['documents']), 2)

    def test_stemming(self):
        for s in ('believe', 'believes', 'believing'):
            self.assertCorpusResults(s, [3, 0])

        for s in ('thing', 'things'):
            self.assertCorpusResults(s, [4, 2])

        for s in ('faithful', 'faith'):
            self.assertCorpusResults(s, [2, 3, 0, 4, 1])

    def test_complex_queries(self):
        self.assertCorpusResults('(hope OR man) AND faith', [0, 4])
        self.assertCorpusResults('"true faith" OR believe', [1, 3, 0])
        self.assertCorpusResults('beli* NOT nothing', [3])
        self.assertCorpusResults('NEAR(faith man, 5) OR hope', [0, 4])
        self.assertCorpusResults('^faith AND thing', [4])

    def test_http_complex(self):
        data, _ = self._http_search('(hope OR man) AND faith')
        self.assertEqual(len(data['documents']), 2)

    def test_bm25_ordering(self):
        results = engine.search('believe', index=self.index, ranking=SEARCH_BM25)
        results = list(results)
        self.assertEqual(len(results), 2)
        self.assertEqual(results[0].content, self.corpus[3])
        for doc in results:
            self.assertTrue(hasattr(doc, 'score'))
            self.assertLess(doc.score, 0)

    def test_ranking_none_suppresses_scores(self):
        data, _ = self._http_search('believe', ranking='none')
        for doc in data['documents']:
            self.assertNotIn('score', doc)

    def test_http_scores_present(self):
        data, _ = self._http_search('believe')
        for doc in data['documents']:
            self.assertIn('score', doc)
            self.assertIsInstance(doc['score'], float)

    def test_ordering_by_score(self):
        # By default sorted by score.
        data, _ = self._http_search('faith')
        scores = [d['score'] for d in data['documents']]
        self.assertEqual(scores, sorted(scores))

        data, _ = self._http_search('faith', ordering='-score')
        scores = [d['score'] for d in data['documents']]
        self.assertEqual(scores, sorted(scores, reverse=True))

    def test_ordering_by_data(self):
        data, _ = self._http_search('faith', ordering='id')
        ids = [d['id'] for d in data['documents']]
        self.assertEqual(ids, sorted(ids))

        data, _ = self._http_search('faith', ordering='-id')
        ids = [d['id'] for d in data['documents']]
        self.assertEqual(ids, sorted(ids, reverse=True))

        data, _ = self._http_search('faith', ordering='content')
        contents = self._contents(data)
        self.assertEqual(contents, sorted(contents))


class TestFTS5ErrorHandling(FTS5TestCase):
    """
    Malformed FTS5 queries should return a 400 with a helpful message,
    not a 500 Internal Server Error.
    """
    def setUp(self):
        super().setUp()
        for content in self.corpus:
            self._add(content)

    def test_empty_query_error(self):
        self.assertRaises(InvalidSearchException, engine.search, '')
        self.assertRaises(InvalidSearchException, engine.search, '   ')

    def test_search_errors(self):
        cases = (
            '"unbalanced',
            'OR',
            'NOT',
            'AND',
            'foo AND OR bar',
            '(foo AND bar',
            'foo AND bar)',
            '()',
            'NEAR()',
        )

        for case in cases:
            data, status = self._http_search(case)
            self.assertEqual(status, 400)
            self.assertIn('error', data)

            data, status = self._http_search_docs('"unbalanced')
            self.assertEqual(status, 400)
            self.assertIn('error', data)

    def test_valid_query_still_works(self):
        data, status = self._http_search('faith')
        self.assertEqual(status, 200)
        self.assertEqual(len(data['documents']), 5)


class TestFTS5Unicode(FTS5TestCase):
    def setUp(self):
        super().setUp()
        self._add('café au lait is a french drink')
        self._add('naïve bayes classifier')
        self._add('über cool engineering')

    def test_unicode(self):
        results = self._search('café')
        self.assertEqual(len(results), 1)
        self.assertIn('café', results[0])

        results = self._search('naïve')
        self.assertEqual(len(results), 1)

        results = self._search('über')
        self.assertEqual(len(results), 1)

    def test_http_unicode(self):
        data, status = self._http_search('café')
        self.assertEqual(status, 200)
        self.assertTrue(len(data['documents']) >= 1)


class TestFTS5WithMetadataFilters(FTS5TestCase):
    def setUp(self):
        super().setUp()
        topics = ['virtue', 'prayer', 'virtue', 'philosophy', 'philosophy']
        authors = ['hugo', 'luther', 'teresa', 'voltaire', 'unknown']
        for i, content in enumerate(self.corpus):
            self._add(content, topic=topics[i], author=authors[i])

    def test_search_with_eq_filter(self):
        results = self._search('faith', topic='virtue')
        self.assertEqual(len(results), 2)

    def test_search_with_multiple_filters(self):
        results = self._search('faith', topic='virtue', author='hugo')
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0], self.corpus[0])

    def test_search_with_ne_filter(self):
        results = self._search('believe', author__ne='hugo')
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0], self.corpus[3])

    def test_search_with_in_filter(self):
        results = self._search('faith', topic__in='virtue,prayer')
        self.assertEqual(len(results), 3)

    def test_search_with_contains_filter(self):
        results = self._search('faith', topic__contains='philos')
        self.assertEqual(len(results), 2)

    def test_http_search_with_filter(self):
        data, _ = self._http_search('faith', topic='virtue')
        self.assertEqual(len(data['documents']), 2)
        self.assertEqual(data['filters'], {'topic': ['virtue']})

    def test_http_search_with_multiple_filters(self):
        data, _ = self._http_search('faith', topic='virtue', author='hugo')
        self.assertEqual(len(data['documents']), 1)
        self.assertEqual(data['documents'][0]['content'], self.corpus[0])


class TestFTS5EdgeCases(FTS5TestCase):
    def test_search_empty_index(self):
        self.assertEqual(self._search('anything'), [])

    def test_duplicate_content(self):
        for _ in range(3):
            self._add('identical content here')
        self.assertEqual(len(self._search('identical')), 3)

    def test_search_after_update(self):
        doc = self._add('original content', identifier='doc1')
        self.assertEqual(len(self._search('original')), 1)

        self.index.index(content='updated content', document=doc,
                         identifier='doc1')
        self.assertEqual(self._search('original'), [])
        self.assertEqual(len(self._search('updated')), 1)

    def test_search_after_delete(self):
        doc = self._add('ephemeral content')
        self.assertEqual(len(self._search('ephemeral')), 1)
        doc.delete_instance()
        self.assertEqual(self._search('ephemeral'), [])

    def test_asterisk_with_filter(self):
        self._add('first document', tag='a')
        self._add('second document', tag='b')
        results = self._search('*', tag='a')
        self.assertEqual(len(results), 1)
        self.assertIn('first document', results)

    def test_search_multiple_indexes(self):
        idx2 = Index.create(name='other')
        doc = self._add('shared document')
        idx2.add_to_index(doc)

        self.assertEqual(len(self._search('shared')), 1)
        r2 = engine.search('shared', index=idx2, ranking=SEARCH_BM25)
        self.assertEqual(len(list(r2)), 1)


class TestFTS5HTTPIntegration(FTS5TestCase):
    def setUp(self):
        super().setUp()
        for i in range(25):
            self._add('document number %d about testing' % i, idx=str(i))

    def test_pagination(self):
        data, _ = self._http_search('testing')
        self.assertEqual(data['filtered_count'], 25)
        self.assertEqual(len(data['documents']), 10)

    def test_filtered_count(self):
        data, _ = self._http_search('testing', idx='5')
        self.assertEqual(data['filtered_count'], 1)

    def test_search_term_in_response(self):
        data, _ = self._http_search('testing')
        self.assertEqual(data['search_term'], 'testing')

    def test_ranking_in_response(self):
        data, _ = self._http_search('testing')
        self.assertEqual(data['ranking'], 'bm25')

    def test_ranking_none_in_response(self):
        data, _ = self._http_search('testing', ranking='none')
        self.assertEqual(data['ranking'], 'none')

    def test_invalid_ranking(self):
        data, status = self._http_search('testing', ranking='invalid')
        self.assertEqual(status, 400)

    def test_documents_endpoint_search(self):
        data, status = self._http_search_docs('testing')
        self.assertEqual(status, 200)
        self.assertEqual(data['filtered_count'], 25)


def main():
    option_parser = get_option_parser()
    options, args = option_parser.parse_args()
    unittest.main(argv=sys.argv, verbosity=not options.quiet and 2 or 0)


if __name__ == '__main__':
    main()
