## Changelog

This document describes changes to Scout from one release to another.

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
