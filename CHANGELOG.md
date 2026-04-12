## Changelog

This document describes changes to Scout from one release to another.

## master

* **Backwards-incompatible**: switch to FTS5. A migration script is
  provided as well as a command-line option to perform the migration. Note that
  FTS5 is much stricter about search queries, but also more performant and more
  powerful.
* Use a separate doc lookup table for O(log(N)) lookups by identifier instead
  of previous implementation which required table scan of the index. This is a
  huge improvement for apps that utilize application-internal identifiers for
  indexed docs.
* Unified behavior around use of application-specific identifiers, eliminating
  the need to use Scout's internal document IDs (unless you prefer to, of
  course).
* Fixed bugs causing content-addressable Blobdata rows to become orphaned.
* Added a `client.search()` method to present a more obvious interface for
  full-text search.

Scout will refuse to run if it detects FTS4, **unless** you specify the
`--migrate` command-line option. This option instructs Scout to perform the
migration in-place (if needed) during server startup.

To migrate your index in a separate database, use the `migrate_fts5.py` script.
This creates a **new** database rather than modifying in-place.

```bash
$ python migrate_fts5.py /path/to/scout.db /path/to/new.db
```

[View commits](https://github.com/coleifer/scout/compare/3.1.0...master)

## 3.1.0

* Add `scout.gevent_server` implementation of Scout using gevent for the WSGI
  server.
* Add new `Attachment`-only endpoint for querying all attachments
  (`/attachments/`).
* Improve client multipart upload implementation and use `requests` for
  handling those if available.
* Ensure orphaned BlobData (content-addressable attachment storage) is cleaned
  up properly.
* Include `next_url` and `previous_url` for all paginated response types.
* Set base URL to default to http://localhost:8000 for Scout client.
* Improved documentation and test coverage, fixed several longstanding bugs.
* Support for latest version of Peewee.
* Removed Python 2.x compat.

[View commits](https://github.com/coleifer/scout/compare/3.0.4...3.1.0)

### 3.0.4

New build system.

**Backwards-incompatible** - the scout client has been moved into the `scout`
package, and can now be imported using:

```
from scout.client import Scout
```

[View commits](https://github.com/coleifer/scout/compare/3.0.3...3.0.4)

### 3.0.2

* Fix a failing test, which was changed due to an update to how Peewee
  assigns cursor row attributes to python rows.
* Add support for travis-ci.

[View commits](https://github.com/coleifer/scout/compare/3.0.1...3.0.2)

### 3.0.1

Add `prefix` option to FTS4 config to make prefix searches of lengths 2 and 3
more efficient (at the cost of a bit extra disk space).

[View commits](https://github.com/coleifer/scout/compare/3.0.0...3.0.1)

### 3.0.0

Released Scout 3.0.0, which uses a new version numbering system which aims to
make keeping compatible versions of Scout and Peewee simpler.

Peewee underwent a rewrite and the 3.0.0 release was not compatible with Scout
0.4.0. Scout will use the same major version as Peewee to indicate which
version of the library it is compatible with.

Additionally, Scout has vastly improved Python 3 compatibility.

[View commits](https://github.com/coleifer/scout/compare/0.4.0...3.0.0)
