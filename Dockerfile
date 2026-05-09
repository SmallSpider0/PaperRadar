# syntax=docker/dockerfile:1

FROM node:20-bookworm-slim AS frontend-builder

ARG APT_MIRROR=https://mirrors.aliyun.com
ARG NPM_REGISTRY=https://registry.npmmirror.com

RUN set -eux; \
    sed -i \
      -e "s#http://deb.debian.org#${APT_MIRROR}#g" \
      -e "s#http://security.debian.org#${APT_MIRROR}#g" \
      -e "s#https://deb.debian.org#${APT_MIRROR}#g" \
      -e "s#https://security.debian.org#${APT_MIRROR}#g" \
      /etc/apt/sources.list.d/debian.sources || true; \
    npm config set registry "${NPM_REGISTRY}"

WORKDIR /build/app/frontend
COPY app/frontend/package*.json ./
RUN npm ci
COPY app/frontend ./
COPY scripts /build/scripts
ENV NODE_ENV=production
# Use Next directly to avoid requiring Python in the Node build image for npm prebuild hooks.
RUN npx next build

FROM python:3.11-slim-bookworm AS runtime

ARG APT_MIRROR=https://mirrors.aliyun.com
ARG PIP_INDEX_URL=https://mirrors.aliyun.com/pypi/simple/
ARG PIP_TRUSTED_HOST=mirrors.aliyun.com

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    PIP_INDEX_URL=${PIP_INDEX_URL} \
    PIP_TRUSTED_HOST=${PIP_TRUSTED_HOST} \
    PAPERRADAR_HOME=/opt/paperradar \
    PAPERRADAR_DATA_DIR=/var/lib/paperradar \
    PGDATA=/var/lib/postgresql/data \
    PAPERRADAR_APP_HOST=0.0.0.0 \
    PAPERRADAR_APP_PORT=8080 \
    PAPERRADAR_STATIC_DIR=/opt/paperradar/app/frontend/out \
    PAPERRADAR_DB_HOST=127.0.0.1 \
    PAPERRADAR_DB_PORT=5432 \
    PAPERRADAR_DB_NAME=paperradar \
    PAPERRADAR_DB_USER=paperradar \
    PAPERRADAR_REDIS_URL=redis://127.0.0.1:6379/0

RUN set -eux; \
    sed -i \
      -e "s#http://deb.debian.org#${APT_MIRROR}#g" \
      -e "s#http://security.debian.org#${APT_MIRROR}#g" \
      -e "s#https://deb.debian.org#${APT_MIRROR}#g" \
      -e "s#https://security.debian.org#${APT_MIRROR}#g" \
      /etc/apt/sources.list.d/debian.sources || true; \
    apt-get update; \
    apt-get install -y --no-install-recommends \
        bash \
        ca-certificates \
        curl \
        postgresql \
        postgresql-client \
        redis-server \
        tini; \
    rm -rf /var/lib/apt/lists/*; \
    mkdir -p /opt/paperradar /var/lib/paperradar

WORKDIR /opt/paperradar
COPY app ./app
COPY scripts ./scripts
COPY docs ./docs
COPY PROJECT.md README.md ./
COPY --from=frontend-builder /build/app/frontend/out ./app/frontend/out
COPY docker/entrypoint.sh /usr/local/bin/paperradar-entrypoint.sh

RUN pip install --no-cache-dir -r app/backend/requirements.txt \
    && chmod +x /usr/local/bin/paperradar-entrypoint.sh \
    && chown -R postgres:postgres /var/lib/postgresql

EXPOSE 8080
VOLUME ["/var/lib/postgresql/data", "/var/lib/paperradar"]
ENTRYPOINT ["/usr/bin/tini", "--", "/usr/local/bin/paperradar-entrypoint.sh"]
