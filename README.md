![](http://media.charlesleifer.com/blog/photos/scout.png)

scout is a RESTful search server written in Python. The search is powered by [SQLite's full-text search extension](http://sqlite.org/fts3.html), and the web application utilizes the [Flask](http://flask.pocoo.org) framework.

Features:

* Multiple search indexes present in a single database.
* RESTful design for easy indexing and searching.
* Lightweight, low resource utilization, minimal setup required.
* Store search content and arbitrary metadata.
* Multiple result ranking algorithms, porter stemmer.
* Comprehensive unit-tests.
