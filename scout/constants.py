SEARCH_BM25 = 'bm25'
SEARCH_NONE = 'none'
RANKING_CHOICES = (SEARCH_BM25, SEARCH_NONE)

PROTECTED_KEYS = set(('page', 'q', 'key', 'ranking', 'identifier', 'index',
                      'ordering'))
