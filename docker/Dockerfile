FROM python:3.12-alpine
ENV SCOUT_DATABASE=/data/search-index.db

# Install Python deps and ensure peewee C extensions are compiled.
RUN apk add --no-cache --virtual .build-deps build-base sqlite-dev libffi-dev \
      && apk add --no-cache libev sqlite-libs \
      && pip install --no-cache-dir gevent scout \
      && apk del .build-deps
EXPOSE 9004
VOLUME /data/

HEALTHCHECK --interval=30s --timeout=5s \
  CMD wget -qO- http://localhost:9004/ || exit 1

WORKDIR /data
ENTRYPOINT ["scout_wsgi", "-H", "0.0.0.0", "-p", "9004", "-l", "/data/scout.log"]
