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
from scout.constants import SEARCH_NONE
from scout.exceptions import InvalidRequestException
from scout.exceptions import InvalidSearchException
from scout.models import Attachment
from scout.models import BlobData
from scout.models import database
from scout.models import DocLookup
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
            DocLookup,
            Document,
            Metadata,
            Index,
            IndexDocument])


class HTTPTestCase(BaseTestCase):
    """Base for tests that exercise the Flask HTTP API."""
    def setUp(self):
        super().setUp()
        self.app = app.test_client()
        app.config['AUTHENTICATION'] = None

    def post_json(self, url, data):
        response = self.app.post(
            url,
            data=json.dumps(data),
            headers={'content-type': 'application/json'})
        return json_load(response.data)

    def put_json(self, url, data):
        response = self.app.put(
            url,
            data=json.dumps(data),
            headers={'content-type': 'application/json'})
        return json_load(response.data)

    def get_json(self, url):
        response = self.app.get(url)
        return json_load(response.data)


#
# Layer 1: Model / Python-level APIs
#

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
        self.assertRaises(InvalidSearchException, engine.search, '',
                          SEARCH_BM25)

        assertSearch('believe', [0, 3], SEARCH_NONE)
        assertSearch('faith thing', [2, 4], SEARCH_NONE)
        assertSearch('things', [2, 4], SEARCH_NONE)
        assertSearch('blah', [], SEARCH_NONE)
        self.assertRaises(InvalidSearchException, engine.search, '',
                          SEARCH_NONE)

    def test_blob_lifecycle(self):
        idx = Index.create(name='idx')
        doc1 = idx.index('doc1')
        doc2 = idx.index('doc2')

        # Same content -> same hash -> same BlobData row.
        doc1.attach('a.txt', b'shared data')
        doc2.attach('b.txt', b'shared data')
        self.assertEqual(BlobData.select().count(), 1)

        # Detach from doc1, blob still referenced by doc2.
        doc1.detach('a.txt')
        self.assertEqual(Attachment.select().count(), 1)
        self.assertEqual(BlobData.select().count(), 1)

        # Detach from doc2, blob orphaned, cleaned up.
        doc2.detach('b.txt')
        self.assertEqual(Attachment.select().count(), 0)
        self.assertEqual(BlobData.select().count(), 0)

        # Detach nonexistent filename returns 0, no error.
        self.assertEqual(doc1.detach('nope.txt'), 0)

    def test_set_metadata_replaces_all_keys(self):
        doc = self.index.index('test', k1='v1', k2='v2')
        self.assertEqual(doc.metadata, {'k1': 'v1', 'k2': 'v2'})

        doc.metadata = {'k3': 'v3'}
        self.assertEqual(doc.metadata, {'k3': 'v3'})
        self.assertEqual(
            Metadata.select().where(Metadata.document == doc.rowid).count(), 1)


class TestModelSearch(BaseTestCase):
    """Model-level search engine tests with a large metadata-rich dataset."""
    def setUp(self):
        super().setUp()
        self.index = Index.create(name='default')

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

    def assertResults(self, filters, expected):
        results = engine.search('testing', index=self.index, **filters)
        results = sorted(results, key=lambda doc: doc.metadata['idx'])
        indexes = [doc.metadata['idx'] for doc in results]
        self.assertEqual(indexes, expected)
        return results

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

        docs = engine.search('*', index=self.index, dob__le='2008-04-01')
        self.assertEqual(sorted([doc.metadata['dob'] for doc in docs]), [
            '2007-02-01',
            '2008-04-01',
        ])

    def test_invalid_op(self):
        with self.assertRaises(InvalidRequestException):
            engine.search('testing', index=self.index, name__xx='missing')

    def test_search_with_ranking_not_treated_as_metadata(self):
        self.populate()
        results = list(engine.search('testing', index=self.index,
                                     ranking='bm25', k1='k1-1', page=1))
        self.assertTrue(len(results) > 0)
        self.assertTrue(results[0].score <= 0)

    def test_apply_sorting(self):
        self.populate()
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


class TestDocLookupModelLevel(BaseTestCase):
    def setUp(self):
        super(TestDocLookupModelLevel, self).setUp()
        self.index = Index.create(name='idx')

    def test_create_and_get(self):
        # With identifier -- lookup created, resolvable by identifier or rowid.
        doc = self.index.index(content='hello world', identifier='my-doc')
        self.assertEqual(DocLookup.select().count(), 1)
        lookup = DocLookup.get(DocLookup.identifier == 'my-doc')
        self.assertEqual(lookup.rowid, doc.rowid)

        found = DocLookup.get_document('my-doc')
        self.assertEqual(found.rowid, doc.rowid)
        self.assertEqual(found.content, 'hello world')

        found = DocLookup.get_document(doc.rowid)
        self.assertEqual(found.content, 'hello world')

        found = DocLookup.get_document(str(doc.rowid))
        self.assertEqual(found.content, 'hello world')

        # Without identifier -- no lookup created.
        self.index.index(content='no ident')
        self.assertEqual(DocLookup.select().count(), 1)

    def test_update_and_clear_identifier(self):
        doc = self.index.index(content='hello', identifier='old-id')

        # Update identifier.
        self.index.index(content='hello updated', document=doc,
                         identifier='new-id')
        self.assertEqual(DocLookup.select().count(), 1)
        self.assertEqual(DocLookup.get().identifier, 'new-id')
        self.assertRaises(Document.DoesNotExist,
                          DocLookup.get_document, 'old-id')
        self.assertEqual(DocLookup.get_document('new-id').rowid, doc.rowid)

        # Clear identifier.
        self.index.index(content='hello cleared', document=doc,
                         identifier=None)
        self.assertEqual(DocLookup.select().count(), 0)
        self.assertRaises(Document.DoesNotExist,
                          DocLookup.get_document, 'new-id')

    def test_reuse_identifier_on_new_document(self):
        doc1 = self.index.index(content='first', identifier='reused')
        doc2 = self.index.index(content='second', identifier='reused')
        self.assertEqual(DocLookup.select().count(), 1)
        found = DocLookup.get_document('reused')
        self.assertEqual(found.rowid, doc2.rowid)
        self.assertNotEqual(found.rowid, doc1.rowid)

    def test_multiple_documents_distinct_identifiers(self):
        doc_a = self.index.index(content='aaa', identifier='id-a')
        doc_b = self.index.index(content='bbb', identifier='id-b')
        self.index.index(content='ccc')

        self.assertEqual(DocLookup.select().count(), 2)
        self.assertEqual(DocLookup.get_document('id-a').rowid, doc_a.rowid)
        self.assertEqual(DocLookup.get_document('id-b').rowid, doc_b.rowid)
        self.assertRaises(Document.DoesNotExist,
                          DocLookup.get_document, 'id-c')

    def test_swap_identifiers(self):
        doc_a = self.index.index(content='aaa', identifier='id-a')
        doc_b = self.index.index(content='bbb', identifier='id-b')

        # Clear a, assign a's old id to b, assign b's old id to a.
        self.index.index(content='aaa', document=doc_a, identifier=None)
        self.index.index(content='bbb', document=doc_b, identifier='id-a')
        self.index.index(content='aaa', document=doc_a, identifier='id-b')

        self.assertEqual(DocLookup.get_document('id-a').rowid, doc_b.rowid)
        self.assertEqual(DocLookup.get_document('id-b').rowid, doc_a.rowid)


#
# Layer 2: HTTP APIs
#

class TestHTTPViews(HTTPTestCase):
    """Index and document CRUD via the HTTP API."""

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
            data='{"not" "json}',
            headers={'content-type': 'application/json'})
        data = json_load(response.data)
        self.assertEqual(
            data,
            {'error': 'Unable to parse JSON data from request.'})

    def test_index_list(self):
        indexes = [Index.create(name='i%s' % i) for i in range(3)]
        indexes[1].index('test doc1')
        indexes[1].index('test doc2')

        data = self.get_json('/')
        self.assertEqual(data['indexes'], [
            {'document_count': 0, 'documents': '/i0/', 'id': 1, 'name': 'i0'},
            {'document_count': 2, 'documents': '/i1/', 'id': 2, 'name': 'i1'},
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

        data = self.get_json('/idx-a/')
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

        data = self.get_json('/idx-a/?page=2')
        self.assertEqual(data['page'], 2)
        self.assertEqual(data['pages'], 2)
        self.assertEqual(len(data['documents']), 2)

        data = self.get_json('/idx-b/')
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

    def test_parse_post_rejects_unknown_keys(self):
        idx = Index.create(name='idx')
        for bad_val in (None, ''):
            response = self.post_json('/documents/', {
                'content': 'test',
                'index': 'idx',
                'evil_key': bad_val})
            self.assertIn('error', response)
            self.assertIn('evil_key', response['error'])
        self.assertEqual(Document.select().count(), 0)

    def test_document_detail_get(self):
        idx = Index.create(name='idx')
        doc = idx.index('test doc', foo='bar')
        alt_doc = idx.index('alt doc')

        data = self.get_json('/documents/%s/' % doc.rowid)
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

        # Omitting indexes preserves existing.
        response = self.post_json(url, {'indexes': ['idx']})
        response = self.post_json(url, {'content': 're-updated'})
        assertDoc(doc, 're-updated', {}, ['idx'])

        # Empty content is allowed.
        response = self.post_json(url, {'content': ''})
        assertDoc(doc, '', {}, ['idx'])

        # Identifier can be changed.
        response = self.post_json(url, {'identifier': 'new-id'})
        doc_db = self.refresh_doc(doc)
        self.assertEqual(doc_db.identifier, 'new-id')

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

    def test_update_content_null_sets_empty(self):
        idx = Index.create(name='idx')
        doc = idx.index('original content')
        url = '/documents/%s/' % doc.get_id()

        self.post_json(url, {'content': None})
        data = self.get_json(url)
        self.assertEqual(data['content'], '')

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

    def test_document_delete_blob_cleanup(self):
        idx = Index.create(name='idx')
        d1 = idx.index('doc1')
        d2 = idx.index('doc2')

        # Unique blobs cleaned up on delete.
        d1.attach('a.txt', b'data-a')
        d1.attach('b.txt', b'data-b')
        self.assertEqual(BlobData.select().count(), 2)

        # Shared blob preserved when one reference remains.
        d1.attach('shared.txt', b'shared')
        d2.attach('shared2.txt', b'shared')
        self.assertEqual(BlobData.select().count(), 3)

        self.app.delete('/documents/%s/' % d1.get_id())
        self.assertEqual(Attachment.select().count(), 1)
        # Only shared blob survives (referenced by d2).
        self.assertEqual(BlobData.select().count(), 1)

    def test_create_duplicate_index(self):
        self.post_json('/', {'name': 'idx'})
        resp = self.post_json('/', {'name': 'idx'})
        self.assertIn('already exists', resp['error'])
        self.assertEqual(Index.select().count(), 1)

    def test_rename_index_collision(self):
        self.post_json('/', {'name': 'idx-a'})
        self.post_json('/', {'name': 'idx-b'})
        resp = self.post_json('/idx-b/', {'name': 'idx-a'})
        self.assertIn('already in use', resp['error'])
        # Names unchanged.
        names = sorted(idx.name for idx in Index.select())
        self.assertEqual(names, ['idx-a', 'idx-b'])

    def test_create_document_missing_content(self):
        Index.create(name='idx')
        resp = self.post_json('/documents/', {'index': 'idx'})
        self.assertIn('content', resp['error'])
        self.assertEqual(Document.select().count(), 0)

        resp = self.post_json('/documents/', {
            'content': None, 'index': 'idx'})
        self.assertIn('content', resp['error'])
        self.assertEqual(Document.select().count(), 0)


class TestHTTPAttachments(HTTPTestCase):
    """Attachment CRUD and global attachment views via the HTTP API."""

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
            data = self.get_json('/documents/1/attachments/')

        self.assertEqual(data, {
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
            data = self.get_json('/documents/%s/' % doc.get_id())

        self.assertEqual(len(data['attachments']), 10)

        with assert_query_count(8):
            self.get_json('/documents/')

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
        self.assertEqual(BlobData.select().count(), 2)  # BlobData orphan gone.

        # Existing file updated, new file added.
        foo, foo2 = Attachment.select().order_by(Attachment.filename)
        self.assertEqual(foo.blob.data, b'xx')
        self.assertEqual(foo2.blob.data, b'yy')

    def test_attachment_views(self):
        idx = Index.create(name='idx')
        doc = idx.index('doc 1')
        doc.attach('foo.jpg', 'x')
        doc.attach('bar.png', 'x')
        Attachment.update(timestamp='2016-01-02 03:04:05').execute()

        data = self.get_json('/documents/1/attachments/')
        self.assertEqual(data['attachments'], [
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

        data = self.get_json('/documents/1/attachments/foo.jpg/')
        self.assertEqual(data, {
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

    def test_global_attachments(self):
        idx = Index.create(name='idx')
        idx2 = Index.create(name='idx2')

        # Empty state.
        data = self.get_json('/attachments/')
        self.assertEqual(data['attachments'], [])
        self.assertEqual(data['page'], 1)
        self.assertEqual(data['pages'], 0)

        doc = idx.index('doc')
        doc.attach('photo.jpg', b'jpeg')
        doc.attach('notes.txt', b'text')
        doc.attach('logo.png', b'png')

        doc2 = idx2.index('doc')
        doc2.attach('d2.jpg', b'jpeg2')
        doc2.attach('notes.txt', b'text2')

        # All attachments.
        data = self.get_json('/attachments/')
        self.assertEqual(len(data['attachments']), 5)

        # Filter by mimetype.
        data = self.get_json('/attachments/?mimetype=image/jpeg')
        self.assertEqual(
            sorted(a['filename'] for a in data['attachments']),
            ['d2.jpg', 'photo.jpg'])

        # Filter by filename.
        data = self.get_json('/attachments/?filename=notes.txt')
        self.assertEqual(len(data['attachments']), 2)

        # Filter by index.
        data = self.get_json('/attachments/?index=idx2')
        self.assertEqual(
            sorted(a['filename'] for a in data['attachments']),
            ['d2.jpg', 'notes.txt'])

        data = self.get_json('/attachments/?index=idx&index=idx2')
        self.assertEqual(len(data['attachments']), 5)

        data = self.get_json('/attachments/?index=nope')
        self.assertEqual(len(data['attachments']), 0)

        # Ordering.
        data = self.get_json('/attachments/?index=idx&ordering=-filename')
        filenames = [a['filename'] for a in data['attachments']]
        self.assertEqual(filenames, ['photo.jpg', 'notes.txt', 'logo.png'])

        # Auth required.
        app.config['AUTHENTICATION'] = 'secret'
        try:
            self.assertEqual(self.app.get('/attachments/').status_code, 401)
            self.assertEqual(
                self.app.get('/attachments/?key=secret').status_code, 200)
        finally:
            app.config['AUTHENTICATION'] = None

    def test_attachment_create_no_files(self):
        idx = Index.create(name='idx')
        doc = idx.index('doc')
        resp = self.app.post('/documents/%s/attachments/' % doc.get_id(),
                             data={'data': '{}'})
        data = json_load(resp.data)
        self.assertIn('error', data)

    def test_attachment_update_file_count_errors(self):
        idx = Index.create(name='idx')
        doc = idx.index('doc')
        doc.attach('f.txt', b'original')

        # Update with no file.
        resp = self.app.post('/documents/%s/attachments/f.txt/' % doc.get_id(),
                             data={'data': '{}'})
        data = json_load(resp.data)
        self.assertIn('error', data)

        # Update with two files.
        resp = self.app.post(
            '/documents/%s/attachments/f.txt/' % doc.get_id(),
            data={
                'data': '{}',
                'file_0': (BytesIO(b'a'), 'f.txt'),
                'file_1': (BytesIO(b'b'), 'g.txt')})
        data = json_load(resp.data)
        self.assertIn('error', data)

        # Original unchanged.
        self.assertEqual(Attachment.select().count(), 1)

    def test_attachment_404s(self):
        idx = Index.create(name='idx')
        doc = idx.index('doc')
        doc.attach('exists.txt', b'data')

        # Nonexistent filename on existing document.
        resp = self.app.get('/documents/%s/attachments/nope.txt/' %
                            doc.get_id())
        self.assertEqual(resp.status_code, 404)

        # Nonexistent document entirely.
        resp = self.app.get('/documents/9999/attachments/anything/')
        self.assertEqual(resp.status_code, 404)

        # Download 404.
        resp = self.app.get('/documents/%s/attachments/nope.txt/download/' %
                            doc.get_id())
        self.assertEqual(resp.status_code, 404)

    def test_per_document_attachment_ordering(self):
        idx = Index.create(name='idx')
        doc = idx.index('doc')
        doc.attach('b.txt', b'bb')
        doc.attach('a.txt', b'a')
        doc.attach('c.txt', b'ccc')

        # Default: sorted by filename ascending.
        data = self.get_json('/documents/%s/attachments/' % doc.get_id())
        filenames = [a['filename'] for a in data['attachments']]
        self.assertEqual(filenames, ['a.txt', 'b.txt', 'c.txt'])

        # Reverse filename.
        data = self.get_json(
            '/documents/%s/attachments/?ordering=-filename' % doc.get_id())
        filenames = [a['filename'] for a in data['attachments']]
        self.assertEqual(filenames, ['c.txt', 'b.txt', 'a.txt'])

        # By mimetype (all text/plain here, so falls back to stable order).
        data = self.get_json(
            '/documents/%s/attachments/?ordering=mimetype' % doc.get_id())
        self.assertEqual(len(data['attachments']), 3)


class TestHTTPSearch(HTTPTestCase):
    """Search, filtering, pagination, auth, and query performance via HTTP."""

    def search(self, index, query, page=1, **filters):
        filters.setdefault('ranking', SEARCH_BM25)
        params = urlencode(dict(filters, q=query, page=page))
        return self.get_json('/%s/?%s' % (index, params))

    def populate(self, index):
        """Populate an index with 100 documents with metadata for filtering."""
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
                index.index(
                    content='testing %s' % i,
                    test='true',
                    k1=k1[i % 2],
                    k2=k2[i % 2],
                    k3=k3[i % 2],
                    idx='%02d' % i,
                    idx10=i % 10,
                    name=messages[i % 4],
                )

    def test_search_metadata_pagination(self):
        idx = Index.create(name='default')
        Index.create(name='unused-1')
        Index.create(name='unused-2')
        self.populate(idx)

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

    def test_search_sql_query_count(self):
        idx = Index.create(name='default')
        Index.create(name='unused-1')
        Index.create(name='unused-2')
        self.populate(idx)

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
                    self.search(idx, query)

                with assert_query_count(9):
                    self.search(idx, query, foo='bar')

        with assert_query_count(9):
            self.get_json('/idx-a/')

        with assert_query_count(8):
            self.get_json('/documents/')

        for i in range(10):
            Index.create(name='idx-%s' % i)

        with assert_query_count(2):
            self.get_json('/')

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
        idx_a = Index.create(name='idx-a')
        idx_b = Index.create(name='idx-b')
        for i in range(5):
            idx_a.index('doc-a-%d' % i)
        for i in range(3):
            idx_b.index('doc-b-%d' % i)

        # Shared doc in both indexes should be counted once.
        shared = idx_a.index('shared doc')
        idx_b.add_to_index(shared)

        data = self.get_json('/documents/')
        self.assertEqual(data['document_count'], 9)

        data = self.get_json('/documents/?index=idx-a')
        self.assertEqual(data['document_count'], 6)

        data = self.get_json('/documents/?index=idx-b')
        self.assertEqual(data['document_count'], 4)

        # Both indexes -- shared doc counted once, 9 not 10.
        data = self.get_json('/documents/?index=idx-a&index=idx-b')
        self.assertEqual(data['document_count'], 9)

    def test_pagination_urls(self):
        idx = Index.create(name='idx')
        for i in range(25):
            idx.index('document %d' % i, color='red')

        # Page 1 of 3.
        data = self.get_json('/documents/')
        self.assertEqual(data['page'], 1)
        self.assertEqual(data['pages'], 3)
        self.assertTrue(data['next_url'].endswith('/documents/?page=2'))
        self.assertIsNone(data['previous_url'])

        # Page 2: has both prev and next.
        data = self.get_json('/documents/?page=2')
        self.assertEqual(data['page'], 2)
        self.assertTrue(data['next_url'].endswith('/documents/?page=3'))
        self.assertTrue(data['previous_url'].endswith('/documents/?page=1'))

        # Page 3 (last): no next.
        data = self.get_json('/documents/?page=3')
        self.assertEqual(data['page'], 3)
        self.assertIsNone(data['next_url'])
        self.assertIsNotNone(data['previous_url'])

        # Single page: no prev or next.
        idx2 = Index.create(name='lonely')
        idx2.index('only doc')
        data = self.get_json('/lonely/')
        self.assertIsNone(data['next_url'])
        self.assertIsNone(data['previous_url'])

        # Query params are preserved in pagination URLs.
        data = self.get_json('/idx/?q=document&color=red')
        next_url = data['next_url']
        self.assertIn('page=2', next_url)
        self.assertIn('q=document', next_url)
        self.assertIn('color=red', next_url)

        # Index list and attachment list also have pagination.
        for i in range(25):
            Index.create(name='idx-%02d' % i)
        data = self.get_json('/')
        self.assertIn('next_url', data)

        doc = idx.index('doc')
        for i in range(15):
            doc.attach('file_%02d.txt' % i, b'data')
        data = self.get_json('/documents/%s/attachments/' % doc.get_id())
        self.assertIn('next_url', data)

    def test_index_list_ordering(self):
        idx_a = Index.create(name='alpha')
        idx_c = Index.create(name='charlie')
        idx_b = Index.create(name='bravo')
        idx_a.index('doc1')
        idx_a.index('doc2')
        idx_a.index('doc3')
        idx_b.index('doc1')

        # Default: by name ascending.
        data = self.get_json('/')
        names = [idx['name'] for idx in data['indexes']]
        self.assertEqual(names, ['alpha', 'bravo', 'charlie'])

        # By name descending.
        data = self.get_json('/?ordering=-name')
        names = [idx['name'] for idx in data['indexes']]
        self.assertEqual(names, ['charlie', 'bravo', 'alpha'])

        # By document_count descending.
        data = self.get_json('/?ordering=-document_count')
        names = [idx['name'] for idx in data['indexes']]
        self.assertEqual(names[0], 'alpha')

        # By id.
        data = self.get_json('/?ordering=id')
        ids = [idx['id'] for idx in data['indexes']]
        self.assertEqual(ids, sorted(ids))

    def test_documents_endpoint_ordering(self):
        idx = Index.create(name='idx')
        for content in self.corpus:
            idx.index(content)

        # Order by content.
        data = self.get_json('/documents/?index=idx&q=faith&ranking=bm25'
                             '&ordering=content')
        contents = [d['content'] for d in data['documents']]
        self.assertEqual(contents, sorted(contents))

        # Order by id descending.
        data = self.get_json('/documents/?index=idx&q=faith&ranking=bm25'
                             '&ordering=-id')
        ids = [d['id'] for d in data['documents']]
        self.assertEqual(ids, sorted(ids, reverse=True))


class TestDocLookupHTTP(HTTPTestCase):
    """Identifier-based document lookup via the HTTP API."""
    def setUp(self):
        super().setUp()
        self.index = Index.create(name='idx')

    def _create(self, content, identifier=None, **meta):
        payload = {'content': content, 'index': 'idx'}
        if identifier is not None:
            payload['identifier'] = identifier
        if meta:
            payload['metadata'] = meta
        return self.post_json('/documents/', payload)

    def _get(self, pk):
        return self.get_json('/documents/%s/' % pk)

    def _update(self, pk, **data):
        return self.put_json('/documents/%s/' % pk, data)

    def _delete(self, pk):
        return json_load(self.app.delete('/documents/%s/' % pk).data)

    def assertLookupCount(self, n):
        self.assertEqual(DocLookup.select().count(), n)

    def assertLookupMaps(self, identifier, rowid):
        lookup = DocLookup.get(DocLookup.identifier == identifier)
        self.assertEqual(lookup.rowid, rowid)
        doc = Document.all().where(Document.rowid == rowid).get()
        self.assertEqual(doc.identifier, identifier)

    def assertNotFound(self, pk):
        self.assertEqual(self.app.get('/documents/%s/' % pk).status_code, 404)

    def test_full_lifecycle(self):
        # Create with identifier.
        doc_id = self._create('v1', identifier='life')['id']
        self.assertLookupMaps('life', doc_id)

        # Create without identifier -- no lookup.
        self._create('no ident')
        self.assertLookupCount(1)

        # Update content only -- lookup preserved.
        self._update(doc_id, content='v2')
        self.assertEqual(self._get('life')['content'], 'v2')
        self.assertLookupMaps('life', doc_id)

        # Change identifier.
        self._update(doc_id, identifier='life2')
        self.assertNotFound('life')
        self.assertLookupMaps('life2', doc_id)

        # Update via identifier URL.
        self._update('life2', identifier='life3')
        self.assertNotFound('life2')
        self.assertEqual(self._get('life3')['content'], 'v2')

        # Update content and identifier simultaneously.
        self._update(doc_id, content='v3', identifier='life4')
        self.assertNotFound('life3')
        self.assertEqual(self._get('life4')['content'], 'v3')

        # Clear identifier.
        self.put_json('/documents/%s/' % doc_id, {'identifier': None})
        self.assertNotFound('life4')
        self.assertLookupCount(0)

        # Re-add identifier.
        self._update(doc_id, identifier='life5')
        self.assertLookupMaps('life5', doc_id)

        # Delete by identifier.
        self._delete('life5')
        self.assertLookupCount(0)
        self.assertEqual(Document.select().count(), 1)  # "no ident" remains.

    def test_add_identifier_to_bare_document(self):
        doc_id = self._create('hello')['id']
        self.assertLookupCount(0)
        self._update(doc_id, identifier='added-later')
        self.assertEqual(self._get('added-later')['id'], doc_id)
        self.assertLookupMaps('added-later', doc_id)

    def test_dedup_create(self):
        # Second POST with same identifier updates existing document.
        doc_id = self._create('first', identifier='dedup')['id']
        resp = self._create('second', identifier='dedup')
        self.assertEqual(resp['id'], doc_id)
        self.assertEqual(resp['content'], 'second')
        self.assertEqual(Document.select().count(), 1)
        self.assertLookupMaps('dedup', doc_id)

        # Dedup across indexes preserves metadata and indexes.
        Index.create(name='other')
        self._create('v1', identifier='dup', k1='old')
        resp = self.post_json('/documents/', {
            'content': 'v2', 'identifier': 'dup',
            'indexes': ['idx', 'other'],
            'metadata': {'k1': 'new', 'k2': 'added'}})
        self.assertEqual(resp['content'], 'v2')
        self.assertEqual(resp['metadata'], {'k1': 'new', 'k2': 'added'})
        self.assertIn('other', resp['indexes'])
        self.assertLookupCount(2)

    def test_delete_cleanup(self):
        # Delete by rowid.
        doc_id = self._create('hello', identifier='doomed')['id']
        self._delete(doc_id)
        self.assertLookupCount(0)
        self.assertEqual(Document.select().count(), 0)

        # Delete without identifier -- no lookup error.
        doc_id = self._create('bare')['id']
        self.assertEqual(self._delete(doc_id), {'success': True})
        self.assertLookupCount(0)

        # Delete middle of chain leaves others intact.
        a = self._create('aaa', identifier='a')['id']
        b = self._create('bbb', identifier='b')['id']
        c = self._create('ccc', identifier='c')['id']
        self._delete('b')
        self.assertLookupCount(2)
        self.assertLookupMaps('a', a)
        self.assertLookupMaps('c', c)
        self.assertNotFound('b')

    def test_all_tables_clean_after_delete(self):
        doc_id = self._create('full', identifier='clean', k='v')['id']
        self.app.post('/documents/clean/attachments/', data={
            'data': '{}',
            'file_0': (BytesIO(b'data'), 'f.txt')})

        self._delete('clean')
        self.assertEqual(Document.select().count(), 0)
        self.assertLookupCount(0)
        self.assertEqual(Metadata.select().count(), 0)
        self.assertEqual(Attachment.select().count(), 0)
        self.assertEqual(BlobData.select().count(), 0)
        self.assertEqual(IndexDocument.select().count(), 0)

    def test_swap_identifiers(self):
        r1 = self._create('aaa', identifier='id-a')
        r2 = self._create('bbb', identifier='id-b')

        self.put_json('/documents/%s/' % r1['id'], {'identifier': None})
        self._update(r2['id'], identifier='id-a')
        self._update(r1['id'], identifier='id-b')

        self.assertEqual(self._get('id-a')['content'], 'bbb')
        self.assertEqual(self._get('id-b')['content'], 'aaa')
        self.assertLookupMaps('id-a', r2['id'])
        self.assertLookupMaps('id-b', r1['id'])

    def test_steal_identifier_via_update(self):
        r1 = self._create('owner', identifier='mine')
        r2 = self._create('thief', identifier='other')

        self._update(r2['id'], identifier='mine')

        self.assertEqual(self._get('mine')['id'], r2['id'])
        self.assertLookupCount(1)

        # Owner still reachable by rowid, but has no lookup.
        self.assertEqual(self._get(r1['id'])['content'], 'owner')
        self.assertFalse(DocLookup.select().where(
            DocLookup.rowid == r1['id']).exists())

    def test_reuse_identifier_after_delete(self):
        old_id = self._create('first', identifier='recycled')['id']
        self._delete('recycled')
        self._create('xyz')  # prevent rowid reuse
        new_id = self._create('second', identifier='recycled')['id']
        self.assertNotEqual(new_id, old_id)
        self.assertLookupMaps('recycled', new_id)

    def test_clear_then_set_same_identifier(self):
        doc_id = self._create('sticky', identifier='boomerang')['id']
        self.put_json('/documents/%s/' % doc_id, {'identifier': None})
        self.assertLookupCount(0)
        self._update(doc_id, identifier='boomerang')
        self.assertLookupMaps('boomerang', doc_id)

    def test_index_and_metadata_survive_identifier_changes(self):
        Index.create(name='other')
        doc_id = self._create('tagged', identifier='m1', color='red',
                              size='big')['id']

        # Index change preserves lookup.
        self._update(doc_id, indexes=['other'])
        detail = self._get('m1')
        self.assertEqual(detail['indexes'], ['other'])
        self.assertLookupMaps('m1', doc_id)

        # Identifier change preserves metadata.
        self._update(doc_id, identifier='m2')
        self.assertEqual(self._get('m2')['metadata'],
                         {'color': 'red', 'size': 'big'})
        self.assertEqual(
            Metadata.select().where(Metadata.document == doc_id).count(), 2)

        # Index deletion does not affect lookup.
        self.app.delete('/other/')
        detail = self._get('m2')
        self.assertEqual(detail['id'], doc_id)
        self.assertEqual(detail['indexes'], [])
        self.assertLookupMaps('m2', doc_id)

    def test_search_finds_doc_after_identifier_change(self):
        self._create('unique platypus content', identifier='before')
        self._update('before', identifier='after')
        resp = self.get_json('/idx/?q=platypus')
        self.assertEqual(len(resp['documents']), 1)
        self.assertEqual(resp['documents'][0]['identifier'], 'after')

    def test_empty_string_identifier(self):
        r1 = self._create('hello', identifier='')
        r2 = self._create('world', identifier='')
        self.assertNotEqual(r1['id'], r2['id'])
        self.assertLookupCount(0)

        # Setting '' via update also clears.
        self._update(r1['id'], identifier='x')
        self.assertLookupCount(1)
        self._update(r1['id'], identifier='')
        self.assertLookupCount(0)
        self.assertIsNone(Document.all().where(
            Document.rowid == r1['id']).get().identifier)

    def test_numeric_string_identifier_does_not_shadow_rowid(self):
        for i in range(5):
            self._create('filler-%d' % i)
        target_id = self._create('the target', identifier='3')['id']

        # Rowid 3 wins over identifier '3'.
        self.assertEqual(self._get(3)['content'], 'filler-2')

        # After deleting rowid 3, identifier fallback kicks in.
        self._delete(3)
        detail = self._get(3)
        self.assertEqual(detail['id'], target_id)
        self.assertEqual(detail['content'], 'the target')

    def test_identifier_same_as_other_docs_rowid(self):
        """Create dedup must match by identifier only, not rowid."""
        r1 = self._create('first')
        r2 = self._create('second', identifier=str(r1['id']))
        # Dedup did NOT clobber r1 -- two distinct documents.
        self.assertNotEqual(r1['id'], r2['id'])
        self.assertEqual(Document.select().count(), 2)
        self.assertLookupMaps(str(r1['id']), r2['id'])

    def test_concurrent_style_interleaved_updates(self):
        a = self._create('aaa', identifier='a-id')['id']
        b = self._create('bbb', identifier='b-id')['id']

        # Interleave: update a, update b, update a, update b.
        self._update(a, content='a2')
        self._update(b, identifier='b-id-2')
        self._update(a, identifier='a-id-2')
        self._update(b, content='b2')

        self.assertLookupMaps('a-id-2', a)
        self.assertLookupMaps('b-id-2', b)
        self.assertEqual(self._get('a-id-2')['content'], 'a2')
        self.assertEqual(self._get('b-id-2')['content'], 'b2')
        self.assertNotFound('a-id')
        self.assertNotFound('b-id')
        self.assertLookupCount(2)
        self.assertEqual(Document.select().count(), 2)

        # Interleave: update a, update b, update a, update b.
        self._update('a-id-2', content='a3')
        self._update('b-id-2', identifier='b-id-3')
        self._update('a-id-2', identifier='a-id-3')
        self._update('b-id-3', content='b3')

        self.assertLookupMaps('a-id-3', a)
        self.assertLookupMaps('b-id-3', b)
        self.assertEqual(self._get('a-id-3')['content'], 'a3')
        self.assertEqual(self._get('b-id-3')['content'], 'b3')
        self.assertNotFound('a-id-2')
        self.assertNotFound('b-id-2')
        self.assertLookupCount(2)
        self.assertEqual(Document.select().count(), 2)

    def test_identifier_with_special_characters(self):
        for ident in ('has spaces', 'slashes/in/it', 'q?mark', 'pct%20enc'):
            doc_id = self._create('content', identifier=ident)['id']
            self.assertEqual(self._get(doc_id)['identifier'], ident)
            self.assertLookupMaps(ident, doc_id)
            self._delete(doc_id)
            self.assertLookupCount(0)


#
# Layer 3: HTTP via the Client
#

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

    def test_index_lifecycle(self):
        self.scout.create_index('idx-a')
        self.scout.create_index('idx-b')
        names = sorted(idx['name'] for idx in self.scout.get_indexes())
        self.assertEqual(names, ['idx-a', 'idx-b'])

        detail = self.scout.get_index('idx-a')
        self.assertEqual(detail['document_count'], 0)
        self.assertEqual(detail['page'], 1)
        self.assertEqual(detail['pages'], 0)

        self.scout.rename_index('idx-a', 'idx-renamed')
        names = sorted(idx['name'] for idx in self.scout.get_indexes())
        self.assertEqual(names, ['idx-b', 'idx-renamed'])

        # Delete index preserves documents.
        self.scout.create_document('hello world', 'idx-renamed')
        self.scout.delete_index('idx-renamed')
        self.assertEqual(Document.select().count(), 1)
        self.assertEqual(
            [idx['name'] for idx in self.scout.get_indexes()], ['idx-b'])

    def test_document_crud(self):
        idx = self.scout.create_index('idx')
        self.scout.create_index('alt')

        # Create with single index and metadata.
        doc = self.scout.create_document('test content', 'idx', k1='v1')
        self.assertEqual(doc['content'], 'test content')
        self.assertEqual(doc['indexes'], ['idx'])
        self.assertEqual(doc['metadata'], {'k1': 'v1'})

        # Get by id.
        fetched = self.scout.get_document(doc['id'])
        self.assertEqual(fetched, doc)

        # Create with multiple indexes.
        doc2 = self.scout.create_document('multi', ['idx', 'alt'])
        self.assertEqual(sorted(doc2['indexes']), ['alt', 'idx'])

        # Create with identifier.
        doc3 = self.scout.create_document('ident', 'idx', identifier='my-id')
        self.assertEqual(doc3['identifier'], 'my-id')

        # Update content.
        updated = self.scout.update_document(
            document_id=doc['id'], content='modified')
        self.assertEqual(updated['content'], 'modified')
        self.assertEqual(self.scout.get_document(doc['id'])['content'],
                         'modified')

        # Update by identifier.
        updated = self.scout.update_document('my-id', content='via ident')
        self.assertEqual(updated['content'], 'via ident')

        # Update metadata, then clear it.
        updated = self.scout.update_document(
            document_id=doc['id'], metadata={'color': 'blue', 'size': 'lg'})
        self.assertEqual(updated['metadata'], {'color': 'blue', 'size': 'lg'})
        updated = self.scout.update_document(
            document_id=doc['id'], metadata={})
        self.assertEqual(updated['metadata'], {})

        # Update indexes.
        updated = self.scout.update_document(
            document_id=doc['id'], indexes=['idx', 'alt'])
        self.assertEqual(sorted(updated['indexes']), ['alt', 'idx'])

        # Delete.
        result = self.scout.delete_document(doc['id'])
        self.assertEqual(result, {'success': True})

    def test_update_document_clear_identifier(self):
        self.scout.create_index('idx')
        doc = self.scout.create_document('text', 'idx', identifier='removable')
        self.assertEqual(DocLookup.select().count(), 1)

        updated = self.scout.update_document(doc['id'], identifier=None)
        self.assertIn(updated['identifier'], (None, ''))
        self.assertEqual(DocLookup.select().count(), 0)

    def test_create_without_identifier_no_lookup(self):
        self.scout.create_index('idx')
        doc = self.scout.create_document('no ident', 'idx')
        self.assertIn(doc['identifier'], (None, ''))
        self.assertEqual(DocLookup.select().count(), 0)

    def test_validate_rowid_present(self):
        self.assertRaises(ValueError, self.scout.delete_document)
        self.assertRaises(ValueError, self.scout.get_document)

        self.scout.create_index('idx')
        doc = self.scout.create_document('text', 'idx')
        self.assertRaises(
            ValueError,
            self.scout.update_document,
            document_id=doc['id'])

    def test_document_list_and_search(self):
        self.scout.create_index('a')
        self.scout.create_index('b')
        self.scout.create_document('alpha bravo', 'a', color='red')
        self.scout.create_document('bravo charlie', 'b', color='blue')
        self.scout.create_document('delta echo', 'a', color='red')

        # List all.
        result = self.scout.get_documents()
        self.assertEqual(result['document_count'], 3)

        # Filter by index.
        result = self.scout.get_documents(index=['a'])
        self.assertEqual(result['document_count'], 2)

        # Search via get_index.
        results = self.scout.get_index('a', q='bravo')
        self.assertEqual(len(results['documents']), 1)

        # Search via get_documents.
        results = self.scout.get_documents(q='bravo')
        self.assertEqual(len(results['documents']), 2)
        results = self.scout.get_documents(q='bravo', index='a')
        self.assertEqual(len(results['documents']), 1)

        # Metadata filter.
        results = self.scout.get_index('a', q='*', color='red')
        self.assertEqual(len(results['documents']), 2)

        # Ranking.
        results = self.scout.get_index('a', q='bravo', ranking='bm25')
        for doc in results['documents']:
            self.assertIn('score', doc)
        results = self.scout.get_index('a', q='bravo', ranking='none')
        for doc in results['documents']:
            self.assertNotIn('score', doc)

        # Pagination.
        for i in range(10):
            self.scout.create_document('doc %d' % i, 'a')
        result = self.scout.get_documents()
        self.assertEqual(result['pages'], 2)
        self.assertEqual(len(result['documents']), 10)

    def test_attachment_lifecycle(self):
        self.scout.create_index('idx')
        doc = self.scout.create_document('with file', 'idx')
        doc_id = doc['id']

        # Attach.
        result = self.scout.attach_files(doc_id, {
            'hello.txt': BytesIO(b'hello world'),
        })
        self.assertEqual(len(result['attachments']), 1)
        self.assertEqual(result['attachments'][0]['filename'], 'hello.txt')

        # List.
        attachments = self.scout.get_attachments(doc_id)
        self.assertEqual(len(attachments['attachments']), 1)
        att = attachments['attachments'][0]
        self.assertEqual(att['filename'], 'hello.txt')
        self.assertEqual(att['mimetype'], 'text/plain')

        # Detail.
        detail = self.scout.get_attachment(doc_id, 'hello.txt')
        self.assertEqual(detail['filename'], 'hello.txt')

        # Download.
        downloaded = self.scout.download_attachment(doc_id, 'hello.txt')
        self.assertEqual(downloaded, b'hello world')

        # Update.
        self.scout.update_file(doc_id, 'hello.txt', BytesIO(b'updated'))
        self.assertEqual(
            self.scout.download_attachment(doc_id, 'hello.txt'), b'updated')

        # Detach.
        self.scout.detach_file(doc_id, 'hello.txt')
        self.assertEqual(Attachment.select().count(), 0)

    def test_attachments_via_identifier(self):
        self.scout.create_index('idx')
        doc = self.scout.create_document('doc', 'idx', identifier='file-host')

        self.scout.attach_files('file-host', {
            'test.txt': BytesIO(b'payload')})
        resp = self.scout.get_attachments('file-host')
        self.assertEqual(resp['attachments'][0]['filename'], 'test.txt')
        self.assertEqual(
            self.scout.download_attachment('file-host', 'test.txt'),
            b'payload')

    def test_create_document_with_attachments(self):
        self.scout.create_index('idx')
        doc = self.scout.create_document(
            'with attachment', 'idx',
            attachments={'readme.txt': BytesIO(b'read me')})
        self.assertEqual(len(doc['attachments']), 1)
        self.assertEqual(doc['attachments'][0]['filename'], 'readme.txt')

    def test_upload_binary_file_with_crlf(self):
        self.scout.create_index('idx')
        evil_data = b'\r\n--boundary\r\nContent-Disposition: bad\r\n\r\nfake'
        doc = self.scout.create_document(
            'binary test', 'idx',
            identifier='evil-doc',
            attachments={'evil.bin': BytesIO(evil_data)})
        self.assertEqual(len(doc['attachments']), 1)

        self.assertEqual(
            self.scout.download_attachment(doc['id'], 'evil.bin'), evil_data)
        self.assertEqual(
            self.scout.download_attachment('evil-doc', 'evil.bin'), evil_data)

    def test_search_attachments(self):
        self.scout.create_index('a')
        self.scout.create_index('b')
        self.scout.create_document(
            'doc a', 'a', attachments={
                'a.txt': BytesIO(b'aaa'),
                'b.jpg': BytesIO(b'bbb')})
        self.scout.create_document(
            'doc b', 'b', attachments={'fb.txt': BytesIO(b'b')})

        results = self.scout.search_attachments()
        self.assertEqual(len(results['attachments']), 3)

        results = self.scout.search_attachments(mimetype='image/jpeg')
        self.assertEqual(len(results['attachments']), 1)
        self.assertEqual(results['attachments'][0]['filename'], 'b.jpg')

        results = self.scout.search_attachments(index='a')
        self.assertEqual(len(results['attachments']), 2)

    def test_authentication_key_sent(self):
        app.config['AUTHENTICATION'] = 'my-secret'
        try:
            authed = FlaskScout(app, key='my-secret')
            authed.create_index('secure-idx')
            indexes = authed.get_indexes()
            self.assertEqual(len(indexes), 1)

            # Without key, should get 401 -- the raw response is not JSON.
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


#
# Layer 4: FTS5-specific
#

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

    def assertHTTPResults(self, phrase, expected_indexes, **params):
        data, status = self._http_search(phrase, **params)
        self.assertEqual(status, 200)
        self.assertEqual(self._contents(data),
                         [self.corpus[i] for i in expected_indexes])
        return data


class TestScopeToContent(FTS5TestCase):
    """
    Verify that the ``identifier`` column is NOT searched.
    """
    def test_identifier_not_matched(self):
        self._add('the quick brown fox', identifier='secret-keyword-xyz')
        self.assertEqual(self._search('secret'), [])
        self.assertEqual(self._search('keyword'), [])
        self.assertEqual(self._search('xyz'), [])

        # Content still matches.
        self.assertEqual(self._search('quick'), ['the quick brown fox'])

    def test_shared_term_only_matches_content(self):
        self._add('python tutorial for beginners', identifier='python tut')
        self.assertEqual(self._search('python'),
                         ['python tutorial for beginners'])

    def test_http_identifier_not_matched(self):
        self._add('secret formula', identifier='magic keyword')
        data, status = self._http_search('magic')
        self.assertEqual(status, 200)
        self.assertEqual(self._contents(data), [])

        data, status = self._http_search('secret')
        self.assertEqual(status, 200)
        self.assertEqual(self._contents(data), ['secret formula'])

    def test_column_filter_injection(self):
        self._add('harmless content', identifier='secret data')
        self.assertEqual(self._search('identifier : secret'), [])
        self.assertEqual(self._search('x OR identifier : secret'), [])

        # HTTP level: should be 200 with no results, or 400 if FTS5
        # rejects the nested column filter.
        data, status = self._http_search('identifier : secret')
        self.assertIn(status, (200, 400))
        if status == 200:
            self.assertEqual(self._contents(data), [])


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

    def test_exact_phrase(self):
        self.assertCorpusResults('"true faith"', [1])
        self.assertCorpusResults('"small things"', [2])
        self.assertCorpusResults('"things small"', [])
        self.assertCorpusResults('"faith hope"', [])

        self.assertCorpusResults('"true faith" OR "small things"', [2, 1])
        self.assertCorpusResults('"true faith" heart', [1])

    def test_prefix(self):
        self.assertCorpusResults('fa*', [2, 3, 0, 4, 1])
        self.assertCorpusResults('beli*', [3, 0])
        self.assertCorpusResults('fa* NOT hope', [2, 3, 0, 1])
        self.assertCorpusResults('xyz*', [])

    def test_near(self):
        self.assertCorpusResults('NEAR(faith man)', [0])
        self.assertCorpusResults('NEAR(true faith, 1)', [1])
        self.assertCorpusResults('NEAR(call desired, 2)', [])
        self.assertCorpusResults('NEAR(call desired, 25)', [1])

    def test_initial_token(self):
        self.assertCorpusResults('^faith', [3, 4])
        self.assertCorpusResults('^hope', [])
        self.assertCorpusResults('^a', [0])

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

    def test_bm25_ordering(self):
        results = engine.search(
            'believe', index=self.index, ranking=SEARCH_BM25)
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

    def test_http_scores(self):
        data, _ = self._http_search('believe')
        for doc in data['documents']:
            self.assertIn('score', doc)
            self.assertIsInstance(doc['score'], float)

    def test_ordering(self):
        # Default: sorted by score ascending (most negative = best).
        data, _ = self._http_search('faith')
        scores = [d['score'] for d in data['documents']]
        self.assertEqual(scores, sorted(scores))

        data, _ = self._http_search('faith', ordering='-score')
        scores = [d['score'] for d in data['documents']]
        self.assertEqual(scores, sorted(scores, reverse=True))

        data, _ = self._http_search('faith', ordering='id')
        ids = [d['id'] for d in data['documents']]
        self.assertEqual(ids, sorted(ids))

        data, _ = self._http_search('faith', ordering='-id')
        ids = [d['id'] for d in data['documents']]
        self.assertEqual(ids, sorted(ids, reverse=True))

        data, _ = self._http_search('faith', ordering='content')
        contents = self._contents(data)
        self.assertEqual(contents, sorted(contents))

    def test_http_queries(self):
        self.assertHTTPResults('believe', [3, 0])
        self.assertHTTPResults('man OR hope', [0, 4])
        self.assertHTTPResults('believe NOT nothing', [3])
        self.assertHTTPResults('"true faith"', [1])
        self.assertHTTPResults('beli*', [3, 0])
        self.assertHTTPResults('NEAR(true faith, 1)', [1])
        self.assertHTTPResults('^faith', [3, 4])
        self.assertHTTPResults('(hope OR man) AND faith', [0, 4])

    def test_http_response_metadata(self):
        data = self.assertHTTPResults('believe', [3, 0])
        self.assertEqual(data['search_term'], 'believe')
        self.assertEqual(data['ranking'], 'bm25')

    def test_documents_endpoint_queries(self):
        for phrase, n in (('believe', 2), ('man OR hope', 2),
                          ('"true faith"', 1), ('beli*', 2),
                          ('^faith AND thing', 1)):
            data, status = self._http_search_docs(phrase)
            self.assertEqual(status, 200)
            self.assertEqual(len(data['documents']), n, phrase)


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

            data, status = self._http_search_docs(case)
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
        other = ['alpha', 'beta', 'gamma', 'delta', 'epsilon']
        for i, content in enumerate(self.corpus):
            self._add(content, topic=topics[i], other=other[i])

    def test_filters(self):
        results = self._search('faith', topic='virtue')
        self.assertEqual(len(results), 2)

        results = self._search('faith', topic='virtue', other='alpha')
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0], self.corpus[0])

        results = self._search('believe', other__ne='alpha')
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0], self.corpus[3])

        results = self._search('faith', topic__in='virtue,prayer')
        self.assertEqual(len(results), 3)

        results = self._search('faith', topic__contains='philos')
        self.assertEqual(len(results), 2)

    def test_http_filters(self):
        data, _ = self._http_search('faith', topic='virtue')
        self.assertEqual(len(data['documents']), 2)
        self.assertEqual(data['filters'], {'topic': ['virtue']})

        data, _ = self._http_search('faith', topic='virtue', other='alpha')
        self.assertEqual(len(data['documents']), 1)
        self.assertEqual(data['documents'][0]['content'], self.corpus[0])


class TestFTS5EdgeCases(FTS5TestCase):
    def test_empty_index_and_mutations(self):
        # Search empty index.
        self.assertEqual(self._search('anything'), [])

        # Duplicate content creates separate documents.
        for _ in range(3):
            self._add('identical content here')
        self.assertEqual(len(self._search('identical')), 3)

        # Update replaces content in index.
        doc = self._add('original content', identifier='doc1')
        self.assertEqual(len(self._search('original')), 1)
        self.index.index(content='updated content', document=doc,
                         identifier='doc1')
        self.assertEqual(self._search('original'), [])
        self.assertEqual(len(self._search('updated')), 1)

        # Delete removes from index.
        doc2 = self._add('ephemeral content')
        self.assertEqual(len(self._search('ephemeral')), 1)
        doc2.delete_instance()
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

    def test_pagination_and_counts(self):
        data, _ = self._http_search('testing')
        self.assertEqual(data['filtered_count'], 25)
        self.assertEqual(len(data['documents']), 10)
        self.assertEqual(data['search_term'], 'testing')
        self.assertEqual(data['ranking'], 'bm25')

        # Filter narrows count.
        data, _ = self._http_search('testing', idx='5')
        self.assertEqual(data['filtered_count'], 1)

        # Documents endpoint.
        data, status = self._http_search_docs('testing')
        self.assertEqual(status, 200)
        self.assertEqual(data['filtered_count'], 25)

    def test_ranking_options(self):
        data, _ = self._http_search('testing', ranking='none')
        self.assertEqual(data['ranking'], 'none')

        data, status = self._http_search('testing', ranking='invalid')
        self.assertEqual(status, 400)


def main():
    option_parser = get_option_parser()
    options, args = option_parser.parse_args()
    unittest.main(argv=sys.argv, verbosity=not options.quiet and 2 or 0)


if __name__ == '__main__':
    main()
