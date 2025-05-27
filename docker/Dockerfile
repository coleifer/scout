FROM ghcr.io/astral-sh/uv:0.7 AS uv-base

FROM alpine:3.21
ENV SCOUT_DATABASE=/data/search-index.db
COPY ./server /srv/

# Install Python deps and ensure peewee C extensions are compiled.
RUN \
    --mount=type=bind,from=uv-base,source=/uv,target=/usr/local/bin/uv \
    apk add --no-cache \
        libev python3 sqlite \
    && \
    apk add --no-cache \
        --virtual .build-deps \
        build-base libev-dev python3-dev sqlite-dev \
    && \
    UV_BREAK_SYSTEM_PACKAGES=1 \
    UV_COMPILE_BYTECODE=1 UV_LINK_MODE='copy' \
    UV_NO_CACHE=1 UV_NO_CONFIG=1 UV_NO_MANAGED_PYTHON=1 \
    UV_NO_PROGRESS=1 UV_SYSTEM_PYTHON=1 \
    uv pip install --strict \
        cython gevent scout \
    && \
    apk del --no-cache --purge .build-deps
    
EXPOSE 9004
VOLUME /data/

WORKDIR /data
ENTRYPOINT ["/usr/bin/env", "python3", "/srv/server.py", "-H", "0.0.0.0", "-p", "9004", "-s", "porter", "-l", "/data/scout.log"]
