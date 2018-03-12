FROM python:3.6
ENV SCOUT_DATABASE=/data/search-index.db
ENV CFLAGS="-DSQLITE_ALLOW_COVERING_INDEX_SCAN=1 -DSQLITE_DEFAULT_CACHE_SIZE=-8000 -DSQLITE_DEFAULT_MEMSTATUS=0 -DSQLITE_DEFAULT_PAGE_SIZE=4096 -DSQLITE_DEFAULT_SYNCHRONOUS=0 -DSQLITE_DEFAULT_WAL_SYNCHRONOUS=0 -DSQLITE_DISABLE_DIRSYNC -DSQLITE_ENABLE_FTS3 -DSQLITE_ENABLE_FTS3_PARENTHESIS -DSQLITE_ENABLE_FTS4 -DSQLITE_ENABLE_FTS5 -DSQLITE_ENABLE_JSON1 -DSQLITE_ENABLE_MEMDB -DSQLITE_ENABLE_STAT4 -DSQLITE_ENABLE_STMTVTAB -DSQLITE_ENABLE_UNLOCK_NOTIFY -DSQLITE_ENABLE_UPDATE_DELETE_LIMIT -DSQLITE_LIKE_DOESNT_MATCH_BLOBS -DSQLITE_SOUNDEX -DSQLITE_STMTJRNL_SPILL=-1 -DSQLITE_TEMP_STORE=3 -DSQLITE_USE_ALLOCA -DSQLITE_USE_URI -DSQLITE_DEFAULT_JOURNAL_SIZE_LIMIT=1536 -DSQLITE_DEFAULT_WAL_AUTOCHECKPOINT=128 -DHAVE_MALLOC_USABLE_SIZE -DHAVE_ISNAN -DHAVE_USLEEP -O2 -fPIC"
COPY ./server /srv/

# Install up-to-date SQLite compiled with all the frills.
RUN apt-get update && apt-get -y install tcl-dev wget && \
      wget https://www.sqlite.org/src/tarball/sqlite.tar.gz?r=release -O sqlite.tar.gz -q && \
      tar xzf sqlite.tar.gz && \
      cd sqlite && \
      LIBS="-lm" PREFIX="/usr/local" ./configure --disable-tcl --enable-static --enable-shared --enable-tempstore=always --prefix="/usr/local" && \
      make -j4 && \
      make install && \
      ldconfig && \
      cd ../ && \
      rm -rf ./sqlite/ ./sqlite.tar.gz

# Install Python deps and ensure peewee C extensions are compiled.
RUN pip install --no-cache-dir cython && pip install --no-cache-dir gevent scout
EXPOSE 9004
VOLUME /data/

WORKDIR /data
ENTRYPOINT ["python", "/srv/server.py", "-H", "0.0.0.0", "-p", "9004", "-s", "porter", "-l", "/data/scout.log"]
