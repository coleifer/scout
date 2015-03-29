import json
import optparse
import sys
import unittest
import urllib

from playhouse.test_utils import assert_query_count

from scout import app
from scout import database
from scout import Document
from scout import IndexDocument
from scout import Index
from scout import Metadata


def get_option_parser():
    parser = optparse.OptionParser()
    parser.add_option(
        '-q',
        '--quiet',
        action='store_true',
        dest='quiet')
    return parser


class BaseTestCase(unittest.TestCase):
    def setUp(self):
        database.drop_tables([
            Document,
            Metadata,
            Index,
            IndexDocument], safe=True)

        Document.create_table(tokenize='porter')
        database.create_tables([
            Metadata,
            Index,
            IndexDocument])

class TestModelAPIs(BaseTestCase):
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
        self.assertEqual(doc.rowid, 1)
        self.assertEqual(doc.content, content)
        self.assertEqual(doc.metadata, {})

        # Verify through relationship properties.
        self.assertEqual(IndexDocument.select().count(), 1)
        idx_doc = IndexDocument.get()
        self.assertEqual(idx_doc._data['document'], doc.rowid)
        self.assertEqual(idx_doc._data['index'], self.index.id)

    def test_index_with_metadata(self):
        """
        Test to ensure that content can be indexed with arbitrary key
        value metadata, which is stored as strings.
        """
        doc = self.index.index('test doc', foo='bar', nugget=33)
        self.assertEqual(doc.rowid, 1)
        self.assertEqual(doc.metadata, {'foo': 'bar', 'nugget': '33'})

    def test_reindex(self):
        """
        Test that an existing document can be re-indexed, updating the
        content and metadata in the process.
        """
        doc = self.index.index('test doc', foo='bar', baze='nug')
        doc_db = Document.select(Document.rowid, Document.content).get()
        self.assertTrue(doc_db.rowid is not None)
        self.assertEqual(doc_db.content, 'test doc')
        self.assertEqual(doc_db.metadata, {'foo': 'bar', 'baze': 'nug'})

        updated_doc = self.index.index(
            'updated doc',
            document=doc,
            foo='bazz',
            nug='x')
        self.assertEqual(Document.select().count(), 1)
        self.assertEqual(updated_doc.metadata, {'foo': 'bazz', 'nug': 'x'})

        u_doc_db = Document.select(Document.rowid, Document.content).get()
        self.assertEqual(u_doc_db.content, 'updated doc')
        self.assertEqual(u_doc_db.rowid, doc_db.rowid)
        self.assertEqual(u_doc_db.metadata, {'foo': 'bazz', 'nug': 'x'})

        # Verify through relationship properties.
        self.assertEqual(IndexDocument.select().count(), 1)
        idx_doc = IndexDocument.get()
        self.assertEqual(idx_doc._data['document'], u_doc_db.rowid)
        self.assertEqual(idx_doc._data['index'], self.index.id)

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
            {'document': document.rowid, 'name': 'idx-0'},
            {'document': document.rowid, 'name': 'idx-1'},
            {'document': document.rowid, 'name': 'idx-2'},
        ])

    def test_search(self):
        """
        Basic tests for simple string searches of a single index. Use both
        the simple and bm25 ranking algorithms.
        """
        for idx, content in enumerate(self.corpus):
            self.index.index(content=content)

        def assertSearch(phrase, indexes, ranking=Index.RANK_SIMPLE):
            results = [doc.content
                       for doc in self.index.search(phrase, ranking)]
            self.assertEqual(results, [self.corpus[idx] for idx in indexes])

        assertSearch('believe', [3, 0])
        assertSearch('faith man', [0])
        assertSearch('faith thing', [4, 2])
        assertSearch('things', [4, 2])
        assertSearch('blah', [])
        assertSearch('', [])

        assertSearch('believe', [3, 0], Index.RANK_BM25)  # Same result.
        assertSearch('faith thing', [2, 4], Index.RANK_BM25)  # Swapped.
        assertSearch('things', [4, 2], Index.RANK_BM25)  # Same result.
        assertSearch('blah', [], Index.RANK_BM25)  # No results, works.
        assertSearch('', [], Index.RANK_BM25)


class TestSearchViews(BaseTestCase):
    def setUp(self):
        super(TestSearchViews, self).setUp()
        self.app = app.test_client()
        app.config['AUTHENTICATION'] = None

    def post_json(self, url, data, parse_response=True):
        response = self.app.post(url, data=json.dumps(data))
        if parse_response:
            return json.loads(response.data)
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
        data = json.loads(response.data)
        self.assertEqual(
            data,
            {'error': 'Unable to parse JSON data from request.'})

    def test_index_list(self):
        for i in range(3):
            Index.create(name='i%s' % i)

        response = self.app.get('/')
        data = json.loads(response.data)
        self.assertEqual(data['indexes'], [
            {'documents': 0, 'id': 1, 'name': 'i0'},
            {'documents': 0, 'id': 2, 'name': 'i1'},
            {'documents': 0, 'id': 3, 'name': 'i2'},
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
        data = json.loads(response.data)
        self.assertEqual(data['page'], 1)
        self.assertEqual(data['pages'], 2)
        self.assertEqual(len(data['documents']), 10)
        doc = data['documents'][0]
        self.assertEqual(doc, {
            'content': 'document-0',
            'id': 1,
            'indexes': ['idx-a'],
            'metadata': {'foo': 'bar-0'}})

        response = self.app.get('/idx-a/?page=2')
        data = json.loads(response.data)
        self.assertEqual(data['page'], 2)
        self.assertEqual(data['pages'], 2)
        self.assertEqual(len(data['documents']), 2)

        response = self.app.get('/idx-b/')
        data = json.loads(response.data)
        self.assertEqual(data['page'], 1)
        self.assertEqual(data['pages'], 1)
        self.assertEqual(len(data['documents']), 1)
        doc = data['documents'][0]
        self.assertEqual(doc, {
            'content': 'both-doc',
            'id': 12,
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
        data = json.loads(response.data)
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
            'content': 'doc 1',
            'id': 1,
            'indexes': ['idx-a'],
            'metadata': {'k1': 'v1', 'k2': 'v2'}})

        response = self.post_json('/documents/', {
            'content': 'doc 2',
            'indexes': ['idx-a', 'idx-b']})
        self.assertEqual(response, {
            'content': 'doc 2',
            'id': 2,
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

    def test_document_detail_get(self):
        idx = Index.create(name='idx')
        doc = idx.index('test doc', foo='bar')
        alt_doc = idx.index('alt doc')

        response = self.app.get('/documents/%s/' % doc.rowid)
        data = json.loads(response.data)
        self.assertEqual(data, {
            'content': 'test doc',
            'id': doc.rowid,
            'indexes': ['idx'],
            'metadata': {'foo': 'bar'}})

    def refresh_doc(self, doc):
        return Document.all().where(Document.rowid == doc.rowid).get()

    def test_document_detail_post(self):
        idx = Index.create(name='idx')
        alt_idx = Index.create(name='alt-idx')
        doc = idx.index('test doc', foo='bar', nug='baze')
        alt_doc = idx.index('alt doc')

        url = '/documents/%s/' % doc.rowid

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

    def test_document_detail_delete(self):
        idx = Index.create(name='idx')
        alt_idx = Index.create(name='alt-idx')

        d1 = idx.index('doc 1', k1='v1', k2='v2')
        d2 = idx.index('doc 2', k3='v3')
        alt_idx.add_to_index(d1)
        alt_idx.add_to_index(d2)

        self.assertEqual(Metadata.select().count(), 3)

        response = self.app.delete('/documents/%s/' % d2.rowid)
        data = json.loads(response.data)
        self.assertEqual(data, {'success': True})

        self.assertEqual(Metadata.select().count(), 2)

        response = self.app.delete('/documents/%s/' % d2.rowid)
        self.assertEqual(response.status_code, 404)

        self.assertEqual(Document.select().count(), 1)
        self.assertEqual(IndexDocument.select().count(), 2)
        self.assertEqual([d.rowid for d in idx.documents], [d1.rowid])
        self.assertEqual([d.rowid for d in alt_idx.documents], [d1.rowid])

    def search(self, index, query, page=1, **filters):
        params = urllib.urlencode(dict(filters, q=query, page=page))
        response = self.app.get('/%s/search/?%s' % (index, params))
        return json.loads(response.data)

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

        first_doc = response['documents'][0]
        self.assertEqual(round(first_doc['score'], 3), .059)

        response = self.search('idx', 'document', 2)
        self.assertEqual(len(response['documents']), 7)

        response = self.search('idx', 'doc* nug*')
        self.assertEqual(response['page'], 1)
        self.assertEqual(response['pages'], 1)
        self.assertEqual(len(response['documents']), 2)
        doc1, doc2 = response['documents']

        self.assertEqual(doc1, {
            'content': 'document nug nugs',
            'id': doc1['id'],
            'indexes': ['idx'],
            'metadata': {'special': 'True'},
            'score': doc1['score']})
        self.assertEqual(round(doc1['score'], 4), .7255)

        self.assertEqual(doc2, {
            'content': 'document blah nuggie foo',
            'id': doc2['id'],
            'indexes': ['idx'],
            'metadata': {'special': 'True'},
            'score': doc2['score']})
        self.assertEqual(round(doc2['score'], 4), .3922)

        response = self.search('idx', 'missing')
        self.assertEqual(len(response['documents']), 0)

        response = self.search('idx', 'nug', ranking='bm25')
        doc = response['documents'][0]
        self.assertEqual(doc['content'], 'document nug nugs')
        self.assertEqual(round(doc['score'], 3), 2.891)

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

        assertResults(
            'huey',
            {},
            ['huey document', 'little huey bear', 'uncle huey'])
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
                with assert_query_count(6):
                    # 1. Get index.
                    # 2. Prefetch indexes.
                    # 3. Prefetch index documents.
                    # 4. Prefetch metadata
                    # 5. Fetch documents (top of prefetch).
                    # 6. COUNT(*) for pagination.
                    self.search(idx, query)

                with assert_query_count(6):
                    self.search(idx, query, foo='bar')

        with assert_query_count(6):
            # Same as above.
            self.app.get('/idx-a/')

        with assert_query_count(5):
            # Same as above minus first query for index.
            self.app.get('/documents/')

        for i in range(10):
            Index.create(name='idx-%s' % i)

        with assert_query_count(1):
            self.app.get('/')

    def test_authentication(self):
        Index.create(name='idx')

        app.config['AUTHENTICATION'] = 'test'
        resp = self.app.get('/')
        self.assertEqual(resp.status_code, 401)
        self.assertEqual(resp.data, 'Invalid API key')

        resp = self.app.get('/?key=tesss')
        self.assertEqual(resp.status_code, 401)

        resp = self.app.get('/', headers={'key': 'tesss'})
        self.assertEqual(resp.status_code, 401)

        resp = self.app.get('/?key=test')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(json.loads(resp.data), {'indexes': [
            {'id': 1, 'name': 'idx', 'documents': 0}]})

        resp = self.app.get('/', headers={'key': 'test'})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(json.loads(resp.data), {'indexes': [
            {'id': 1, 'name': 'idx', 'documents': 0}]})


def main():
    option_parser = get_option_parser()
    options, args = option_parser.parse_args()
    database.init(':memory:')
    app.config['PAGINATE_BY'] = 10
    unittest.main(argv=sys.argv, verbosity=not options.quiet and 2 or 0)


if __name__ == '__main__':
    main()
