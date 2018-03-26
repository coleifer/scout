FROM coleifer/sqlite
ENV SCOUT_DATABASE=/data/search-index.db
COPY ./server /srv/

# Install Python deps and ensure peewee C extensions are compiled.
RUN pip install --no-cache-dir cython && pip install --no-cache-dir gevent scout
EXPOSE 9004
VOLUME /data/

WORKDIR /data
ENTRYPOINT ["python", "/srv/server.py", "-H", "0.0.0.0", "-p", "9004", "-s", "porter", "-l", "/data/scout.log"]
