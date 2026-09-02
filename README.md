# ReviewRush

AI-assisted GitHub code-review and merge system. This repository currently implements
**Phase 1 — Project foundation** only: the backend scaffold and local development
environment. See [AI_Code_Review_Agent_All_Phases.md](AI_Code_Review_Agent_All_Phases.md)
for the full roadmap.

## Stack

FastAPI, PostgreSQL + SQLAlchemy/Alembic, Redis + Celery, Docker Compose.

## Run locally with Docker Compose

```bash
cp .env.example .env
docker compose up --build
```

- API: http://localhost:8010
- Liveness: http://localhost:8010/api/v1/health/live
- Readiness (checks DB + Redis): http://localhost:8010/api/v1/health/ready

Apply database migrations (from the host, with the stack running):

```bash
docker compose exec api alembic upgrade head
```

## Run without Docker

Requires Python 3.12+, a local PostgreSQL instance, and a local Redis instance.

```bash
python -m venv .venv && source .venv/bin/activate
pip install ".[dev]"
cp .env.example .env   # edit DATABASE_URL / REDIS_URL if not using defaults

alembic upgrade head
uvicorn app.main:app --reload

# in a second terminal
celery -A app.celery_app.celery_app worker --loglevel=INFO
```

## Tests, lint, type checks

```bash
ruff check .
mypy app
pytest
```

## Project layout

```
app/
  main.py          FastAPI app + middleware
  config.py        Environment-validated settings
  logging.py       Structured JSON logging with correlation IDs
  db.py            SQLAlchemy engine/session, readiness check
  celery_app.py    Celery app, readiness check
  api/v1/          Versioned API routes (health endpoints)
  models/          SQLAlchemy declarative base (domain models land in later phases)
  tasks/           Celery tasks
alembic/           Migrations (baseline revision only in this phase)
tests/             pytest suite
```

## Notes

- No GitHub App, webhook, or business-domain logic is implemented in this phase —
  see the roadmap for Phase 2 onward.
- `.env` is git-ignored; only `.env.example` (variable names, no secrets) is committed.
