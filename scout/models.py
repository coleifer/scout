import base64
import datetime
import hashlib
import mimetypes
import sys

from peewee import *
from playhouse.fields import CompressedField
from playhouse.sqlite_ext import *
try:
    SqliteExtDatabase
except NameError:
    SqliteExtDatabase = SqliteDatabase
from werkzeug.utils import secure_filename

from scout.constants import SENTINEL


database = SqliteExtDatabase(None, regexp_function=True)


class Document(FTS5Model):
    """
    The :py:class:`Document` class contains content which should be indexed
    for search. Documents can be associated with any number of indexes via
    the `IndexDocument` junction table. Because `Document` is implemented
    as an FTS virtual table, it does not support any secondary indexes, and
    all columns have *Text* type, regardless of their declared type. For that
    reason we will utilize the internal SQLite `rowid` column to relate
    documents to indexes.
    """
    content = SearchField()
    identifier = SearchField(unindexed=True)

    class Meta:
        database = database
        options = {
            'prefix': [2, 3],
            'tokenize': 'porter unicode61'}
        table_name = 'main_document'

    @classmethod
    def all(cls):
        return Document.select(Document.rowid, Document.content,
                               Document.identifier)

    def get_metadata(self):
        return dict(Metadata
                    .select(Metadata.key, Metadata.value)
                    .where(Metadata.document == self.rowid)
                    .tuples())

    def set_metadata(self, metadata, clear=True):
        if clear:
            del self.metadata
        if metadata:
            (Metadata
             .replace_many([
                 {'key': key, 'value': value, 'document': self.rowid}
                 for key, value in metadata.items() if value is not None])
             .execute())

            nulls = [k for k in metadata if metadata[k] is None]
            if nulls:
                Metadata.delete().where(
                    (Metadata.document == self.rowid) &
                    (Metadata.key.in_(nulls))).execute()

    def delete_metadata(self):
        Metadata.delete().where(Metadata.document == self.rowid).execute()

    metadata = property(get_metadata, set_metadata, delete_metadata)

    def get_indexes(self):
        return (Index
                .select()
                .join(IndexDocument)
                .where(IndexDocument.document == self.rowid))

    def attach(self, filename, data):
        filename = secure_filename(filename) or 'unnamed'
        mimetype = mimetypes.guess_type(filename)[0] or 'text/plain'
        if isinstance(data, str):
            data = data.encode('utf-8')
        hash_obj = hashlib.sha256(data)
        data_hash = base64.b64encode(hash_obj.digest())
        with database.atomic():
            # If updating a pre-existing attachment w/this filename, first
            # delete - this ensures blobdata is cleaned up as well if needed.
            self.detach(filename)

            try:
                with database.atomic():
                    data_obj = BlobData.create(hash=data_hash, data=data)
            except IntegrityError:
                pass

            attachment = Attachment.create(
                document=self,
                filename=filename,
                hash=data_hash,
                mimetype=mimetype)

        return attachment

    def detach(self, filename):
        with database.atomic():
            try:
                attachment = Attachment.get(
                    (Attachment.document == self) &
                    (Attachment.filename == filename))
            except Attachment.DoesNotExist:
                return 0

            attachment.delete_instance()
            return 1


class BaseModel(Model):
    class Meta:
        database = database


class DocLookup(BaseModel):
    rowid = RowIDField()
    identifier = TextField(unique=True)

    class Meta:
        table_name = 'main_doclookup'

    @classmethod
    def get_document(cls, pk):
        try:
            return (Document
                    .all()
                    .join(DocLookup, on=(DocLookup.rowid == Document.rowid))
                    .where(DocLookup.identifier == pk)
                    .get())
        except Document.DoesNotExist:
            pass

        if isinstance(pk, int) or (isinstance(pk, str) and pk.isdigit()):
            return Document.all().where(Document.rowid == pk).get()

        raise Document.DoesNotExist()

    @classmethod
    def set_identifier(cls, document, identifier):
        """
        Single entry-point for updating a document's identifier. Keeps
        Document.identifier and the DocLookup table in sync.

        Must be called inside a database.atomic() block together with
        any subsequent document.save() to guarantee consistency.
        """
        if identifier:
            # If another document currently owns this identifier, clear it.
            (Document
             .update(identifier=None)
             .where((Document.identifier == identifier) &
                    (Document.rowid != document.rowid))
             .execute())
            (DocLookup.delete()
             .where(DocLookup.identifier == identifier)
             .execute())

            # Insert or update previous identifier for this document.
            (DocLookup
             .replace(rowid=document.rowid, identifier=identifier)
             .execute())

            document.identifier = identifier
        else:
            if document.identifier:
                cls.delete().where(cls.rowid == document.rowid).execute()
            document.identifier = None


class Attachment(BaseModel):
    """
    A mapping of a BLOB to a Document.
    """
    document = ForeignKeyField(Document, backref='attachments')
    hash = TextField()
    filename = TextField(index=True)
    mimetype = TextField()
    timestamp = DateTimeField(default=datetime.datetime.now, index=True)

    class Meta:
        indexes = (
            (('document', 'filename'), True),
        )

    def delete_instance(self):
        ret = super(Attachment, self).delete_instance()

        # Clean up orphaned blob data.
        blob_refs = (Attachment
                     .select()
                     .where(Attachment.hash == self.hash)
                     .exists())
        if not blob_refs:
            BlobData.delete().where(BlobData.hash == self.hash).execute()

        return ret

    @property
    def blob(self):
        if not hasattr(self, '_blob'):
            self._blob = BlobData.get(BlobData.hash == self.hash)
        return self._blob

    @property
    def length(self):
        return len(self.blob.data)


class BlobData(BaseModel):
    """Content-addressable BLOB."""
    hash = TextField(primary_key=True)
    data = CompressedField(compression_level=6, algorithm='zlib')


class Metadata(BaseModel):
    """
    Arbitrary key/value pairs associated with an indexed `Document`. The
    metadata associated with a document can also be used to filter search
    results.
    """
    document = ForeignKeyField(Document, backref='metadata_set')
    key = TextField()
    value = TextField()

    class Meta:
        indexes = (
            (('document', 'key'), True),
            (('key', 'value'), False),
        )
        table_name = 'main_metadata'


class Index(BaseModel):
    """
    Indexes contain any number of documents and expose a clean API for
    searching and storing content.
    """
    name = TextField(unique=True)

    class Meta:
        table_name = 'main_index'

    def add_to_index(self, document):
        with database.atomic():
            try:
                IndexDocument.create(index=self, document=document)
            except IntegrityError:
                pass

    def index(self, content, document=None, identifier=SENTINEL, **metadata):
        identifier_value = None if identifier is SENTINEL else identifier

        if document is None and identifier_value:
            try:
                document = DocLookup.get_document(identifier_value)
            except Document.DoesNotExist:
                pass

        with database.atomic():
            if document is None:
                document = Document.create(
                    content=content,
                    identifier=identifier_value)
                if identifier_value:
                    DocLookup.set_identifier(document, identifier_value)
            else:
                del document.metadata
                document.content = content
                if identifier is not SENTINEL:
                    DocLookup.set_identifier(document, identifier_value)
                document.save()

        self.add_to_index(document)
        if metadata:
            document.metadata = metadata
        return document

    @property
    def documents(self):
        return (Document
                .all()
                .join(IndexDocument)
                .where(IndexDocument.index == self))


class IndexDocument(BaseModel):
    index = ForeignKeyField(Index)
    document = ForeignKeyField(Document)

    class Meta:
        indexes = (
            (('index', 'document'), True),
        )
        table_name = 'main_index_document'
