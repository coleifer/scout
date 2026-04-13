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

Simple Queries
--------------

The simplest query is a single word. It matches any document whose content
contains that word (after stemming - see below).

.. code-block:: console

    $ curl "localhost:8000/my-index/?q=python"

.. code-block:: python

    results = scout.get_index('my-index', q='python')

Multiple words are joined with **implicit AND**, all terms must be present in
the document:

.. code-block:: console

    $ curl "localhost:8000/my-index/?q=python+web+framework"

.. code-block:: python

    results = scout.get_index('my-index', q='python web framework')

This returns only documents that contain *all three* of the words ``python``,
``web``, and ``framework``.

To query across multiple indexes (or all indexes) you can use the documents
endpoint:

.. code-block:: console

    $ curl "localhost:8000/documents/?q=python&index=idx1&index=idx2"

.. code-block:: python

    results = scout.search('python', index=['idx1', 'idx2'])


All Documents
^^^^^^^^^^^^^

You can omit a query and filter directly on metadata across all documents:

.. code-block:: console

    $ curl "localhost:8000/my-index/?category=tutorial"

Alternately, you can use the wildcard ``'*'`` to accomplish the same:

.. code-block:: console

    $ curl "localhost:8000/my-index/?category=tutorial&q=*"

Boolean Operators
-----------------

FTS5 supports three boolean operators: **AND**, **OR**, and **NOT**. Operators
must be **UPPERCASE**.

**OR**: match documents containing *either* term:

.. code-block:: console

    $ curl "localhost:8000/my-index/?q=flask+OR+django"

**NOT**: exclude documents containing a term:

.. code-block:: console

    $ curl "localhost:8000/my-index/?q=python+NOT+javascript"

**AND**: explicitly require both terms (this is the default, so ``python AND
web`` is equivalent to ``python web``):

.. code-block:: console

    $ curl "localhost:8000/my-index/?q=python+AND+web"

Use **parentheses** to group sub-expressions:

.. code-block:: console

    $ curl "localhost:8000/my-index/?q=(flask+OR+django)+AND+python"

This matches documents that contain ``python`` and at least one of ``flask``
or ``django``.

A more complex example:

.. code-block:: console

    $ curl "localhost:8000/my-index/?q=(flask+OR+django)+NOT+javascript"

Phrase Queries
--------------

Wrap terms in **double quotes** to require an exact sequence of tokens:

.. code-block:: console

    $ curl 'localhost:8000/my-index/?q="web+framework"'

.. code-block:: python

    results = scout.get_index('my-index', q='"web framework"')

The query ``"web framework"`` matches ``a web framework for python`` but not
``the framework is web-based`` (because the tokens are not adjacent).

Phrases can be combined with boolean operators:

.. code-block:: console

    $ curl 'localhost:8000/my-index/?q="web+framework"+OR+"REST+API"'

Prefix Queries
--------------

Append ``*`` to a token to match any word that starts with that prefix:

.. code-block:: console

    $ curl "localhost:8000/my-index/?q=frame*"

This matches ``framework``, ``frameworks``, ``framed``, etc.

.. note::

    Scout's FTS index is configured with ``prefix = [2, 3]``, meaning 2- and
    3-character prefixes are pre-indexed for fast lookup. Longer prefixes work
    too, but the first two/three characters benefit from the index.

Prefix queries combine naturally with other features:

.. code-block:: console

    $ curl "localhost:8000/my-index/?q=pyth*+NOT+javascript"

NEAR Queries
------------

The ``NEAR`` operator matches documents where two or more terms appear within a
specified distance (in tokens) of each other:

.. code-block:: console

    $ curl "localhost:8000/my-index/?q=NEAR(python+web,+3)"

.. code-block:: python

    results = scout.get_index('my-index', q='NEAR(python web, 3)')

This matches documents where ``python`` and ``web`` are within 3 tokens of each
other. The default distance (when omitted) is 10.

.. code-block:: console

    # Default distance of 10
    $ curl "localhost:8000/my-index/?q=NEAR(python+web)"

Initial Token Queries
---------------------

The ``^`` operator matches only if the token appears at the very **beginning**
of the content field:

.. code-block:: console

    $ curl "localhost:8000/my-index/?q=^python"

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

.. code-block:: console

    # Phrase + boolean + prefix
    $ curl 'localhost:8000/my-index/?q="web+framework"+OR+pyth*'

    # NEAR + NOT
    $ curl "localhost:8000/my-index/?q=NEAR(python+web,+5)+NOT+django"

    # Initial token + boolean grouping
    $ curl "localhost:8000/my-index/?q=^python+AND+(flask+OR+django)"

    # Complex grouped expression
    $ curl 'localhost:8000/my-index/?q=(flask+OR+django)+AND+"REST+API"+NOT+legacy'

Combined with metadata filters:

.. code-block:: console

    # Full-text search + metadata filters
    $ curl "localhost:8000/my-index/?q=python+OR+javascript&category=tutorial&level=beginner"

.. code-block:: python

    results = scout.get_index(
        'my-index',
        q='python OR javascript',
        category='tutorial',
        level='beginner')

Error Handling
--------------

If you send a malformed query (unbalanced quotes, dangling operators, etc),
Scout will return a **400 Bad Request** with a JSON error message:

.. code-block:: console

    $ curl 'localhost:8000/my-index/?q="unbalanced'
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

* ``ranking=bm25`` - (default) use BM25 ranking.
* ``ranking=none`` - no ranking; results are returned in rowid (insertion)
  order and the ``score`` field is omitted.

You can also control sort order with the ``ordering`` parameter:

.. code-block:: console

    # Sort by score (best match first — this is the default with BM25)
    $ curl "localhost:8000/my-index/?q=python&ordering=score"

    # Sort by ID descending (newest first)
    $ curl "localhost:8000/my-index/?q=python&ordering=-id"

    # Sort by content alphabetically
    $ curl "localhost:8000/my-index/?q=python&ordering=content"

Valid ordering choices: ``id``, ``identifier``, ``content``, ``score``
(only when a search query is present). Prefix with ``-`` for descending.

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
     - ``q=python``
   * - Implicit AND
     - ``word1 word2``
     - ``q=python web``
   * - OR
     - ``word1 OR word2``
     - ``q=flask OR django``
   * - NOT
     - ``word1 NOT word2``
     - ``q=python NOT java``
   * - Phrase
     - ``"word1 word2"``
     - ``q="web framework"``
   * - Prefix
     - ``prefix*``
     - ``q=frame*``
   * - NEAR
     - ``NEAR(w1 w2, N)``
     - ``q=NEAR(python web, 5)``
   * - Initial token
     - ``^word``
     - ``q=^python``
   * - Grouping
     - ``(expr)``
     - ``q=(flask OR django) AND python``
   * - All documents
     - ``*``
     - ``q=*``
