import operator

from flask import url_for
from peewee import prefetch

from scout.models import Attachment
from scout.models import Document
from scout.models import Index
from scout.models import IndexDocument
from scout.models import Metadata


class Serializer(object):
    def serialize(self, model, **options):
        raise NotImplementedError

    def serialize_query(self, query, **options):
        # NB: note really used.
        return [self.serialize(obj, **options) for obj in query]


class DocumentSerializer(Serializer):
    def serialize(self, document, prefetched=False, include_score=False):
        data = {
            'id': document.rowid,
            'identifier': document.identifier,
            'content': document.content,
        }

        _filename = operator.attrgetter('filename')
        data['attachments'] = [{
            'filename': attachment.filename,
            'mimetype': attachment.mimetype,
            'timestamp': str(attachment.timestamp),
            'data': url_for(
                'attachment_download',
                document_id=document.rowid,
                pk=attachment.filename)}
            for attachment in sorted(document.attachments, key=_filename)]

        if prefetched:
            data['metadata'] = dict((metadata.key, metadata.value)
                                    for metadata in document.metadata_set)
            data['indexes'] = [idx_doc.index.name
                               for idx_doc in document.indexdocument_set]
        else:
            data['metadata'] = document.metadata
            indexes = (Index
                       .select(Index.name)
                       .join(IndexDocument)
                       .where(IndexDocument.document == document.rowid)
                       .order_by(Index.name)
                       .tuples())
            data['indexes'] = [name for name, in indexes]

        if include_score:
            data['score'] = document.score

        return data

    def serialize_query(self, query, include_score=False):
        documents = prefetch(
            query,
            Attachment,
            Metadata,
            IndexDocument,
            Index)
        return [self.serialize(document, prefetched=True,
                               include_score=include_score)
                for document in documents]


class AttachmentSerializer(Serializer):
    def serialize(self, attachment):
        data = {
            'filename': attachment.filename,
            'mimetype': attachment.mimetype,
            'timestamp': str(attachment.timestamp),
            'data_length': attachment.length,
            'document': url_for('document_view_detail',
                                pk=attachment.document_id),
            'data': url_for('attachment_download',
                            document_id=attachment.document_id,
                            pk=attachment.filename)}
        return data


class IndexSerializer(Serializer):
    def serialize(self, index):
        if hasattr(index, 'document_count'):
            document_count = index.document_count
        else:
            document_count = index.documents.count()
        return {
            'id': index.id,
            'name': index.name,
            'documents': url_for('index_view_detail', pk=index.name),
            'document_count': document_count}
