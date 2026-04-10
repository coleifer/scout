.. _example:

Examples
========

This document walks through two complete examples showing how to use Scout in
practice. Both examples use the :ref:`Python client <client>`, but every
operation has an equivalent ``curl`` call documented in the :ref:`server`
reference.

.. contents:: In this document
   :local:
   :depth: 2


Example 1: Personal Blog
-------------------------

Consider a personal blog with two kinds of searchable content: **entries** and
**comments**. We will create a separate index for each, populate them with
documents, attach images to entries, and then search and filter the results.

Setting up
^^^^^^^^^^

Start the server and create a client:

.. code-block:: python

    from scout.client import Scout

    scout = Scout('http://localhost:8000')

Create the two indexes:

.. code-block:: python

    scout.create_index('blog-entries')
    scout.create_index('blog-comments')

Indexing blog entries
^^^^^^^^^^^^^^^^^^^^^

Each blog entry becomes a document whose ``content`` is the full text of the
post. Metadata stores structured fields we will want to filter on later:

.. code-block:: python

    scout.create_document(
        'Welcome to my blog!  This is my very first post, where I introduce '
        'myself and talk about what I plan to write about.',
        'blog-entries',
        identifier='entry-1',
        title='Welcome to my blog!',
        url='/blog/welcome/',
        published='true',
        date='2026-01-15')

    scout.create_document(
        'Today my cat ate a spider and later he was sick.',
        'blog-entries',
        identifier='entry-2',
        title='Spider Adventures',
        url='/blog/spiders/',
        published='true',
        date='2026-02-03')

    scout.create_document(
        'My cat ate another spider, I could tell because there were some '
        'legs on his bed. He was not sick, so it must have been a different '
        'type of spider',
        'blog-entries',
        identifier='entry-3',
        title='More Spider News',
        url='/blog/more-spiders/',
        published='true',
        date='2026-03-20')

    # A draft that has not been published yet.
    scout.create_document(
        'Draft post about pest control...still fleshing out ideas here.',
        'blog-entries',
        identifier='entry-4',
        title='Pest Control (draft)',
        url='/blog/pest-control/',
        published='false',
        date='2024-04-01')

Attaching images
^^^^^^^^^^^^^^^^

If your blog entries have a primary image, you can attach it to the document so
that search results can display a thumbnail:

.. code-block:: python

    scout.attach_files(
        scout.get_document('entry-2')['id'],
        {'spider.jpg': open('/path/to/spider.jpg', 'rb')})

    scout.attach_files(
        scout.get_document('entry-3')['id'],
        {'spider-remnants.png': open('/path/to/spider-remnants.png', 'rb')})

When you retrieve or search documents later, each result will include an
``attachments`` list with download URLs.

Indexing comments
^^^^^^^^^^^^^^^^^

Comments are stored in a separate index. The metadata includes the parent
entry's identifier (for filtering) and a spam flag:

.. code-block:: python

    scout.create_document(
        'Looking forward to the content',
        'blog-comments',
        identifier='comment-1',
        entry_id='entry-1',
        author='alice',
        spam='false',
        date='2026-01-16')

    scout.create_document(
        'What did the spider look like?',
        'blog-comments',
        identifier='comment-2',
        entry_id='entry-2',
        author='bob',
        spam='false',
        date='2026-02-04')

    scout.create_document(
        'Buy cheap watches at http://example.com',
        'blog-comments',
        identifier='comment-3',
        entry_id='entry-2',
        author='spambot',
        spam='true',
        date='2026-02-04')

Searching entries
^^^^^^^^^^^^^^^^^

Full-text search over all published entries:

.. code-block:: python

    results = scout.get_index('blog-entries', q='spiders', published='true')
    for doc in results['documents']:
        print(doc['metadata']['title'], '-', doc['metadata']['url'], doc['score'])
    # Spider Adventures - /blog/spiders/ -0.268...
    # More Spider News - /blog/more-spiders/ -0.252...

Search with a wildcard to match prefixes:

.. code-block:: python

    results = scout.get_index('blog-entries', q='spid*')
    for doc in results['documents']:
        print(doc['metadata']['title'])
    # Spider Adventures
    # More Spider News

Filtering by date range (all entries from February 2026 onward):

.. code-block:: python

    results = scout.get_index(
        'blog-entries',
        published='true',
        date__ge='2026-02-01')
    for doc in results['documents']:
        print(doc['metadata']['date'], doc['metadata']['title'])
    # 2026-02-03 Spider Adventures
    # 2026-03-20 More Spider News

Exclude drafts from results:

.. code-block:: python

    results = scout.get_index('blog-entries', published='true')
    print(len(results['documents']))  # 3 (the draft is excluded)

Searching comments
^^^^^^^^^^^^^^^^^^

Find all non-spam comments on a particular entry:

.. code-block:: python

    results = scout.get_index(
        'blog-comments',
        entry_id='entry-2',
        spam='false')
    for doc in results['documents']:
        print(doc['metadata']['author'], ':', doc['content'])
    # bob : What did the spider look like?

Search comments across all entries:

.. code-block:: python

    results = scout.get_index('blog-comments', q='spiders', spam='false')
    for doc in results['documents']:
        print(doc['metadata']['author'], 'on', doc['metadata']['entry_id'])
    # bob on entry-2

Updating and deleting
^^^^^^^^^^^^^^^^^^^^^

Publish a draft by updating its metadata:

.. code-block:: python

    doc = scout.get_document('entry-4')
    scout.update_document(
        document_id=doc['id'],
        metadata={
            'title': 'Pest Control',
            'url': '/blog/pest-control/',
            'published': 'true',
            'date': '2026-04-10',
        })

Remove a spam comment:

.. code-block:: python

    doc = scout.get_document('comment-3')
    scout.delete_document(doc['id'])

Example 2: News Website
------------------------

A news website has several content types — articles, local events, and sports
scores — each in its own index. A **master** index that contains every document
allows site-wide search.

Setting up
^^^^^^^^^^

.. code-block:: python

    from scout.client import Scout

    scout = Scout('http://localhost:8000')

    scout.create_index('articles')
    scout.create_index('events')
    scout.create_index('sports')
    scout.create_index('master')  # Everything goes here too.

Indexing content
^^^^^^^^^^^^^^^^

A helper function keeps things DRY by always adding documents to the master
index alongside the category-specific index:

.. code-block:: python

    def index_content(content, category, **metadata):
        """Index a piece of content into its category index and the master index."""
        return scout.create_document(
            content,
            [category, 'master'],
            **metadata)

    # Articles
    index_content(
        'The city council voted Tuesday to approve the new downtown park '
        'proposal after months of public debate.',
        'articles',
        identifier='article-100',
        headline='City Council Approves Downtown Park',
        section='local',
        date='2024-06-11')

    index_content(
        'Global markets rallied on Friday after the central bank signaled a '
        'pause in rate hikes.  Tech stocks led the gains.',
        'articles',
        identifier='article-101',
        headline='Markets Rally on Rate Pause Signal',
        section='business',
        date='2024-06-14')

    index_content(
        'A new study shows that urban green spaces significantly improve '
        'mental health outcomes for nearby residents.',
        'articles',
        identifier='article-102',
        headline='Green Spaces Linked to Better Mental Health',
        section='science',
        date='2024-06-15')

    # Local events
    index_content(
        'The annual Summer Jazz Festival returns to Riverside Park on July 4th '
        'with headlining performances by several Grammy-winning artists.',
        'events',
        identifier='event-200',
        title='Summer Jazz Festival',
        venue='Riverside Park',
        date='2024-07-04')

    index_content(
        'Downtown Farmers Market every Saturday morning from 8am to noon.  '
        'Fresh produce, baked goods, and local crafts.',
        'events',
        identifier='event-201',
        title='Downtown Farmers Market',
        venue='Main Street Plaza',
        date='2024-06-01',
        recurring='true')

    # Sports scores
    index_content(
        'The Lions defeated the Bears 27-14 in a dominant home performance.  '
        'Quarterback Smith threw for 3 touchdowns.',
        'sports',
        identifier='game-300',
        home_team='Lions',
        away_team='Bears',
        score='27-14',
        date='2024-06-09')

    index_content(
        'Eagles and Hawks played to a 1-1 draw in a rain-soaked match.  '
        'Both goals came in the second half.',
        'sports',
        identifier='game-301',
        home_team='Eagles',
        away_team='Hawks',
        score='1-1',
        date='2024-06-10')

Searching within a category
^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Search only articles:

.. code-block:: python

    results = scout.get_index('articles', q='park')
    for doc in results['documents']:
        print(doc['metadata']['headline'])
    # City Council Approves Downtown Park

Filter articles by section:

.. code-block:: python

    results = scout.get_index('articles', section='business')
    for doc in results['documents']:
        print(doc['metadata']['headline'])
    # Markets Rally on Rate Pause Signal

Search only events at a particular venue:

.. code-block:: python

    results = scout.get_index('events', venue='Riverside Park')
    for doc in results['documents']:
        print(doc['metadata']['title'], '-', doc['metadata']['date'])
    # Summer Jazz Festival - 2024-07-04

Search sports results for a specific team:

.. code-block:: python

    results = scout.get_index('sports', home_team='Lions')
    for doc in results['documents']:
        print(doc['metadata']['home_team'], 'vs', doc['metadata']['away_team'],
              doc['metadata']['score'])
    # Lions vs Bears 27-14

Site-wide search
^^^^^^^^^^^^^^^^

The master index lets you search across every content type at once:

.. code-block:: python

    results = scout.get_index('master', q='park')
    for doc in results['documents']:
        print(doc['indexes'], doc['content'][:60] + '...')
    # ['articles', 'master'] The city council voted Tuesday to approve the new do...
    # ['events', 'master']   The annual Summer Jazz Festival returns to Riverside ...

Using the documents endpoint with multiple indexes achieves the same thing
without a dedicated master index:

.. code-block:: python

    results = scout.get_documents(
        q='park',
        index=['articles', 'events', 'sports'])
    for doc in results['documents']:
        print(doc['content'][:60] + '...')

Date range queries work the same way across all indexes:

.. code-block:: python

    results = scout.get_index(
        'master',
        date__ge='2024-06-10',
        date__le='2024-06-15')
    for doc in results['documents']:
        print(doc['metadata']['date'], doc['content'][:50] + '...')

Working with attachments
^^^^^^^^^^^^^^^^^^^^^^^^^

Attach a PDF of the full print article:

.. code-block:: python

    doc = scout.get_document('article-100')
    scout.attach_files(doc['id'], {
        'downtown-park-full.pdf': open('downtown-park-full.pdf', 'rb'),
    })

Download the attachment to a local file:

.. code-block:: python

    raw_bytes = scout.download_attachment(doc['id'], 'downtown-park-full.pdf')
    with open('downloaded-article.pdf', 'wb') as fh:
        fh.write(raw_bytes)

Later, find all PDF attachments across the articles index:

.. code-block:: python

    pdfs = scout.search_attachments(index='articles', mimetype='application/pdf')
    for att in pdfs['attachments']:
        print(att['filename'], att['data_length'], 'bytes')
    # downtown-park-full.pdf 84521 bytes

Using SearchSite for automatic indexing
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

If your application uses model classes, you can use :py:class:`~scout.client.SearchSite`
to automatically index and remove objects without manually calling
``create_document`` and ``delete_document``:

.. code-block:: python

    from scout.client import Scout, SearchProvider, SearchSite

    class ArticleProvider(SearchProvider):
        def content(self, article):
            return '%s %s' % (article.headline, article.body)

        def identifier(self, article):
            return 'article-%s' % article.id

        def metadata(self, article):
            return {
                'headline': article.headline,
                'section': article.section,
                'date': str(article.pub_date),
            }

    scout = Scout('http://localhost:8000')
    site = SearchSite(scout, 'articles')
    site.register(Article, ArticleProvider)

    # When a new article is created:
    site.store(article)

    # When an article is deleted:
    site.remove(article)

This pattern works well inside ORM hooks (such as Peewee ``post_save`` and
``post_delete`` signals or Django signals) to keep the search index in sync
with your database automatically.
