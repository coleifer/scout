.. _search_queries:

Search Query Syntax
===================

Scout uses `SQLite FTS5 <https://www.sqlite.org/fts5.html>`_ for full-text
search. The ``q`` parameter on any search endpoint accepts the full FTS5 query
syntax, giving you powerful tools for building precise queries.

.. note::

    All search queries operate on the **content** field only. The
    ``identifier`` field is used internally for upsert logic and is excluded
    from search matching and scoring. You never need to specify a column name
    in your queries.

The examples below assume you have a client initialized:

.. code-block:: python

    from scout.client import Scout
    scout = Scout('http://localhost:8000')

Most examples use :py:meth:`~Scout.search`, which searches across all indexes
(or a specified subset). To restrict a search to a single index, use
:py:meth:`~Scout.get_index` instead — the query syntax is identical.

Quick Reference
---------------

.. list-table::
   :header-rows: 1
   :widths: 30 30 40

   * - Feature
     - Syntax
     - Example
   * - Single term
     - ``word``
     - ``q='python'``
   * - Implicit AND
     - ``word1 word2``
     - ``q='python web'``
   * - OR
     - ``word1 OR word2``
     - ``q='flask OR django'``
   * - NOT
     - ``word1 NOT word2``
     - ``q='python NOT java'``
   * - Phrase
     - ``"word1 word2"``
     - ``q='"web framework"'``
   * - Prefix
     - ``prefix*``
     - ``q='frame*'``
   * - NEAR
     - ``NEAR(w1 w2, N)``
     - ``q='NEAR(python web, 5)'``
   * - Initial token
     - ``^word``
     - ``q='^python'``
   * - Grouping
     - ``(expr)``
     - ``q='(flask OR django) AND python'``
   * - All documents
     - ``*``
     - ``q='*'``

Simple Queries
--------------

The simplest query is a single word. It matches any document whose content
contains that word (after stemming - see below).

.. code-block:: python

    results = scout.search('python')

Multiple words are joined with **implicit AND**, all terms must be present in
the document:

.. code-block:: python

    results = scout.search('python web framework')

This returns only documents that contain *all three* of the words ``python``,
``web``, and ``framework``.

To restrict a search to specific indexes, pass ``index`` as a string or list:

.. code-block:: python

    # Single index
    results = scout.search('python', index='my-index')

    # Multiple indexes
    results = scout.search('python', index=['idx1', 'idx2'])

You can also use :py:meth:`~Scout.get_index` to search within a single index:

.. code-block:: python

    results = scout.get_index('my-index', q='python')

All Documents
^^^^^^^^^^^^^

You can use the wildcard ``'*'`` search query and filter directly on metadata
across all documents:

.. code-block:: python

    results = scout.search('*', category='tutorial')

Alternately, you can omit the query and search across a single index or all
indexes:

.. code-block:: python

    # Just in "my-index".
    results = scout.get_index('my-index', category='tutorial')

    # All documents.
    results = scout.get_documents(category='tutorial')

Boolean Operators
-----------------

FTS5 supports three boolean operators: **AND**, **OR**, and **NOT**. Operators
must be **UPPERCASE**.

**OR**: match documents containing *either* term:

.. code-block:: python

    results = scout.search('flask OR django')

**NOT**: exclude documents containing a term:

.. code-block:: python

    results = scout.search('python NOT javascript')

**AND**: explicitly require both terms (this is the default, so ``python AND
web`` is equivalent to ``python web``):

.. code-block:: python

    results = scout.search('python AND web')

Use **parentheses** to group sub-expressions:

.. code-block:: python

    results = scout.search('(flask OR django) AND python')

This matches documents that contain ``python`` and at least one of ``flask``
or ``django``.

A more complex example:

.. code-block:: python

    results = scout.search('(flask OR django) NOT javascript')

Phrase Queries
--------------

Wrap terms in **double quotes** to require an exact sequence of tokens:

.. code-block:: python

    results = scout.search('"web framework"')

The query ``"web framework"`` matches ``a web framework for python`` but not
``the framework is web-based`` (because the tokens are not adjacent).

Phrases can be combined with boolean operators:

.. code-block:: python

    results = scout.search('"web framework" OR "REST API"')

Prefix Queries
--------------

Append ``*`` to a token to match any word that starts with that prefix:

.. code-block:: python

    results = scout.search('frame*')

This matches ``framework``, ``frameworks``, ``framed``, etc.

.. note::

    Scout's FTS index is configured with ``prefix = [2, 3]``, meaning 2- and
    3-character prefixes are pre-indexed for fast lookup. Longer prefixes work
    too, but the first two/three characters benefit from the index.

Prefix queries combine naturally with other features:

.. code-block:: python

    results = scout.search('pyth* NOT javascript')

NEAR Queries
------------

The ``NEAR`` operator matches documents where two or more terms appear within a
specified distance (in tokens) of each other:

.. code-block:: python

    results = scout.search('NEAR(python web, 3)')

This matches documents where ``python`` and ``web`` are within 3 tokens of each
other. The default distance (when omitted) is 10:

.. code-block:: python

    results = scout.search('NEAR(python web)')

Initial Token Queries
---------------------

The ``^`` operator matches only if the token appears at the very **beginning**
of the content field:

.. code-block:: python

    results = scout.search('^python')

This matches ``python web framework`` but not ``learning python basics``.

Stemming
--------

Scout uses the **Porter** stemmer with the **unicode61** tokenizer. This means
queries automatically match morphological variants of words:

* ``run`` matches ``running``, ``runs``
* ``belief`` matches ``believe``, ``believes``, ``believing``
* ``connection`` matches ``connected``, ``connect``, ``connecting``,
  ``connects``, etc.

Stemming is applied to both document content at index time and to query terms
at search time, so you do not need to worry about exact word forms.

Case Sensitivity
^^^^^^^^^^^^^^^^

All queries are **case-insensitive**. The queries ``Python``, ``python``, and
``PYTHON`` all return the same results.

Combining Features
------------------

All of the above features can be combined freely:

.. code-block:: python

    # Phrase + boolean + prefix
    results = scout.search('"web framework" OR pyth*')

    # NEAR + NOT
    results = scout.search('NEAR(python web, 5) NOT django')

    # Initial token + boolean grouping
    results = scout.search('^python AND (flask OR django)')

    # Complex grouped expression
    results = scout.search('(flask OR django) AND "REST API" NOT legacy')

Combined with metadata filters:

.. code-block:: python

    # Using search() across all indexes
    results = scout.search(
        'python OR javascript',
        category='tutorial',
        level='beginner')

    # Using get_index() to also restrict to a single index
    results = scout.get_index(
        'my-index',
        q='python OR javascript',
        category='tutorial',
        level='beginner')

For the full set of metadata filter operations, see :ref:`metadata_filters`.

Error Handling
--------------

If you send a malformed query (unbalanced quotes, dangling operators, etc),
Scout will return a **400 Bad Request** with a JSON error message:

.. code-block:: javascript

    {"error": "Invalid search query: unterminated string"}

Common mistakes:

- ``"unclosed quote``
- ``AND OR foo`` - consecutive operators
- ``(foo AND bar`` - unbalanced parentheses
- ``NOT`` - operator with no operand

Ranking
-------

By default, search results are ranked using the `BM25 algorithm
<http://en.wikipedia.org/wiki/Okapi_BM25>`_, which is built into SQLite FTS5.
Documents that are a better match for your query appear first.

Each document in the response includes a ``score`` field. **Scores are
negative**, and lower (more negative) values indicate better matches:

.. code-block:: javascript

    {
      "content": "python web framework flask tutorial",
      "score": -1.4206,
      ...
    }

This convention comes from SQLite FTS5's built-in ``rank`` column, which
returns negative BM25 values so that a simple ascending sort puts the best
matches first. A score of ``-2.98`` is a better match than ``-0.02``.

You can control ranking with the ``ranking`` parameter:

.. code-block:: python

    # Default BM25 ranking (best match first)
    results = scout.search('python', ranking='bm25')

    # No ranking — results returned in insertion order, score omitted
    results = scout.search('python', ranking='none')

You can also control sort order with the ``ordering`` parameter:

.. code-block:: python

    # Sort by score (best match first — this is the default with BM25)
    results = scout.search('python', ordering='score')

    # Sort by ID descending (newest first)
    results = scout.search('python', ordering='-id')

    # Sort by content alphabetically
    results = scout.search('python', ordering='content')

Valid ordering choices: ``id``, ``identifier``, ``content``, ``score``
(only when a search query is present). Prefix with ``-`` for descending.
