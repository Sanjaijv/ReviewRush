FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /srv

COPY pyproject.toml ./
COPY app ./app
COPY alembic ./alembic
COPY alembic.ini ./

RUN pip install --no-cache-dir ".[dev]"

FROM base AS api
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]

FROM base AS worker
# The docker CLI (client only, not the dockerd daemon) is needed when
# ANALYSIS_SANDBOX_ENABLED=true (Phase 5): the worker shells out to it to
# launch isolated containers for untrusted PR code, talking to the *host's*
# Docker daemon via the mounted socket (docker-compose.yml) - it never runs
# its own daemon. `docker-cli` is the correct package for this: on current
# Debian, `docker.io` only provides the dockerd/docker-proxy binaries, not
# the `docker` client itself (a packaging split from older Debian/Ubuntu
# releases) - installing `docker.io` here silently leaves `docker` missing
# from $PATH despite apt reporting success.
# Force the Debian mirror to HTTPS before installing: some networks
# (corporate proxies/VPNs) intercept and reject plain HTTP (port 80),
# returning 403 on `apt-get update`, while HTTPS passes through untouched.
RUN (sed -i 's/^URIs: http:/URIs: https:/' /etc/apt/sources.list.d/*.sources 2>/dev/null || true) \
    && (sed -i 's|http://deb.debian.org|https://deb.debian.org|g' /etc/apt/sources.list 2>/dev/null || true) \
    && apt-get update \
    && apt-get install --no-install-recommends -y docker-cli \
    && rm -rf /var/lib/apt/lists/*
CMD ["celery", "-A", "app.celery_app.celery_app", "worker", "--loglevel=INFO"]
