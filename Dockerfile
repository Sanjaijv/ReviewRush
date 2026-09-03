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
# docker CLI is only needed when ANALYSIS_SANDBOX_ENABLED=true (Phase 5): the
# worker shells out to it to launch isolated containers for untrusted PR code.
RUN apt-get update \
    && apt-get install --no-install-recommends -y docker.io \
    && rm -rf /var/lib/apt/lists/*
CMD ["celery", "-A", "app.celery_app.celery_app", "worker", "--loglevel=INFO"]
