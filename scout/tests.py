import json
import optparse
import sys
import unittest
from io import BytesIO
from urllib.parse import urlencode

from playhouse.sqlite_ext import *
from playhouse.test_utils import assert_query_count

from scout.client import Scout
from scout.client import SearchProvider
from scout.client import SearchSite
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

    def delete(self, url):
        response = self.app.delete(
            url,
            headers={'content-type': 'application/json'})
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

        # No identifier so DocLookup empty.
        self.assertEqual(DocLookup.select().count(), 0)

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

        # Metadata is cleared if empty.
        update2 = self.index.index('updated doc 2', document=doc)
        self.assertEqual(Document.select().count(), 1)
        u_doc_db = (Document
                    .select(Document._meta.primary_key, Document.content)
                    .get())
        self.assertEqual(u_doc_db.content, 'updated doc 2')
        self.assertEqual(u_doc_db.get_id(), doc_db.get_id())
        self.assertEqual(u_doc_db.metadata, {})

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
        Basic tests for simple string searches of a single index.
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

        assertSearch('believe', [3, 0], SEARCH_BM25)  # Same result.
        assertSearch('faith thing', [4, 2], SEARCH_BM25)  # Same.
        assertSearch('things', [4, 2], SEARCH_BM25)  # Same result.
        assertSearch('blah', [], SEARCH_BM25)  # No results, works.

        assertSearch('believe', [0, 3], SEARCH_NONE)
        assertSearch('faith thing', [2, 4], SEARCH_NONE)
        assertSearch('things', [2, 4], SEARCH_NONE)
        assertSearch('blah', [], SEARCH_NONE)

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
        q = Metadata.select().where(Metadata.document == doc.rowid)
        self.assertEqual(q.count(), 1)

        # Empty value clears.
        for m in ({}, None):
            doc.metadata = m
            q = Metadata.select().where(Metadata.document == doc.rowid)
            self.assertEqual(q.count(), 0)

    def test_model_dedup_on_identifier(self):
        doc1 = self.index.index('first', identifier='dedup')
        doc2 = self.index.index('second', identifier='dedup')
        self.assertEqual(Document.select().count(), 1)
        self.assertEqual(doc2.rowid, doc1.rowid)
        refreshed = Document.all().where(Document.rowid == doc1.rowid).get()
        self.assertEqual(refreshed.content, 'second')

    def test_identifier_preserved_reindex(self):
        doc = self.index.index('original', identifier='keep-me')
        self.assertEqual(DocLookup.select().count(), 1)

        # Identifier not overwritten.
        self.index.index('updated content', document=doc)
        self.assertEqual(DocLookup.select().count(), 1)
        self.assertEqual(DocLookup.get().identifier, 'keep-me')
        refreshed = Document.all().where(Document.rowid == doc.rowid).get()
        self.assertEqual(refreshed.content, 'updated content')
        self.assertEqual(refreshed.identifier, 'keep-me')

    def test_attach_sanitizes_empty_filename(self):
        doc = self.index.index('test')
        attachment = doc.attach('...', b'data')
        self.assertEqual(attachment.filename, 'unnamed')


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
                    identifier='doc:%s' % i)

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

        # Comma-separated get normalized.
        self.assertResults(
            {'idx__ge': 95, 'idx10__in': '5 , 8,9,1, 3'},
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

    def test_numeric_metadata_ordering(self):
        data = [('testing 2', '2'), ('testing 10', '10'), ('testing 1', '1'),
                ('testing 20', '20')]
        for content, priority in data:
            self.index.index(content=content, priority=priority, idx=content)

        self.assertResults({'priority__gt': 5}, ['testing 10', 'testing 20'])
        self.assertResults({'priority__le': 2}, ['testing 1', 'testing 2'])

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

        docs = engine.search('*', index=self.index, dob__ge='2008-01-01',
                             dob__lt='2009-01-01')
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

        # Id.
        results = list(engine.search(
            'testing', index=self.index, ordering='-id'))
        ids = [doc.rowid for doc in results]
        self.assertEqual(ids, sorted(ids, reverse=True))

        results = list(engine.search(
            'testing', index=self.index, ordering='id'))
        ids = [doc.rowid for doc in results]
        self.assertEqual(ids, sorted(ids))

        # Identifier.
        results = list(engine.search(
            'testing', index=self.index, ordering='-identifier'))
        identifiers = [doc.identifier for doc in results]
        self.assertEqual(identifiers, sorted(identifiers, reverse=True))

        results = list(engine.search(
            'testing', index=self.index, ordering='identifier'))
        identifiers = [doc.identifier for doc in results]
        self.assertEqual(identifiers, sorted(identifiers))

        # Content.
        results = list(engine.search(
            'testing', index=self.index, ordering='-content'))
        contents = [doc.content for doc in results]
        self.assertEqual(contents, sorted(contents, reverse=True))

        results = list(engine.search(
            'testing', index=self.index, ordering='content'))
        contents = [doc.content for doc in results]
        self.assertEqual(contents, sorted(contents))


class TestDocLookupModelLevel(BaseTestCase):
    def setUp(self):
        super(TestDocLookupModelLevel, self).setUp()
        self.index = Index.create(name='idx')

    def test_numeric_identifier_vs_rowid(self):
        """Numeric identifier must take precedence over rowid."""
        # Create 3 docs without identifiers - rowids 1, 2, 3.
        doc1 = self.index.index(content='rowid-1')
        doc2 = self.index.index(content='rowid-2')
        doc3 = self.index.index(content='rowid-3')
        self.assertEqual(doc1.rowid, 1)
        self.assertEqual(doc2.rowid, 2)
        self.assertEqual(doc3.rowid, 3)

        # Give doc3 the identifier '1', which is doc1's rowid.
        self.index.index(content='rowid-3', document=doc3, identifier='1')

        # Lookup '1' must return doc3 (identifier), not doc1 (rowid).
        found = DocLookup.get_document('1')
        self.assertEqual(found.rowid, doc3.rowid)
        self.assertEqual(found.content, 'rowid-3')

        # Integer 1 also returns doc3, identifier still wins.
        found = DocLookup.get_document(1)
        self.assertEqual(found.rowid, doc3.rowid)

        # After removing the identifier, '1' falls back to rowid.
        DocLookup.set_identifier(doc3, None)
        doc3.save()
        found = DocLookup.get_document('1')
        self.assertEqual(found.rowid, doc1.rowid)
        self.assertEqual(found.content, 'rowid-1')

    def test_set_identifier_empty_string_treated_as_clear(self):
        doc = self.index.index(content='test', identifier='will-clear')
        self.assertEqual(DocLookup.select().count(), 1)

        DocLookup.set_identifier(doc, '')
        self.assertIsNone(doc.identifier)
        self.assertEqual(DocLookup.select().count(), 0)

#
# Layer 2: HTTP APIs
#

class TestHTTPViews(HTTPTestCase):
    """Index and document CRUD via the HTTP API."""
    def assertLookupCount(self, n):
        self.assertEqual(DocLookup.select().count(), n)

    def assertLookupMaps(self, identifier, rowid):
        lookup = DocLookup.get(DocLookup.identifier == identifier)
        self.assertEqual(lookup.rowid, rowid)
        doc = Document.all().where(Document.rowid == rowid).get()
        self.assertEqual(doc.identifier, identifier)

    def assertNotFound(self, url):
        resp = self.app.get(url)
        self.assertEqual(resp.status_code, 404)

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

    def test_normalize_get_indexes_empty_value(self):
        Index.create(name='idx')
        idx = Index.create(name='idx2')
        idx.index('doc')

        # Empty index= param → should return documents unfiltered, not 500.
        response = self.get_json('/documents/?index=')
        self.assertEqual(len(response['documents']), 1)

    def test_shared_doc_not_duplicated_in_multi_index_filter(self):
        idx_a = Index.create(name='idx-a')
        idx_b = Index.create(name='idx-b')

        # doc lives in both indexes.
        doc = idx_a.index('shared content')
        idx_b.add_to_index(doc)

        # Only in idx-a.
        idx_a.index('only-a')

        data = self.get_json('/documents/?index=idx-a&index=idx-b')
        contents = [d['content'] for d in data['documents']]

        # "shared content" must appear exactly once.
        self.assertEqual(sorted(contents), ['only-a', 'shared content'])
        self.assertEqual(data['document_count'], 2)
        self.assertEqual(data['filtered_count'], 2)

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

    def test_identifier_lifecycle(self):
        # Create without identifier: no DocLookup row.
        Index.create(name='idx')
        resp = self.post_json('/documents/', {
            'content': 'huey!',
            'index': 'idx',
            'metadata': {'k1': 'v1'}})
        pk = resp['id']
        self.assertIsNone(resp['identifier'])
        self.assertEqual(DocLookup.select().count(), 0)

        resp = self.get_json('/documents/%s/' % pk)
        self.assertEqual(resp['content'], 'huey!')
        self.assertIsNone(resp['identifier'])

        # Lookup via non-existent identifier or id returns 404.
        resp = self.app.get('/documents/huey/')
        self.assertEqual(resp.status_code, 404)
        resp = self.app.get('/documents/%s/' % (pk + 1,))
        self.assertEqual(resp.status_code, 404)

        # Set the identifier via an update. Nothing else is modified.
        resp = self.post_json('/documents/%s/' % pk, {'identifier': 'i1'})
        self.assertEqual(resp['id'], pk)
        self.assertEqual(resp['identifier'], 'i1')
        self.assertEqual(resp['content'], 'huey!')
        self.assertEqual(resp['metadata'], {'k1': 'v1'})

        # Verify lookup was created properly.
        self.assertLookupCount(1)
        self.assertLookupMaps('i1', pk)

        # Lookup and update via identifier or PK works.
        for val in ('i1', pk):
            resp = self.get_json('/documents/%s/' % val)
            self.assertEqual(resp['id'], pk)
            self.assertEqual(resp['identifier'], 'i1')

            resp = self.post_json('/documents/%s/' % val, {
                'content': 'huey-%s' % val})
            self.assertEqual(resp['id'], pk)
            self.assertEqual(resp['identifier'], 'i1')
            self.assertEqual(resp['content'], 'huey-%s' % val)

        # Update the identifier. Nothing else is modified.
        resp = self.post_json('/documents/i1/', {'identifier': 'i2'})
        self.assertEqual(resp['id'], pk)
        self.assertEqual(resp['identifier'], 'i2')
        self.assertEqual(resp['metadata'], {'k1': 'v1'})

        # Verify lookup was created properly.
        self.assertLookupCount(1)
        self.assertLookupMaps('i2', pk)

        # Old identifier is gone.
        resp = self.app.get('/documents/i1/')
        self.assertEqual(resp.status_code, 404)

        # New identifier resolves.
        resp = self.get_json('/documents/i2/')
        self.assertEqual(resp['id'], pk)
        self.assertEqual(resp['identifier'], 'i2')
        self.assertEqual(resp['metadata'], {'k1': 'v1'})

        # Clear identifier.
        resp = self.post_json('/documents/i2/', {'identifier': None})
        self.assertEqual(resp['id'], pk)
        self.assertIsNone(resp['identifier'])
        self.assertEqual(resp['metadata'], {'k1': 'v1'})

        # Lookup and identifier are gone.
        self.assertEqual(DocLookup.select().count(), 0)
        resp = self.app.get('/documents/i2/')
        self.assertEqual(resp.status_code, 404)

        # Set the identifier. Nothing else is modified.
        resp = self.post_json('/documents/%s/' % pk, {'identifier': 'i3'})
        self.assertEqual(resp['id'], pk)
        self.assertEqual(resp['identifier'], 'i3')
        self.assertEqual(resp['metadata'], {'k1': 'v1'})

        # Verify lookup was created properly.
        self.assertLookupCount(1)
        self.assertLookupMaps('i3', pk)

        # Update the doc w/o specifying ident. Nothing else is modified.
        resp = self.post_json('/documents/i3/', {'content': 'huey!'})
        self.assertEqual(resp['id'], pk)
        self.assertEqual(resp['identifier'], 'i3')
        self.assertEqual(resp['metadata'], {'k1': 'v1'})
        self.assertEqual(resp['content'], 'huey!')

        # Create a second index to verify update occurs.
        Index.create(name='idx2')

        # Create w/existing identifier does upsert.
        resp = self.post_json('/documents/', {
            'content': 'mickey!',
            'identifier': 'i3',
            'indexes': ['idx', 'idx2']})
        self.assertEqual(resp['id'], pk)
        self.assertEqual(resp['identifier'], 'i3')
        self.assertEqual(resp['metadata'], {'k1': 'v1'})
        self.assertEqual(resp['content'], 'mickey!')
        self.assertEqual(sorted(resp['indexes']), ['idx', 'idx2'])

        # Verify lookup is still correct.
        self.assertLookupCount(1)
        self.assertLookupMaps('i3', pk)

    def test_identifier_multi_document_interactions(self):
        Index.create(name='idx')

        # Multiple documents with distinct identifiers.
        def create(**data):
            resp = self.post_json('/documents/', data)
            return resp['id']

        pk_a = create(content='aaa', identifier='id-a', index='idx')
        pk_b = create(content='bbb', identifier='id-b', index='idx')
        pk_bare = create(content='ccc', index='idx')
        self.assertEqual(Document.select().count(), 3)

        self.assertLookupCount(2)
        self.assertLookupMaps('id-a', pk_a)
        self.assertLookupMaps('id-b', pk_b)

        # Create w/same identifier does upsert.
        pk_a2 = create(content='aaa-x', identifier='id-a', index='idx')
        self.assertEqual(pk_a2, pk_a)
        self.assertEqual(Document.select().count(), 3)  # No new document.

        doc = Document.get(Document.rowid == pk_a)
        self.assertEqual(doc.content, 'aaa-x')

        # Update: doc b steal doc a's identifier.
        resp = self.post_json('/documents/id-b/', {
            'identifier': 'id-a',
        })
        self.assertEqual(resp['id'], pk_b)
        self.assertEqual(resp['identifier'], 'id-a')
        self.assertEqual(resp['content'], 'bbb')

        # doc_b now owns 'id-a'.
        self.assertLookupCount(1)
        self.assertLookupMaps('id-a', pk_b)

        # doc_a's identifier got cleared.
        resp = self.get_json('/documents/%s/' % pk_a)
        self.assertIsNone(resp['identifier'])

        # Reset.
        self.post_json('/documents/%s/' % pk_a, {'identifier': 'id-a'})
        self.post_json('/documents/%s/' % pk_b, {'identifier': 'id-b'})

        # Verify docs and identifiers look good.
        self.assertLookupCount(2)
        self.assertLookupMaps('id-a', pk_a)
        self.assertLookupMaps('id-b', pk_b)

        # Update, bare doc steals id-a.
        resp = self.post_json('/documents/%s/' % pk_bare, {
            'identifier': 'id-a',
            'content': 'ccc-x'})
        self.assertEqual(resp['id'], pk_bare)
        self.assertEqual(resp['identifier'], 'id-a')
        self.assertEqual(resp['content'], 'ccc-x')

        # doc_a's identifier is cleared again.
        resp = self.get_json('/documents/%s/' % pk_a)
        self.assertIsNone(resp['identifier'])

        # Verify DocLookup is correct.
        self.assertLookupCount(2)
        self.assertLookupMaps('id-a', pk_bare)
        self.assertLookupMaps('id-b', pk_b)

        # Theft chain: A -> B -> C.
        self.post_json('/documents/%s/' % pk_a, {'identifier': 'chain'})
        self.post_json('/documents/%s/' % pk_b, {'identifier': 'chain'})
        doc_a = Document.get(Document.rowid == pk_a)
        self.assertIsNone(doc_a.identifier)
        self.post_json('/documents/%s/' % pk_bare, {'identifier': 'chain'})
        doc_b = Document.get(Document.rowid == pk_b)
        self.assertIsNone(doc_b.identifier)

        # Only ccc owns 'chain', stale identifiers were removed.
        self.assertLookupCount(1)
        self.assertLookupMaps('chain', pk_bare)

        # Swap identifiers between two documents.
        self.post_json('/documents/%s/' % pk_a, {'identifier': 'id-a'})
        self.post_json('/documents/%s/' % pk_b, {'identifier': 'id-b'})

        self.post_json('/documents/%s/' % pk_a, {'identifier': None})
        self.post_json('/documents/%s/' % pk_b, {'identifier': 'id-a'})
        self.post_json('/documents/%s/' % pk_a, {'identifier': 'id-b'})

        self.assertEqual(self.get_json('/documents/id-a/')['id'], pk_b)
        self.assertEqual(self.get_json('/documents/id-b/')['id'], pk_a)
        self.assertEqual(self.get_json('/documents/chain/')['id'], pk_bare)
        self.assertLookupCount(3)
        self.assertLookupMaps('id-a', pk_b)
        self.assertLookupMaps('id-b', pk_a)
        self.assertLookupMaps('chain', pk_bare)

    def test_identifier_updates(self):
        Index.create(name='idx')
        # Create with identifier.
        resp = self.post_json('/documents/', {
            'content': 'v1',
            'identifier': 'i1',
            'index': 'idx'})
        pk = resp['id']
        self.assertLookupMaps('i1', pk)

        # Create without identifier.
        self.post_json('/documents/', {'content': 'no ident', 'index': 'idx'})
        self.assertLookupCount(1)

        # Update content only -- lookup preserved.
        self.post_json('/documents/i1/', {'content': 'v2'})
        self.assertEqual(self.get_json('/documents/i1/')['content'], 'v2')
        self.assertLookupMaps('i1', pk)

        # Update identifier only.
        self.post_json('/documents/i1/', {'identifier': 'i2'})
        self.assertLookupMaps('i2', pk)

        # Update content and identifier simultaneously.
        self.post_json('/documents/i2/', {
            'content': 'v3',
            'identifier': 'i3'})
        self.assertLookupMaps('i3', pk)
        self.assertLookupCount(1)

        # Clear identifier.
        self.post_json('/documents/i3/', {'identifier': None})
        self.assertLookupCount(0)

        # Re-add identifier.
        self.post_json('/documents/%s/' % pk, {'identifier': 'i4'})
        self.assertLookupCount(1)
        self.assertLookupMaps('i4', pk)

        # Delete by identifier.
        self.app.delete('/documents/i4/')
        self.assertLookupCount(0)
        self.assertEqual(Document.select().count(), 1)  # "no ident" remains.

    def test_dedup_create(self):
        Index.create(name='idx')

        # Second POST with same identifier updates existing document.
        resp = self.post_json('/documents/', {
            'content': 'first',
            'identifier': 'dedup',
            'index': 'idx'})
        pk = resp['id']

        resp = self.post_json('/documents/', {
            'content': 'second',
            'identifier': 'dedup',
            'index': 'idx',
            'metadata': {'k1': 'v1-1'}})
        self.assertEqual(resp['id'], pk)
        self.assertEqual(resp['content'], 'second')
        self.assertEqual(resp['metadata'], {'k1': 'v1-1'})
        self.assertEqual(Document.select().count(), 1)
        self.assertLookupMaps('dedup', pk)

        Index.create(name='other')
        resp = self.post_json('/documents/', {
            'content': 'third',
            'identifier': 'dedup',
            'metadata': {'k1': 'v1-2'},
            'indexes': ['idx', 'other']})
        self.assertLookupMaps('dedup', pk)
        self.assertLookupCount(1)
        self.assertEqual(Document.all().count(), 1)

        resp = self.get_json('/documents/dedup/')
        self.assertEqual(resp['id'], pk)
        self.assertEqual(resp['identifier'], 'dedup')
        self.assertEqual(resp['indexes'], ['idx', 'other'])
        self.assertEqual(resp['content'], 'third')
        self.assertEqual(resp['metadata'], {'k1': 'v1-2'})

    def test_delete_cleanup(self):
        Index.create(name='idx')
        # Delete by rowid.
        self.post_json('/documents/', {
            'content': 'c',
            'identifier': 'i1',
            'index': 'idx'})
        self.delete('/documents/i1/')
        self.assertLookupCount(0)
        self.assertEqual(Document.select().count(), 0)

        # Delete without identifier -- no lookup error.
        resp = self.post_json('/documents/', {'content': 'c', 'index': 'idx'})
        resp = self.delete('/documents/%s/' % resp['id'])
        self.assertEqual(resp, {'success': True})
        self.assertLookupCount(0)
        self.assertEqual(Document.select().count(), 0)

    def test_all_tables_clean_after_delete(self):
        Index.create(name='idx')
        resp = self.post_json('/documents/', {
            'content': 'full',
            'identifier': 'clean',
            'index': 'idx',
            'metadata': {'k1': 'v1', 'k2': 'v2'}})
        self.app.post('/documents/clean/attachments/', data={
            'data': '{}',
            'file_0': (BytesIO(b'data'), 'f.txt')})

        self.delete('/documents/clean/')
        self.assertEqual(Document.select().count(), 0)
        self.assertEqual(DocLookup.select().count(), 0)
        self.assertEqual(Metadata.select().count(), 0)
        self.assertEqual(Attachment.select().count(), 0)
        self.assertEqual(BlobData.select().count(), 0)
        self.assertEqual(IndexDocument.select().count(), 0)

    def test_reuse_identifier_after_delete(self):
        Index.create(name='idx')
        resp = self.post_json('/documents/', {
            'content': 'f',
            'identifier': 'i1',
            'index': 'idx'})
        pk = resp['id']
        self.delete('/documents/i1/')

        # Prevent sqlite from reusing rowid.
        self.post_json('/documents/', {'content': 'x', 'index': 'idx'})

        resp = self.post_json('/documents/', {
            'content': 'f2',
            'identifier': 'i1',
            'index': 'idx'})
        self.assertNotEqual(pk, resp['id'])
        self.assertLookupMaps('i1', resp['id'])

    def test_index_and_metadata_survive_identifier_changes(self):
        Index.create(name='idx')
        Index.create(name='other')
        resp = self.post_json('/documents/', {
            'content': 'c',
            'identifier': 'm1',
            'index': 'idx',
            'metadata': {'k1': 'v1', 'k2': 'v2'}})
        pk = resp['id']

        # Index change preserves lookup.
        self.post_json('/documents/m1/', {'indexes': ['other']})
        resp = self.get_json('/documents/m1/')
        self.assertEqual(resp['indexes'], ['other'])
        self.assertLookupMaps('m1', pk)

        # Identifier change preserves metadata.
        self.post_json('/documents/m1/', {'identifier': 'm2'})
        resp = self.get_json('/documents/m2/')
        self.assertEqual(resp['indexes'], ['other'])
        self.assertEqual(resp['metadata'], {'k1': 'v1', 'k2': 'v2'})
        self.assertLookupMaps('m2', pk)

        # Index deletion does not affect lookup.
        self.app.delete('/other/')
        resp = self.get_json('/documents/m2/')
        self.assertEqual(resp['indexes'], [])
        self.assertEqual(resp['metadata'], {'k1': 'v1', 'k2': 'v2'})
        self.assertEqual(resp['identifier'], 'm2')
        self.assertLookupMaps('m2', pk)

    def test_identifier_precedence(self):
        Index.create(name='idx')
        for i in range(5):
            self.post_json('/documents/', {
                'content': 'filler-%s' % i,
                'index': 'idx'})

        resp = self.post_json('/documents/', {
            'content': 'target',
            'identifier': '3',
            'index': 'idx'})
        pk = resp['id']
        self.assertLookupMaps('3', pk)

        # User identifier is preferred.
        resp = self.get_json('/documents/3/')
        self.assertEqual(resp['content'], 'target')
        self.assertEqual(resp['identifier'], '3')

        # After deleting identifier 3, rowid fallback kicks in.
        self.delete('/documents/3/')
        resp = self.get_json('/documents/3/')
        self.assertEqual(resp['content'], 'filler-2')

    def test_concurrent_style_interleaved_updates(self):
        Index.create(name='idx')
        a = self.post_json('/documents/', {
            'content': 'aaa',
            'identifier': 'a-id',
            'index': 'idx'})['id']
        b = self.post_json('/documents/', {
            'content': 'bbb',
            'identifier': 'b-id',
            'index': 'idx'})['id']

        def _update(pk, **data):
            return self.put_json('/documents/%s/' % pk, data)

        # Interleave: update a, update b, update a, update b.
        _update(a, content='a2')
        _update(b, identifier='b-id-2')
        _update(a, identifier='a-id-2')
        _update(b, content='b2')

        self.assertLookupMaps('a-id-2', a)
        self.assertLookupMaps('b-id-2', b)
        self.assertEqual(self.get_json('/documents/a-id-2/')['content'], 'a2')
        self.assertEqual(self.get_json('/documents/b-id-2/')['content'], 'b2')
        self.assertNotFound('/documents/a-id/')
        self.assertNotFound('/documents/b-id/')
        self.assertLookupCount(2)
        self.assertEqual(Document.select().count(), 2)

        # Interleave: update a, update b, update a, update b.
        _update('a-id-2', content='a3')
        _update('b-id-2', identifier='b-id-3')
        _update('a-id-2', identifier='a-id-3')
        _update('b-id-3', content='b3')

        self.assertLookupMaps('a-id-3', a)
        self.assertLookupMaps('b-id-3', b)
        self.assertEqual(self.get_json('/documents/a-id-3/')['content'], 'a3')
        self.assertEqual(self.get_json('/documents/b-id-3/')['content'], 'b3')
        self.assertNotFound('/documents/a-id-2/')
        self.assertNotFound('/documents/b-id-2/')
        self.assertLookupCount(2)
        self.assertEqual(Document.select().count(), 2)

    def test_identifier_with_special_characters(self):
        Index.create(name='idx')
        # These identifiers are URL-safe and should round-trip via URL.
        safe_idents = ('has-dashes', 'dots.in.it', 'under_scores',
                       'key:value', 'MixedCase123')
        for ident in safe_idents:
            resp = self.post_json('/documents/', {
                'content': 'c',
                'identifier': ident,
                'index': 'idx'})
            pk = resp['id']

            # Lookup by identifier through URL works.
            resp = self.get_json('/documents/%s/' % ident)
            self.assertEqual(resp['id'], pk)
            self.assertLookupMaps(ident, pk)
            self.delete('/documents/%s/' % ident)
            self.assertLookupCount(0)

        # Identifiers with URL-unsafe characters (slashes, ?, %, spaces)
        # are not allowed.
        unsafe_idents = ('slashes/in/it', 'q?mark', 'pct%20enc',
                         'has spaces')
        for ident in unsafe_idents:
            resp = self.post_json('/documents/', {
                'content': 'c',
                'identifier': ident,
                'index': 'idx'})
            self.assertTrue('error' in resp)

    def test_create_with_identifier_matching_other_rowid(self):
        Index.create(name='idx')
        resp = self.post_json('/documents/', {
            'content': 'first doc',
            'index': 'idx'})
        pk = resp['id']

        resp = self.post_json('/documents/', {
            'content': 'second doc',
            'identifier': str(pk),
            'index': 'idx'})
        pk2 = resp['id']

        # Two separate documents exist.
        self.assertNotEqual(pk, pk2)
        self.assertEqual(Document.select().count(), 2)

        # Identifier '1' resolves to r2, not r1.
        resp = self.get_json('/documents/%s/' % pk)
        self.assertEqual(resp['id'], pk2)

        self.post_json('/documents/%s/' % pk, {'identifier': 'renamed'})
        resp = self.get_json('/documents/%s/' % pk)
        self.assertEqual(resp['content'], 'first doc')


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

        with assert_query_count(4) as ctx:
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
        for i in range(20):
            doc.attach('a%s.txt' % i, b'aaa')

        with assert_query_count(5) as ctx:
            data = self.get_json('/documents/%s/' % doc.get_id())

        self.assertEqual(len(data['attachments']), 20)

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

    def test_serialized_attachment_urls_resolve(self):
        idx = Index.create(name='idx')
        json_data = json.dumps({
            'content': 'doc with file',
            'index': 'idx',
            'identifier': 'att-test'})
        resp = self.app.post('/documents/', data={
            'data': json_data,
            'file_0': (BytesIO(b'xx'), 'foo.jpg'),
            'file_1': (BytesIO(b'yy'), 'foo2.jpg')})
        doc_id = json_load(resp.data)['id']

        # Attach another file.
        self.app.post('/documents/%s/attachments/' % doc_id, data={
            'data': '{}',
            'file_0': (BytesIO(b'zz'), 'foo3.txt')})

        data = {'foo.jpg': b'xx', 'foo2.jpg': b'yy', 'foo3.txt': b'zz'}

        # Get the attachment URL.
        for identifier in (doc_id, 'att-test'):
            detail = self.get_json('/documents/%s/' % identifier)
            self.assertEqual(len(detail['attachments']), 3)
            for att in detail['attachments']:
                att_url = att['data']

                # URL returns file data.
                response = self.app.get(att_url)
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.data, data[att['filename']])

    def test_attachment_list_no_dupes_multi_index(self):
        idx_a = Index.create(name='idx-a')
        idx_b = Index.create(name='idx-b')

        doc = idx_a.index('shared')
        idx_b.add_to_index(doc)
        doc.attach('f.txt', b'data')

        data = self.get_json('/attachments/?index=idx-a&index=idx-b')

        # The single attachment must appear exactly once.
        self.assertEqual(len(data['attachments']), 1)

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
        self.assertTrue('error' in data)

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
        self.assertEqual(data, {'error': 'No file attachments found.'})

    def test_attachment_update_file_count_errors(self):
        idx = Index.create(name='idx')
        doc = idx.index('doc')
        doc.attach('f.txt', b'original')

        # Update with no file.
        resp = self.app.post('/documents/%s/attachments/f.txt/' % doc.get_id(),
                             data={'data': '{}'})
        data = json_load(resp.data)
        self.assertEqual(data, {'error': 'No file attachment found.'})

        # Update with two files.
        resp = self.app.post(
            '/documents/%s/attachments/f.txt/' % doc.get_id(),
            data={
                'data': '{}',
                'file_0': (BytesIO(b'a'), 'f.txt'),
                'file_1': (BytesIO(b'b'), 'g.txt')})
        data = json_load(resp.data)
        self.assertEqual(data, {
            'error': 'Only one attachment permitted when performing update.'})

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

    def test_http_delete_attachment_cleans_orphaned_blobs(self):
        idx = Index.create(name='idx')
        d1 = idx.index('doc1')
        d2 = idx.index('doc2')

        d1.attach('unique.txt', b'only-here')
        self.app.delete('/documents/%s/attachments/unique.txt/' % d1.get_id())
        self.assertEqual(BlobData.select().count(), 0)

        d1.attach('shared.txt', b'shared-data')
        d2.attach('also-shared.txt', b'shared-data')
        self.app.delete('/documents/%s/attachments/shared.txt/' % d1.get_id())
        self.assertEqual(BlobData.select().count(), 1)


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

    def test_numeric_metadata_filter_via_http(self):
        idx = Index.create(name='idx')
        for i in (1, 5, 10, 20, 100):
            idx.index('item-%d' % i, price=str(i))

        data = self.search('idx', 'item*', price__gt='9')
        contents = sorted(d['content'] for d in data['documents'])
        self.assertEqual(contents, ['item-10', 'item-100', 'item-20'])

        data = self.search('idx', 'item*', price__le='5')
        contents = sorted(d['content'] for d in data['documents'])
        self.assertEqual(contents, ['item-1', 'item-5'])

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
        idx_c.index('doc1')
        idx_c.index('doc2')
        idx_c.index('doc3')
        idx_a.index('doc1')

        # Default: by name ascending.
        data = self.get_json('/')
        names = [idx['name'] for idx in data['indexes']]
        self.assertEqual(names, ['alpha', 'bravo', 'charlie'])

        # By name descending.
        data = self.get_json('/?ordering=-name')
        names = [idx['name'] for idx in data['indexes']]
        self.assertEqual(names, ['charlie', 'bravo', 'alpha'])

        # By document_count ascending.
        data = self.get_json('/?ordering=document_count')
        names = [idx['name'] for idx in data['indexes']]
        self.assertEqual(names, ['bravo', 'alpha', 'charlie'])

        # By document_count descending.
        data = self.get_json('/?ordering=-document_count')
        names = [idx['name'] for idx in data['indexes']]
        self.assertEqual(names, ['charlie', 'alpha', 'bravo'])

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
            url += ('&' if '?' in url else '?') + urlencode(kwargs, True)
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

    def test_index_delete_orphaned_docs(self):
        idx1 = self.scout.create_index('idx1')
        idx2 = self.scout.create_index('idx2')
        self.scout.create_document('doc 1', ['idx1'], identifier='d1')
        self.scout.create_document('doc 2', ['idx2'], identifier='d2')
        self.scout.create_document('doc 3', ['idx1', 'idx2'], identifier='d3')

        self.scout.delete_index('idx1')
        resp = [d['content'] for d in self.scout.get_documents()['documents']]
        self.assertEqual(sorted(resp), ['doc 1', 'doc 2', 'doc 3'])

        resp = self.scout.get_document('d1')
        self.assertEqual(resp['indexes'], [])

        resp = self.scout.get_document('d2')
        self.assertEqual(resp['indexes'], ['idx2'])

        resp = self.scout.get_document('d3')
        self.assertEqual(resp['indexes'], ['idx2'])

        resp = [d['content'] for d in self.scout.search('doc')['documents']]
        self.assertEqual(sorted(resp), ['doc 1', 'doc 2', 'doc 3'])

        self.scout.delete_index('idx2')

        resp = [d['content'] for d in self.scout.search('doc')['documents']]
        self.assertEqual(sorted(resp), ['doc 1', 'doc 2', 'doc 3'])

        resp = self.scout.create_index('idx1')
        for d in ('d1', 'd2', 'd3'):
            resp = self.scout.get_document(d)
            self.assertEqual(resp['indexes'], [])

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

    def test_update_metadata(self):
        self.scout.create_index('idx')
        doc = self.scout.create_document('test', 'idx')
        resp = self.scout.update_metadata(doc['id'], k1='v1', k2='v2')
        self.assertEqual(resp['metadata'], {'k1': 'v1', 'k2': 'v2'})

        resp = self.scout.update_metadata(doc['id'], k1='v1x', k3='v3')
        self.assertEqual(resp['metadata'], {
            'k1': 'v1x', 'k2': 'v2', 'k3': 'v3'})

        resp = self.scout.update_metadata(doc['id'], k1=None, k4='v4', k5=None)
        self.assertEqual(resp['metadata'], {
            'k2': 'v2', 'k3': 'v3', 'k4': 'v4'})

        resp = self.scout.update_metadata(doc['id'])
        self.assertEqual(resp['metadata'], {})

    def test_update_document_clear_identifier(self):
        self.scout.create_index('idx')
        doc = self.scout.create_document('text', 'idx', identifier='removable')
        self.assertEqual(DocLookup.select().count(), 1)

        updated = self.scout.update_document(doc['id'], identifier=None)
        self.assertIsNone(updated['identifier'])
        self.assertEqual(DocLookup.select().count(), 0)
        self.assertIsNone(Document.get_by_id(doc['id']).identifier)

    def test_create_without_identifier_no_lookup(self):
        self.scout.create_index('idx')
        doc = self.scout.create_document('no ident', 'idx')
        self.assertIsNone(doc['identifier'])
        self.assertEqual(DocLookup.select().count(), 0)

    def test_client_identifier_theft(self):
        self.scout.create_index('idx')
        a = self.scout.create_document('owner', 'idx', identifier='i1')
        b = self.scout.create_document('thief', 'idx', identifier='i2')

        self.scout.update_document('i2', identifier='i1')

        # Thief owns i1 now.
        found = self.scout.get_document('i1')
        self.assertEqual(found['id'], b['id'])
        self.assertEqual(found['content'], 'thief')

        # Victim's Document.identifier is cleared.
        victim = Document.get(Document.rowid == a['id'])
        self.assertIsNone(victim.identifier)
        self.assertRaises(DocLookup.DoesNotExist, DocLookup.get,
                          DocLookup.rowid == a['id'])

    def test_client_numeric_identifier(self):
        self.scout.create_index('idx')
        d1 = self.scout.create_document('first', 'idx')
        d2 = self.scout.create_document('second', 'idx',
                                         identifier=str(d1['id']))

        # Lookup by the numeric string returns d2 (identifier), not d1.
        found = self.scout.get_document(str(d1['id']))
        self.assertEqual(found['id'], d2['id'])
        self.assertEqual(found['content'], 'second')

        self.assertEqual(DocLookup.select().count(), 1)
        dl = DocLookup.get()
        self.assertEqual(dl.identifier, str(d1['id']))
        self.assertEqual(dl.rowid, d2['id'])

    def test_client_attachment_round_trip_via_identifier(self):
        self.scout.create_index('idx')
        doc = self.scout.create_document('host', 'idx', identifier='host-id')

        self.scout.attach_files('host-id', {'f.txt': BytesIO(b'data')})
        atts = self.scout.get_attachments('host-id')
        self.assertEqual(len(atts['attachments']), 1)

        downloaded = self.scout.download_attachment('host-id', 'f.txt')
        self.assertEqual(downloaded, b'data')

        # Also works via rowid.
        downloaded2 = self.scout.download_attachment(doc['id'], 'f.txt')
        self.assertEqual(downloaded2, b'data')

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

        # Filter by multiple indexes.
        result = self.scout.get_documents(index=['a', 'b'])
        self.assertEqual(result['document_count'], 3)

        # Filter by index as string.
        result = self.scout.get_documents(index='a')
        self.assertEqual(result['document_count'], 2)

        # Search via get_index.
        results = self.scout.get_index('a', q='bravo')
        self.assertEqual(len(results['documents']), 1)

        # Search via get_documents() and search().
        for method in (self.scout.get_documents, self.scout.search):
            results = method(q='bravo')
            self.assertEqual(len(results['documents']), 2)
            results = method(q='bravo', index='a')
            self.assertEqual(len(results['documents']), 1)

        # Metadata filter.
        results = self.scout.get_index('a', q='*', color='red')
        self.assertEqual(len(results['documents']), 2)

        # Ranking via get_index().
        results = self.scout.get_index('a', q='bravo', ranking='bm25')
        for doc in results['documents']:
            self.assertIn('score', doc)
        results = self.scout.get_index('a', q='bravo', ranking='none')
        for doc in results['documents']:
            self.assertNotIn('score', doc)

        # Ranking via get_documents() and search().
        for method in (self.scout.get_documents, self.scout.search):
            results = method(q='bravo', ranking='bm25')
            for doc in results['documents']:
                self.assertIn('score', doc)
            results = method(q='bravo', ranking='none')
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
        self.scout = FlaskScout(app)

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

    def assertClientResults(self, phrase, expected_indexes, **params):
        resp = self.scout.search(phrase, **params)
        self.assertEqual([doc['content'] for doc in resp['documents']],
                         [self.corpus[i] for i in expected_indexes])
        return resp


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

    def test_client_queries(self):
        self.assertClientResults('believe', [3, 0])
        self.assertClientResults('man OR hope', [0, 4])
        self.assertClientResults('believe NOT nothing', [3])
        self.assertClientResults('"true faith"', [1])
        self.assertClientResults('beli*', [3, 0])
        self.assertClientResults('NEAR(true faith, 1)', [1])
        self.assertClientResults('^faith', [3, 4])
        self.assertClientResults('(hope OR man) AND faith', [0, 4])


class TestFTS5ErrorHandling(FTS5TestCase):
    """
    Malformed FTS5 queries should return a 400 with a helpful message,
    not a 500 Internal Server Error.
    """
    def setUp(self):
        super().setUp()
        for content in self.corpus:
            self._add(content)

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
    """
    Two indexes ('notes' and 'events'), five documents each, with metadata.
    All searches use ``ordering='content'`` for deterministic alphabetical
    order unless testing ranking or pagination specifically.

    notes (n0–n4):
      n0: "python programming tips and tricks"             tag=tutorial  level=beginner
      n1: "advanced python techniques for data science"    tag=tutorial  level=advanced
      n2: "javascript frameworks overview and comparison"  tag=reference level=beginner
      n3: "database optimization strategies for queries"   tag=guide     level=advanced
      n4: "python machine learning fundamentals"           tag=guide     level=beginner

    events (e0–e4):
      e0: "python conference keynote speakers announced"   tag=conference year=2024
      e1: "javascript meetup downtown next friday"         tag=meetup    year=2024
      e2: "data science summit registration open"          tag=conference year=2025
      e3: "machine learning workshop for beginners"        tag=workshop  year=2025
      e4: "annual python developers gathering"             tag=conference year=2025
    """
    notes = [
        'python programming tips and tricks',
        'advanced python techniques for data science',
        'javascript frameworks overview and comparison',
        'database optimization strategies for queries',
        'python machine learning fundamentals',
    ]
    notes_meta = [
        {'tag': 'tutorial', 'level': 'beginner'},
        {'tag': 'tutorial', 'level': 'advanced'},
        {'tag': 'reference', 'level': 'beginner'},
        {'tag': 'guide', 'level': 'advanced'},
        {'tag': 'guide', 'level': 'beginner'},
    ]

    events = [
        'python conference keynote speakers announced',
        'javascript meetup downtown next friday',
        'data science summit registration open',
        'machine learning workshop for beginners',
        'annual python developers gathering',
    ]
    events_meta = [
        {'tag': 'conference', 'year': '2024'},
        {'tag': 'meetup', 'year': '2024'},
        {'tag': 'conference', 'year': '2025'},
        {'tag': 'workshop', 'year': '2025'},
        {'tag': 'conference', 'year': '2025'},
    ]

    def setUp(self):
        super().setUp()
        self.notes_idx = Index.create(name='notes')
        self.events_idx = Index.create(name='events')
        for content, meta in zip(self.notes, self.notes_meta):
            self.notes_idx.index(content=content, **meta)
        for content, meta in zip(self.events, self.events_meta):
            self.events_idx.index(content=content, **meta)

    def _search_idx(self, index_name, phrase, **params):
        """GET /<index_name>/?q=..."""
        params['q'] = phrase
        params.setdefault('ranking', SEARCH_BM25)
        qs = urlencode(params, doseq=True)
        response = self.app.get('/%s/?%s' % (index_name, qs))
        return json_load(response.data), response.status_code

    def _search_docs(self, phrase, **params):
        """GET /documents/?q=..."""
        params['q'] = phrase
        params.setdefault('ranking', SEARCH_BM25)
        qs = urlencode(params, doseq=True)
        response = self.app.get('/documents/?%s' % qs)
        return json_load(response.data), response.status_code

    def test_search_indexes(self):
        data, _ = self._search_idx('notes', 'python', ordering='content')
        self.assertEqual(self._contents(data), [
            self.notes[1],  # advanced python techniques ...
            self.notes[4],  # python machine learning ...
            self.notes[0],  # python programming tips ...
        ])

        data, _ = self._search_idx('events', 'python', ordering='content')
        self.assertEqual(self._contents(data), [
            self.events[4],  # annual python developers ...
            self.events[0],  # python conference keynote ...
        ])

        # Same results with client.
        data = self.scout.get_index('notes', q='python', ordering='content')
        self.assertEqual(self._contents(data), [
            self.notes[1],
            self.notes[4],
            self.notes[0],
        ])

        data = self.scout.get_index('events', q='python', ordering='content')
        self.assertEqual(self._contents(data), [
            self.events[4],
            self.events[0],
        ])

    def test_index_isolation(self):
        """A term unique to one index yields nothing in the other."""
        data, _ = self._search_idx('notes', 'conference', ordering='content')
        self.assertEqual(self._contents(data), [])

        data = self.scout.get_index('notes', q='conference',
                                    ordering='content')
        self.assertEqual(self._contents(data), [])

        data, _ = self._search_idx('events', 'database', ordering='content')
        self.assertEqual(self._contents(data), [])

        data = self.scout.get_index('events', q='database', ordering='content')
        self.assertEqual(self._contents(data), [])

    def test_search_all_indexes_via_documents(self):
        data, _ = self._search_docs('python', ordering='content')
        self.assertEqual(self._contents(data), [
            self.notes[1],   # advanced python techniques ...
            self.events[4],  # annual python developers ...
            self.events[0],  # python conference keynote ...
            self.notes[4],   # python machine learning ...
            self.notes[0],   # python programming tips ...
        ])

        data = self.scout.search('python', ordering='content')
        self.assertEqual(self._contents(data), [
            self.notes[1],   # advanced python techniques ...
            self.events[4],  # annual python developers ...
            self.events[0],  # python conference keynote ...
            self.notes[4],   # python machine learning ...
            self.notes[0],   # python programming tips ...
        ])

    def test_documents_single_index_filter(self):
        data, _ = self._search_docs('python', index='notes',
                                    ordering='content')
        self.assertEqual(self._contents(data), [
            self.notes[1],
            self.notes[4],
            self.notes[0],
        ])

        data = self.scout.search('python', index='notes', ordering='content')
        self.assertEqual(self._contents(data), [
            self.notes[1],
            self.notes[4],
            self.notes[0],
        ])

    def test_documents_multiple_index_filters(self):
        # Stick a python doc in the unused 'default' index.
        self.index.index(content='python stray document')

        data, _ = self._search_docs('python',
                                    index=['notes', 'events'],
                                    ordering='content')
        self.assertEqual(self._contents(data), [
            self.notes[1],
            self.events[4],
            self.events[0],
            self.notes[4],
            self.notes[0],
        ])

        data = self.scout.search('python', index=['notes', 'events'],
                                 ordering='content')
        self.assertEqual(self._contents(data), [
            self.notes[1],
            self.events[4],
            self.events[0],
            self.notes[4],
            self.notes[0],
        ])

    def test_shared_document_across_indexes(self):
        """A document in two indexes appears once, reachable from each."""
        txt = 'cross listed research paper'
        doc = Document.create(content=txt)
        self.notes_idx.add_to_index(doc)
        self.events_idx.add_to_index(doc)

        # Unfiltered.
        data, _ = self._search_docs('cross listed')
        self.assertEqual(self._contents(data), [txt])

        data = self.scout.search('cross listed')
        self.assertEqual(self._contents(data), [txt])

        # Each owning index.
        for name in ('notes', 'events'):
            data, _ = self._search_idx(name, 'cross listed')
            self.assertEqual(self._contents(data), [txt])

            data = self.scout.search('cross listed', index=name)
            self.assertEqual(self._contents(data), [txt])

            data = self.scout.get_index(name, q='cross listed')
            self.assertEqual(self._contents(data), [txt])

    def test_shared_deduped(self):
        i1 = Index.create(name='i1')
        i2 = Index.create(name='i2')
        i3 = Index.create(name='i3')
        a = Document.create(content='single doc')
        b = Document.create(content='double doc')
        c = Document.create(content='triple doc')
        a.metadata = {'k': 'v'}
        b.metadata = {'k': 'v'}
        c.metadata = {'k': 'v'}
        i1.add_to_index(a)
        i1.add_to_index(b)
        i1.add_to_index(c)
        i2.add_to_index(b)
        i2.add_to_index(c)
        i3.add_to_index(c)

        data, _ = self._search_docs('doc')
        self.assertEqual(self._contents(data), ['single doc', 'double doc',
                                                'triple doc'])

        data, _ = self._search_docs('doc', index=['i1', 'i2', 'i3'])
        self.assertEqual(self._contents(data), ['single doc', 'double doc',
                                                'triple doc'])

        data, _ = self._search_docs('doc', index=['i1', 'i3'])
        self.assertEqual(self._contents(data), ['single doc', 'double doc',
                                                'triple doc'])

        data, _ = self._search_docs('doc', index=['i2', 'i3'])
        self.assertEqual(self._contents(data), ['double doc', 'triple doc'])

        data, _ = self._search_docs('doc', index=['i3', 'i2'])
        self.assertEqual(self._contents(data), ['double doc', 'triple doc'])

        data, _ = self._search_docs('doc', index=['i3', 'i2'], k='v')
        self.assertEqual(self._contents(data), ['double doc', 'triple doc'])

        data, _ = self._search_docs('doc', index=['i3', 'i2'], k='x')
        self.assertEqual(self._contents(data), [])

        data, _ = self._search_docs('doc', index=['i3', 'i2', 'i4'])
        self.assertTrue('error' in data)

    def test_metadata_filtering(self):
        # Tag EQ.
        data, _ = self._search_idx('notes', 'python', tag='tutorial',
                                   ordering='content')
        self.assertEqual(self._contents(data), [
            self.notes[1],
            self.notes[0],
        ])

        data = self.scout.search('python', index='notes', tag='tutorial',
                                 ordering='content')
        self.assertEqual(self._contents(data), [
            self.notes[1],
            self.notes[0],
        ])

        # Tag NE.
        data, _ = self._search_idx('notes', 'python', tag__ne='tutorial',
                                   ordering='content')
        self.assertEqual(self._contents(data), [
            self.notes[4],  # tag=guide, not tutorial
        ])

        data = self.scout.search('python', index='notes', tag__ne='tutorial',
                                 ordering='content')
        self.assertEqual(self._contents(data), [
            self.notes[4],
        ])

        # Tag IN.
        data, _ = self._search_idx('notes', 'python',
                                   tag__in='tutorial,guide',
                                   ordering='content')
        self.assertEqual(self._contents(data), [
            self.notes[1],
            self.notes[4],
            self.notes[0],
        ])

        data = self.scout.search('python', index='notes',
                                 tag__in='tutorial,guide',
                                 ordering='content')
        self.assertEqual(self._contents(data), [
            self.notes[1],
            self.notes[4],
            self.notes[0],
        ])

        # Tag CONTAINS.
        data, _ = self._search_idx('events', '*', tag__contains='con',
                                   ordering='content')
        self.assertEqual(self._contents(data), [
            self.events[4],  # tag=conference
            self.events[2],  # tag=conference
            self.events[0],  # tag=conference
        ])

        data = self.scout.search('*', index='events', tag__contains='con',
                                 ordering='content')
        self.assertEqual(self._contents(data), [
            self.events[4],
            self.events[2],
            self.events[0],
        ])

        # Two metadata conditions are ANDed with the FTS match.
        data, _ = self._search_idx('notes', 'python',
                                   tag='tutorial', level='beginner',
                                   ordering='content')
        self.assertEqual(self._contents(data), [
            self.notes[0],  # tutorial + beginner
        ])

        data = self.scout.search('python', index='notes', tag='tutorial',
                                 level='beginner', ordering='content')
        self.assertEqual(self._contents(data), [
            self.notes[0],
        ])

        # Two metadata conditions for same field are ORed together.
        data, _ = self._search_idx('notes', 'python',
                                   tag=['tutorial', 'guide'],
                                   ordering='content')
        self.assertEqual(self._contents(data), [
            self.notes[1],
            self.notes[4],
            self.notes[0],
        ])

        data = self.scout.search('python', index='notes',
                                 tag=['tutorial', 'guide'],
                                 ordering='content')
        self.assertEqual(self._contents(data), [
            self.notes[1],
            self.notes[4],
            self.notes[0],
        ])

    def test_metadata_filters_in_response(self):
        data, _ = self._search_idx('events', 'python', tag='conference')
        self.assertEqual(data['filters'], {'tag': ['conference']})

        data = self.scout.search('python', index='events', tag='conference')
        self.assertEqual(data['filters'], {'tag': ['conference']})

    def test_ranking_options(self):
        data, _ = self._http_search('testing', ranking='none')
        self.assertEqual(data['ranking'], 'none')

        data = self.scout.search('testing', ranking='none')
        self.assertEqual(data['ranking'], 'none')

        data, _ = self._http_search('testing', ranking='bm25')
        self.assertEqual(data['ranking'], 'bm25')

        data = self.scout.search('testing', ranking='bm25')
        self.assertEqual(data['ranking'], 'bm25')

        _, status = self._http_search('testing', ranking='magic')
        self.assertEqual(status, 400)

        resp = self.scout.search('testing', ranking='magic')
        self.assertTrue(resp['error'].startswith('Unrecognized "ranking" '))

    def test_ordering_results(self):
        data, _ = self._search_idx('notes', '*', ordering='content')
        self.assertEqual(self._contents(data), [
            self.notes[1],
            self.notes[3],
            self.notes[2],
            self.notes[4],
            self.notes[0],
        ])

        data = self.scout.search('*', index='notes', ordering='content')
        self.assertEqual(self._contents(data), [
            self.notes[1],
            self.notes[3],
            self.notes[2],
            self.notes[4],
            self.notes[0],
        ])

        data, _ = self._search_idx('notes', '*', ordering='-content')
        self.assertEqual(self._contents(data), [
            self.notes[0],
            self.notes[4],
            self.notes[2],
            self.notes[3],
            self.notes[1],
        ])

        data = self.scout.search('*', index='notes', ordering='-content')
        self.assertEqual(self._contents(data), [
            self.notes[0],
            self.notes[4],
            self.notes[2],
            self.notes[3],
            self.notes[1],
        ])

        data, _ = self._search_idx('notes', 'python', ordering='id')
        # Notes n0, n1, n4 inserted first, second, fifth -> id order.
        self.assertEqual(self._contents(data), [
            self.notes[0],
            self.notes[1],
            self.notes[4],
        ])

        data = self.scout.search('python', index='notes', ordering='id')
        self.assertEqual(self._contents(data), [
            self.notes[0],
            self.notes[1],
            self.notes[4],
        ])

        data, _ = self._search_idx('notes', 'python', ordering='-id')
        self.assertEqual(self._contents(data), [
            self.notes[4],
            self.notes[1],
            self.notes[0],
        ])

        data = self.scout.search('python', index='notes', ordering='-id')
        self.assertEqual(self._contents(data), [
            self.notes[4],
            self.notes[1],
            self.notes[0],
        ])

        data, status = self._http_search('testing', ordering='invalid')
        self.assertEqual(status, 400)

        data = self.scout.search('testing', ordering='invalid')
        self.assertTrue(data['error'].startswith('Unrecognized'))

    def test_bm25_scores_present_and_sorted(self):
        data_idx, _ = self._search_idx('notes', 'python')
        data_doc, _ = self._search_docs('python', index='notes')
        data_client = self.scout.search('python', index='notes')

        for data in (data_idx, data_doc, data_client):
            scores = [d['score'] for d in data['documents']]
            self.assertEqual(len(scores), 3)
            for s in scores:
                self.assertIsInstance(s, float)
            self.assertEqual(scores, sorted(scores))

    def test_ranking_none_suppresses_scores(self):
        data_idx, _ = self._search_idx('notes', 'python', ranking='none')
        data_doc, _ = self._search_docs('python', index='notes',
                                        ranking='none')
        data_client = self.scout.search('python', index='notes',
                                        ranking='none')

        for data in (data_idx, data_doc, data_client):
            self.assertEqual(len(data['documents']), 3)
            for doc in data['documents']:
                self.assertNotIn('score', doc)

            # Docs returned in ID order.
            self.assertEqual(self._contents(data), [
                self.notes[0], self.notes[1], self.notes[4],
            ])

    def test_explicit_ordering_preserves_scores(self):
        data_idx, _ = self._search_idx('notes', 'python', ordering='id')
        data_doc, _ = self._search_docs('python', index='notes', ordering='id')
        data_client = self.scout.search('python', index='notes', ordering='id')

        for data in (data_idx, data_doc, data_client):
            self.assertEqual(self._contents(data), [
                self.notes[0],
                self.notes[1],
                self.notes[4],
            ])
            for doc in data['documents']:
                self.assertIn('score', doc)
                self.assertIsInstance(doc['score'], float)

    def test_pagination(self):
        for i in range(12):
            self.notes_idx.index(content='testing document %02d' % i)

        expected = sorted(['testing document %02d' % i for i in range(12)])

        # Page 1: first 10 alphabetically.
        p1_idx, _ = self._search_idx('notes', 'testing', ordering='content')
        p1_docs, _ = self._search_docs('testing', index='notes',
                                       ordering='content')
        p1_client = self.scout.search('testing', index='notes',
                                      ordering='content')
        for p1 in (p1_idx, p1_docs, p1_client):
            self.assertEqual(p1['filtered_count'], 12)
            self.assertEqual(p1['page'], 1)
            self.assertEqual(p1['pages'], 2)
            self.assertIsNotNone(p1['next_url'])
            self.assertIsNone(p1['previous_url'])
            self.assertEqual(self._contents(p1), expected[:10])

        # Page 2: remaining 2.
        p2_idx, _ = self._search_idx('notes', 'testing', ordering='content',
                                     page=2)
        p2_docs, _ = self._search_docs('testing', index='notes',
                                       ordering='content', page=2)
        p2_client = self.scout.search('testing', index='notes',
                                      ordering='content', page=2)
        for p2 in (p2_idx, p2_docs, p2_client):
            self.assertEqual(p2['page'], 2)
            self.assertIsNone(p2['next_url'])
            self.assertIsNotNone(p2['previous_url'])
            self.assertEqual(self._contents(p2), expected[10:])

    def test_pagination_beyond_last_page(self):
        p_idx, _ = self._search_idx('notes', 'python', page=99)
        p_docs, _ = self._search_docs('python', index='notes', page=99)
        p_client = self.scout.search('python', index='notes', page=99)
        for p in (p_idx, p_docs, p_client):
            self.assertEqual(p['page'], 99)
            self.assertEqual(p['filtered_count'], 3)
            self.assertEqual(self._contents(p), [])

class Entry(object):
    def __init__(self, title, body, pk):
        self.title = title
        self.body = body
        self.pk = pk

class EntryProvider(SearchProvider):
    def content(self, entry):
        return '%s: %s' % (entry.title, entry.body)
    def identifier(self, entry):
        return 'entry:%s' % entry.pk
    def metadata(self, entry):
        return {'id': entry.pk, 'title': entry.title}

class TestSearchSite(BaseTestCase):
    def setUp(self):
        super(TestSearchSite, self).setUp()
        app.config['AUTHENTICATION'] = None
        self.app = app.test_client()
        self.index = Index.create(name='default')
        self.scout = FlaskScout(app)
        self.site = SearchSite(self.scout, 'default')
        self.site.register(Entry, EntryProvider)

    def test_search_site(self):
        entries = [Entry(title='t%s' % i, body='b%s' % i, pk=i)
                   for i in range(3)]
        for entry in entries:
            self.site.store(entry)

        resp = self.scout.get_index('default')
        self.assertEqual([d['content'] for d in resp['documents']],
                         ['t0: b0', 't1: b1', 't2: b2'])
        self.assertEqual([d['identifier'] for d in resp['documents']],
                         ['entry:0', 'entry:1', 'entry:2'])
        self.assertEqual([d['metadata']['id'] for d in resp['documents']],
                         ['0', '1', '2'])
        self.assertEqual([d['metadata']['title'] for d in resp['documents']],
                         ['t0', 't1', 't2'])

        entries[1].title = 't1-x'
        entries[2].body = 'b2-x'
        self.site.store(entries[1])
        self.site.store(entries[2])

        resp = self.scout.get_index('default')
        self.assertEqual([d['content'] for d in resp['documents']],
                         ['t0: b0', 't1-x: b1', 't2: b2-x'])
        self.assertEqual([d['identifier'] for d in resp['documents']],
                         ['entry:0', 'entry:1', 'entry:2'])
        self.assertEqual([d['metadata']['id'] for d in resp['documents']],
                         ['0', '1', '2'])
        self.assertEqual([d['metadata']['title'] for d in resp['documents']],
                         ['t0', 't1-x', 't2'])

        self.site.remove(entries[1])
        resp = self.scout.get_index('default')
        self.assertEqual([d['content'] for d in resp['documents']],
                         ['t0: b0', 't2: b2-x'])
        self.assertEqual([d['identifier'] for d in resp['documents']],
                         ['entry:0', 'entry:2'])
        self.assertEqual([d['metadata']['id'] for d in resp['documents']],
                         ['0', '2'])
        self.assertEqual([d['metadata']['title'] for d in resp['documents']],
                         ['t0', 't2'])


def main():
    option_parser = get_option_parser()
    options, args = option_parser.parse_args()
    unittest.main(argv=sys.argv, verbosity=not options.quiet and 2 or 0)


if __name__ == '__main__':
    main()
