import base64
import datetime
import hashlib
import mimetypes
import sys

from peewee import *
from playhouse.fields import CompressedField
from playhouse.sqlite_ext import *
try:
    from playhouse.sqlite_ext import CSqliteExtDatabase as SqliteExtDatabase
except ImportError:
    pass
try:
    from werkzeug import secure_filename
except ImportError:
    from werkzeug.utils import secure_filename


if sys.version_info[0] == 2:
    unicode_type = unicode
else:
    unicode_type = str


database = SqliteExtDatabase(None, regexp_function=True)


class Document(FTSModel):
    """
    The :py:class:`Document` class contains content which should be indexed
    for search. Documents can be associated with any number of indexes via
    the `IndexDocument` junction table. Because `Document` is implemented
    as an FTS virtual table, it does not support any secondary indexes, and
    all columns have *Text* type, regardless of their declared type. For that
    reason we will utilize the internal SQLite `docid` column to relate
    documents to indexes.
    """
    content = SearchField()
    identifier = SearchField()

    class Meta:
        database = database
        options = {
            'prefix': [2, 3],
            'tokenize': 'porter unicode61'}
        table_name = 'main_document'

    @classmethod
    def all(cls):
        return Document.select(Document.docid, Document.content,
                               Document.identifier)

    def get_metadata(self):
        return dict(Metadata
                    .select(Metadata.key, Metadata.value)
                    .where(Metadata.document == self.docid)
                    .tuples())

    def set_metadata(self, metadata):
        (Metadata
         .replace_many([
             {'key': key, 'value': value, 'document': self.docid}
             for key, value in metadata.items()])
         .execute())

    def delete_metadata(self):
        Metadata.delete().where(Metadata.document == self.docid).execute()

    metadata = property(get_metadata, set_metadata, delete_metadata)

    def get_indexes(self):
        return (Index
                .select()
                .join(IndexDocument)
                .where(IndexDocument.document == self.docid))

    def attach(self, filename, data):
        filename = secure_filename(filename)
        if isinstance(data, unicode_type):
            data = data.encode('utf-8')
        hash_obj = hashlib.sha256(data)
        data_hash = base64.b64encode(hash_obj.digest())
        try:
            with database.atomic():
                data_obj = BlobData.create(hash=data_hash, data=data)
        except IntegrityError:
            pass

        mimetype = mimetypes.guess_type(filename)[0] or 'text/plain'
        try:
            with database.atomic():
                attachment = Attachment.create(
                    document=self,
                    filename=filename,
                    hash=data_hash,
                    mimetype=mimetype)
        except IntegrityError:
            attachment = (Attachment
                          .get((Attachment.document == self) &
                               (Attachment.filename == filename)))
            attachment.hash = data_hash
            attachment.mimetype = mimetype
            attachment.save(only=[Attachment.hash, Attachment.mimetype])

        return attachment

    def detach(self, filename):
        return (Attachment
                .delete()
                .where((Attachment.document == self) &
                       (Attachment.filename == filename))
                .execute())


class BaseModel(Model):
    class Meta:
        database = database


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

    def index(self, content, document=None, identifier=None, **metadata):
        if document is None:
            document = Document.create(
                content=content,
                identifier=identifier)
        else:
            del document.metadata
            nrows = (Document
                     .update(
                         content=content,
                         identifier=identifier)
                     .where(Document.docid == document.docid)
                     .execute())

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
