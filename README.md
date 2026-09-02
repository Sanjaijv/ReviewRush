# ReviewRush

AI-assisted GitHub code-review and merge system. This repository currently implements
**Phase 1 — Project foundation** and **Phase 2 — GitHub App and secure webhook
ingestion**: the backend scaffold, local development environment, and a signed,
idempotent GitHub webhook endpoint that queues events for asynchronous processing.
See [AI_Code_Review_Agent_All_Phases.md](AI_Code_Review_Agent_All_Phases.md) for the
full roadmap.

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
- GitHub webhook: http://localhost:8010/api/v1/github/webhook (`POST`, signed)

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
  api/v1/          Versioned API routes (health, GitHub webhook)
  github/          Webhook signature verification, App/installation auth
  models/          SQLAlchemy models (Installation, Repository, WebhookDelivery)
  tasks/           Celery tasks (sample ping, GitHub webhook processing)
alembic/           Migrations
tests/             pytest suite
```

## GitHub App setup (Phase 2)

The webhook endpoint expects a real GitHub App to be created and installed manually;
this repository only implements the receiving side.

1. Create a GitHub App under the target GitHub account/organization's developer
   settings, with these minimum permissions:

   | Permission | Access |
   |---|---|
   | Metadata | Read |
   | Contents | Read |
   | Pull requests | Read and write |
   | Checks | Read and write |

2. Subscribe the App to the `installation`, `installation_repositories`, `push`,
   `pull_request`, `pull_request_review`, `check_run`, and `check_suite` events.
3. Set the webhook URL to `https://<your-host>/api/v1/github/webhook` and generate a
   webhook secret.
4. Generate a private key for the App (PEM format).
5. Set these in `.env` (never commit real values):
   - `GITHUB_APP_ID` — the App's numeric ID.
   - `GITHUB_PRIVATE_KEY` — the PEM private key contents.
   - `GITHUB_WEBHOOK_SECRET` — the webhook secret from step 3.
6. Install the App on one or more repositories.

### Security notes

- `POST /api/v1/github/webhook` verifies `X-Hub-Signature-256` against the raw
  request body before parsing it; requests with a missing, malformed, or invalid
  signature (or an unconfigured secret) are rejected with `401` and nothing is
  persisted or queued — this fails closed.
- `X-GitHub-Delivery` is used as an idempotency key: a DB-level unique constraint on
  `webhook_deliveries.delivery_id` guarantees a replayed delivery is never processed
  twice, even under concurrent requests.
- The endpoint only verifies the signature and persists an idempotency record before
  returning `202`; the payload is then handled asynchronously by a Celery task so the
  webhook responds promptly.
- Only event type, delivery ID, and installation ID are logged — full webhook
  payloads and any credentials are never written to logs.
- Installation access tokens (`app/github/auth.py`) are short-lived and generated
  on demand; no GitHub App private key or token is ever sent to a browser, logged,
  or given network access to pull-request code (no PR code execution exists yet —
  that's Phase 5).

## Notes

- Business-domain logic (PR automation, diff analysis, AI review, policy
  decisions, and merging) is not implemented in this phase — see the roadmap for
  Phase 3 onward.
- `.env` is git-ignored; only `.env.example` (variable names, no secrets) is committed.
