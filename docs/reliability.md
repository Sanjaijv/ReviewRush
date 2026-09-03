# Reliability runbook

Operational guidance for running ReviewRush in production: what to back up,
how to roll back a bad migration, and where to look first when a review
fails. This complements the Phase 13 section of the top-level README, which
covers what was built; this document covers what to *do* with it.

## Database backups

The Postgres database (`DATABASE_URL`) is the only durable state in this
system — Redis holds nothing that survives being lost except in-flight
Celery task messages, which are safe to lose (a duplicate/lost webhook
delivery still gets reconciled the next time GitHub sends state, per the
idempotency guarantees described in the README).

- **What to back up**: the whole `reviewrush` database. Every table is
  either immutable evidence (`diff_snapshots`, `tool_runs`, `ai_reviews`,
  `policy_decisions`, `merge_attempts`, `review_comments`, `audit_events`,
  `task_failures`) or small reference/config data (`installations`,
  `repositories`, `repository_config_versions`). None of it is derivable
  from GitHub after the fact — GitHub's own history doesn't retain a
  point-in-time record of *why* ReviewRush approved or blocked a given
  commit.
- **How**: standard `pg_dump`/`pg_basebackup` + WAL archiving (or your
  managed Postgres provider's equivalent — RDS/Cloud SQL/Neon snapshots).
  A daily full dump plus continuous WAL archiving gives point-in-time
  recovery; a nightly `pg_dump` alone is an acceptable minimum for a
  low-traffic installation.
- **Retention**: match `DASHBOARD_DEFAULT_RETENTION_DAYS` (Phase 12) at
  minimum — there's no value in a backup retention window shorter than the
  data retention policy the product itself advertises to repository admins.
- **What must never be in a backup, unencrypted or otherwise**:
  `github_private_key`, `github_webhook_secret`,
  `github_oauth_client_secret`, `dashboard_session_secret` — none of these
  live in the database (they're environment/secret-manager config, see
  `.env.example`), so a database backup never contains them. Verify your
  secret manager has its own backup/rotation story independent of this.

## Migration rollback

Every Alembic migration in `alembic/versions/` has a working `downgrade()`
(verified as of `0013_reliability`) — this is an existing discipline in this
codebase, not something Phase 13 introduced. To roll back one release:

```bash
alembic downgrade -1        # one migration back
alembic downgrade 0012      # to a specific known-good revision
```

Before rolling back in production:

1. Confirm the application code you're rolling back *to* actually matches
   the schema you're downgrading to — a downgrade that drops a column a
   still-running new-version process reads will crash that process, not
   fix anything.
2. Take a fresh backup immediately before downgrading. A `downgrade()` that
   drops a column drops its data; there is no "undo" for that beyond
   restoring the backup.
3. Drain Celery workers first (`celery -A app.celery_app.celery_app control
   shutdown`, or scale worker replicas to 0) so nothing is mid-write against
   the schema you're about to change.

## Incident response — where a review failed

1. **`GET /health/ready`** (`app/api/v1/health.py`) — confirms whether the
   database and Redis/broker are reachable at all. Start here for "nothing
   is happening."
2. **`GET /metrics`** — `reviewrush_celery_queue_depth` climbing without
   bound means workers aren't keeping up (or are down);
   `reviewrush_task_dead_letters_total` and `reviewrush_model_call_failures_total`
   climbing point at which stage is failing.
3. **Dashboard → repository → "Unresolved task failures"**
   (`GET /api/v1/dashboard/repositories/{id}/task-failures`) — the
   dead-letter table (`task_failures`, Phase 13) records the exact
   exception, traceback, and retry count for a task that gave up. This is
   the fastest way to find *why* one specific review stalled.
4. **Dashboard → repository → run detail**
   (`GET /api/v1/dashboard/repositories/{id}/runs/{diff_snapshot_id}`) —
   the full evidence trail (tool runs, AI review, policy decision, merge
   attempts) for one commit's review. Every non-`"completed"` status field
   here (`ai_reviews.status`, `tool_runs.conclusion`) explains itself:
   `"quota_exceeded"` means a Phase 13 quota kicked in,
   `"error"`/`"invalid_output"` means the model call or its output was bad,
   an errored/timed-out tool run means the deterministic pipeline failed.
5. **Structured logs**: every log line carries a `correlation_id`
   (`app/logging.py`) set from the inbound webhook request's
   `X-Correlation-ID` (or a generated UUID) and echoed back in the response
   header — grep your log aggregator for it to follow one webhook delivery
   across the API process. Distributed tracing (`TRACING_ENABLED=true`)
   extends this same idea across the full Celery task chain, when a
   collector is available.
6. **Manual recovery**: the dashboard's "rerun" action re-queues a review
   from the deterministic-analysis stage after deleting its stored
   `ToolRun`/`AIReview`/`PolicyDecision` rows (the one deliberate, audited
   exception to this codebase's immutability rule); "cancel" stops a
   still-in-flight run. Both require an authenticated, authorized dashboard
   user and are recorded in the audit log.

## Safety invariants worth remembering during an incident

- A GitHub outage, a model outage, or an exhausted quota all degrade to
  `HUMAN_REVIEW` (`app/policy/engine.py`: any non-`"completed"` AI status
  fails closed), never to an implicit approval. There is no code path
  where "the AI reviewer is down" resolves to "auto-merge anyway."
- `merge_pull_request` always passes the reviewed `head_sha` as GitHub's own
  optimistic-concurrency guard — a merge can never land a different commit
  than the one that was actually reviewed, even under retry or a lock
  timeout.
