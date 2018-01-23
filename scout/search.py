try:
    from functools import reduce
except ImportError:
    pass
import operator

from peewee import fn
from peewee import Select

from .constants import PROTECTED_KEYS
from .constants import SEARCH_BM25
from .constants import SEARCH_NONE
from .constants import SEARCH_SIMPLE
from .exceptions import InvalidSearchException
from .exceptions import error
from .models import Document
from .models import Index
from .models import IndexDocument
from .models import Metadata


class DocumentSearch(object):
    def search(self, phrase, index=None, ranking='bm25', ordering=None,
               **filters):
        phrase = phrase.strip()
        if not phrase:
            raise InvalidSearchException('Must provide a search query.')
        elif phrase == '*' or ranking == SEARCH_NONE:
            ranking = None

        query = Document.select()
        if phrase != '*':
            query = query.where(Document.match(phrase))

        # Allow filtering by index(es).
        if index is not None:
            query = query.join(IndexDocument)
            if isinstance(index, (list, tuple, Select)):
                query = query.where(IndexDocument.index << index)
            else:
                query = query.where(IndexDocument.index == index)

        # Allow filtering by metadata.
        metadata_expr = self.get_metadata_filter_expression(filters)
        if metadata_expr is not None:
            query = query.where(metadata_expr)

        # Allow sorting and ranking.
        return self.apply_rank_and_sort(query, ranking, ordering or ())

    def get_metadata_filter_expression(self, filters):
        valid_keys = [key for key in filters if key not in PROTECTED_KEYS]
        if valid_keys:
            return reduce(operator.and_, [
                self._build_filter_expression(key, values)
                for key, values in filters.items()])

    @staticmethod
    def _build_filter_expression(key, values):
        def in_(lhs, rhs):
            return lhs << ([i.strip() for i in rhs.split(',')])
        operations = {
            'eq': operator.eq,
            'ne': operator.ne,
            'ge': operator.ge,
            'gt': operator.gt,
            'le': operator.le,
            'lt': operator.lt,
            'in': in_,
            'contains': lambda l, r: operator.pow(l, '%%%s%%' % r),
            'startswith': lambda l, r: operator.pow(l, '%s%%' % r),
            'endswith': lambda l, r: operator.pow(l, '%%%s' % r),
            'regex': lambda l, r: l.regexp(r),
        }
        if key.find('__') != -1:
            key, op = key.rsplit('__', 1)
            if op not in operations:
                error('Unrecognized operation: %s. Supported operations are:'
                      '\n%s' % (op, '\n'.join(sorted(operations.keys()))))
        else:
            op = 'eq'

        op = operations[op]
        if isinstance(values, (list, tuple)):
            expr = reduce(operator.or_, [
                ((Metadata.key == key) & op(Metadata.value, value))
                for value in values])
        else:
            expr = ((Metadata.key == key) & op(Metadata.value, values))

        return fn.EXISTS(Metadata.select().where(
            expr &
            (Metadata.document == Document.docid)))

    def apply_rank_and_sort(self, query, ranking, ordering, sort_options=None,
                            sort_default='id'):
        sort_options = sort_options or {
            'content': Document.content,
            'id': Document.docid,
            'identifier': Document.identifier,
        }
        if ranking is not None:
            rank = self.get_rank_expression(ranking)
            sort_options['score'] = rank
            sort_default = 'score'

            # Add score to the selected columns.
            query = query.select(*query._returning + [rank.alias('score')])

        return self.apply_sorting(query, ordering, sort_options, sort_default)

    def get_rank_expression(self, ranking):
        if ranking == SEARCH_BM25:
            # Search only the content field, do not search the identifiers.
            return Document.bm25(1.0, 0.0)
        elif ranking == SEARCH_SIMPLE:
            # Search only the content field, do not search the identifiers.
            return Document.rank(1.0, 0.0)
        else:
            error('Unrecognized ranking: "%s"' % ranking)

    def apply_sorting(self, query, ordering, mapping, default):
        sortables = [part.strip() for part in ordering]
        accum = []
        for identifier in sortables:
            is_desc = identifier.startswith('-')
            identifier = identifier.lstrip('-')
            if identifier in mapping:
                value = mapping[identifier]
                accum.append(value.desc() if is_desc else value)

        if not accum:
            accum = [mapping[default]]

        return query.order_by(*accum)
