# Load and fault-injection testing

This document describes the approach for exercising ReviewRush under load
and under failure, and where automated coverage for each already exists.
Load testing itself is not run in CI — this environment has no standing
Postgres/Redis/GitHub-App infrastructure to point a real load generator at —
but the script below is ready to run against a staging deployment.

## Fault injection (automated, runs in CI)

Every Phase 13 reliability mechanism has a corresponding test that induces
the actual failure mode rather than mocking around it:

- `tests/test_reliability_retries.py` — a fake transient exception (a
  connection-refused-shaped `httpx.TransportError`, a `redis.ConnectionError`)
  raised from inside a task body is retried with backoff; a non-transient
  exception (`ValueError`) is not retried and is dead-lettered immediately.
- `tests/test_dead_letter.py` — a task whose retries are exhausted writes a
  `TaskFailure` row with the right `retry_count`/exception details; resolving
  it through the dashboard endpoint sets `resolved_at`/`resolved_by` and
  never deletes the row.
- `tests/test_reliability_locking.py` — a second lock acquisition attempt on
  an already-held key blocks and then raises `LockNotAcquired` within the
  configured wait window; releasing the first lock unblocks a waiter.
- `tests/test_reliability_quota.py` — exceeding the per-repository or
  per-installation daily quota skips the model call, persists
  `status="quota_exceeded"`, and confirms the policy engine still resolves
  that to `HUMAN_REVIEW` (never an implicit approval).
- `tests/test_metrics.py` — `GET /metrics` returns Prometheus text format
  and reflects an observed webhook request.
- `tests/test_github_client_*.py` (existing, extended) — a 429/502/503
  response from the GitHub API is retried by `GitHubClient` and eventually
  succeeds; a 404/422 is raised immediately without retry, and a create-type
  POST is never retried at the HTTP layer.

Run them the same way as the rest of the suite:

```bash
pytest tests/test_reliability_retries.py tests/test_dead_letter.py \
       tests/test_reliability_locking.py tests/test_reliability_quota.py \
       tests/test_metrics.py -v
```

## Load testing (manual, against a staging deployment)

The primary target for load testing is the webhook ingestion path
(`POST /api/v1/github/webhook`), since that's the one endpoint under direct
external load (every push, from every configured repository, arrives here).
A [k6](https://k6.io/) script sketch:

```javascript
// load/webhook.js
import http from "k6/http";
import crypto from "k6/crypto";

const SECRET = __ENV.GITHUB_WEBHOOK_SECRET;
const URL = __ENV.TARGET_URL + "/api/v1/github/webhook";

export const options = {
  scenarios: {
    steady: { executor: "constant-arrival-rate", rate: 20, timeUnit: "1s", duration: "5m", preAllocatedVUs: 50 },
    burst:  { executor: "ramping-arrival-rate", startRate: 20, stages: [{ target: 200, duration: "30s" }, { target: 20, duration: "30s" }], preAllocatedVUs: 300, startTime: "5m" },
  },
};

export default function () {
  const body = JSON.stringify({
    ref: "refs/heads/foundations",
    after: crypto.randomBytes(20).toString("hex"),
    repository: { id: 1, full_name: "acme/demo" },
    installation: { id: 1 },
    sender: { type: "User" },
    commits: [],
  });
  const signature = "sha256=" + crypto.hmac("sha256", SECRET, body, "hex");
  http.post(URL, body, {
    headers: {
      "Content-Type": "application/json",
      "X-GitHub-Event": "push",
      "X-GitHub-Delivery": crypto.randomUUID(),
      "X-Hub-Signature-256": signature,
    },
  });
}
```

Run with: `k6 run -e GITHUB_WEBHOOK_SECRET=... -e TARGET_URL=https://staging.example.com load/webhook.js`

**What to watch during the run** (via `GET /metrics`):

- `reviewrush_webhook_request_latency_seconds` — the endpoint itself does
  only signature verification + a DB insert + enqueue, so p99 should stay
  well under 200ms regardless of downstream pipeline load; a regression here
  points at the database, not the review pipeline.
- `reviewrush_celery_queue_depth` — under the `burst` scenario this should
  climb during the burst and drain back down afterward. A queue depth that
  never drains means worker throughput can't keep up with sustained load at
  that rate — the signal to add worker replicas (each Celery task in this
  codebase is independently horizontally scalable; nothing pins work to a
  specific worker process).
- `reviewrush_task_dead_letters_total` — should stay at zero. Any increase
  under load (rather than under an injected fault) is a bug, not a capacity
  limit.
- Database connection pool exhaustion (`sqlalchemy.exc.TimeoutError` in
  worker logs, or `reviewrush_task_retries_total` climbing for
  `OperationalError`-classified failures) — the signal to raise
  `engine`'s pool size in `app/db.py` or add a connection pooler (pgbouncer)
  in front of Postgres.

The secondary target is the analysis/AI pipeline's *throughput*, not its
per-request latency (a single review reasonably takes tens of seconds to
minutes end-to-end, dominated by the Docker sandbox and/or model call) — the
Celery worker concurrency (`celery worker --concurrency=N`) and replica
count are the levers there, sized against `reviewrush_review_stage_duration_seconds`
and the target reviews-per-minute the deployment needs to sustain.
