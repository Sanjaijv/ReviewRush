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
  github/          Webhook signature verification, App/installation auth, REST client
  diffs/           Diff retrieval, normalization, and size limits (Phase 4)
  analysis/        Sandboxed deterministic checks: runner, workspace, stages,
                   result normalization, pipeline orchestration (Phase 5)
  ai/              AI reviewer: ReviewModel interface, prompt construction,
                   structured-output validation, orchestration (Phase 6)
  context/         Repository-aware context: profiling, symbol extraction,
                   guidance docs, lexical retrieval, orchestration (Phase 10);
                   symbol chunks, embeddings, semantic re-ranking (Phase 11)
  models/          SQLAlchemy models
  tasks/           Celery tasks (webhook processing, analysis pipeline, AI review)
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
  on demand; no GitHub App private key, model key, or database credential is ever
  passed into the sandboxed containers that execute pull-request code (Phase 5).
- `.env` is git-ignored; only `.env.example` (variable names, no secrets) is committed.

## Deterministic analysis pipeline (Phase 5)

Every push builds an immutable diff snapshot (Phase 4) and then, if enabled, runs
each configured/built-in check — tests, lint, formatting, type checks (from
`.reviewrush.yml: checks`), plus built-in Semgrep (SAST) and Gitleaks (secret
scanning), plus an ecosystem-detected dependency-vulnerability scan — each in its
own throwaway container. Results are normalized into one schema per check
(`check/status/conclusion/required/exit_code/duration_ms/summary/annotations`)
and stored as `ToolRun` rows, one per `(diff_snapshot, check_name)` — immutable
once written, same as diff snapshots. This phase does not itself block or approve
merges; it produces the evidence the policy engine (Phase 7) will consume.

**PR code is untrusted and is never executed with real credentials.** Each check
runs in an ephemeral Docker container with: `--network=none` by default, no
mounted secrets/credentials, a read-only view of the checked-out tree, a
size-bounded writable tmpfs scratch space, `--cap-drop=ALL`,
`--security-opt=no-new-privileges`, an unprivileged UID, and hard
memory/CPU/PID/time limits. A timeout is recorded as `conclusion=timed_out`,
distinct from `failed`; a sandbox that couldn't start at all is recorded as
`conclusion=errored` — neither is ever conflated with a real tool failure or a
silent pass.

### Enabling it

Disabled by default (`ANALYSIS_SANDBOX_ENABLED=false`) because running it requires
the Celery worker to be able to launch containers, and the only wiring provided
here is mounting the host's `/var/run/docker.sock` into the worker container
(`docker-compose.yml`) — which is equivalent to granting the worker host root.
That's an accepted, explicit tradeoff for local development and small trusted
deployments; do not enable it in a multi-tenant or otherwise sensitive deployment
without replacing it with a genuinely isolated runner (a dedicated Docker/DinD
host reachable over `DOCKER_HOST` with TLS, gVisor/Kata, or a managed sandboxing
service) — `app/analysis/runner.py`'s `SandboxRunner` interface is written so that
swap is a new implementation, not a rewrite of the pipeline.

To try it locally:

```bash
# .env
ANALYSIS_SANDBOX_ENABLED=true
```

The images for the built-in checks (`semgrep/semgrep`, `zricethezav/gitleaks`) and
any repo-configured `checks[].image` are pulled on demand by the Docker daemon the
worker talks to. Semgrep's default `--config=auto` needs network access to fetch
rules from its registry, so it's network-disabled (and will report "no parseable
JSON output") until you either set `ANALYSIS_SEMGREP_NETWORK_ENABLED=true` or bake
your own rules into a custom image and point `ANALYSIS_SEMGREP_IMAGE` at it.
Dependency scanning similarly stays `skipped` unless
`ANALYSIS_DEPENDENCY_SCAN_NETWORK_ENABLED=true`, since checking advisory databases
needs network access.

## AI reviewer (Phase 6)

After the deterministic pipeline (Phase 5) finishes for a diff snapshot, the AI
review task runs — if `AI_REVIEW_ENABLED=true` — one coding-LLM reviewer over the
diff, PR intent, and deterministic tool results, and stores its findings.

- `app/ai/model.py` defines a provider-neutral `ReviewModel` interface
  (`generate(system, messages) -> ModelResponse`). The only implementation wired up
  is `OllamaReviewModel`, which calls a **free, locally-hosted, already-trained**
  open-weight coding model through [Ollama](https://ollama.com) — no paid API key,
  no training. Swapping providers later means adding a new implementation of the
  same interface, not rewriting the pipeline.
- `app/ai/prompt.py` builds the prompt from the diff's changed files (skipping
  anything Phase 4 already flagged `excluded_from_ai`, e.g. binaries/vendor/oversized
  patches), commit messages, and `ToolRun` results, bounded by `AI_MAX_PROMPT_BYTES`.
  The system prompt explicitly states that all of that — diff content, filenames,
  commit messages, code comments — is **untrusted data, not instructions**, to
  resist prompt injection embedded in reviewed code.
- `app/ai/schema.py` is the required output contract (`summary`, `risk`,
  `confidence`, `decision`, `issues[]`) as a Pydantic model with `extra="forbid"`.
  There is no "merge" decision value — the model can only advise; the actual merge
  decision belongs to the policy engine (Phase 7).
- `app/ai/validation.py` rejects, beyond schema validation, any issue that
  references a file not shown to the model or a line that isn't actually an added
  line in that file's patch (reusing `app/diffs/patch.map_added_lines`).
- `app/ai/service.py` retries a malformed/invalid response **once** with a repair
  turn (the prior reply plus the specific validation errors); if it's still invalid,
  or the model call itself failed, the `AIReview` row is stored with
  `status="invalid_output"`/`"error"`, `decision=None`, and no `AIFinding` rows —
  **fail closed**. Any later consumer must treat `status != "completed"` as requiring
  human review, never as an implicit approval.
- Results are immutable per diff snapshot (`AIReview.diff_snapshot_id` is unique),
  same as `ToolRun`/`DiffSnapshot` — a rebuild for an already-reviewed head_sha
  reuses the existing row instead of calling the model again.

### Enabling it

```bash
ollama pull qwen2.5-coder:7b   # or any coding-capable model you prefer
ollama serve

# .env
AI_REVIEW_ENABLED=true
AI_MODEL=qwen2.5-coder:7b
# Running via `docker compose up` (the worker runs in a container, so
# `localhost` there means the container, not your host):
AI_OLLAMA_BASE_URL=http://host.docker.internal:11434
# Running the worker directly on the host instead (`celery -A app.celery_app.celery_app worker`):
# AI_OLLAMA_BASE_URL=http://localhost:11434
```

A hosted provider (Groq) is also supported for when local CPU-only inference
is too slow - unlike Ollama, this sends diff/prompt content to a third-party
service:

```bash
# .env
AI_REVIEW_ENABLED=true
AI_PROVIDER=groq
AI_GROQ_API_KEY=gsk_...   # free key from console.groq.com/keys
AI_MODEL=openai/gpt-oss-20b
```

## AI auto-fix

For a low-severity, mechanical finding, the AI reviewer can go one step
further than advising: it generates a fix, applies it to a fresh checkout,
re-runs this repository's own deterministic checks against the result, and
- only if every required check still passes - opens a **separate** pull
request proposing the fix, targeting the original PR's own branch (merging
the fix-PR updates the original PR; nothing is ever pushed directly to it,
and nothing merges automatically).

- `category="security"` findings are never eligible, and severity is capped
  at `"low"` by default (`"medium"` at most) - both are enforced in code
  (`app/autofix/service.py`), not just by configuration, so a config mistake
  can never widen what auto-fix is allowed to touch.
- Each fix is scoped to exactly one finding's own `start_line`..`end_line` in
  one file (`app/autofix/schema.py`'s `FixSuggestion`) - there is no general
  patch/diff-apply engine, so a fix that needs a wider change is a case the
  model is instructed to decline (`applicable: false`) rather than force.
- Every attempt - successful or not - is recorded immutably in
  `AutoFixAttempt` (`status`: `pr_opened`, `verification_failed`,
  `not_applicable`, `invalid_output`, or `error`) and in the audit log
  (`app/dashboard/audit.py`), and is idempotent per finding: a rerun never
  re-attempts (or re-pushes) a finding that already has an attempt row.
- A finding left unmerged on its fix-PR is reported again as a "new"
  AIFinding on every later push that still contains it (each review run
  assigns fresh row ids, and the model rewords titles slightly between
  runs), which used to pile up one redundant fix-PR per push forever. When
  a new automatic fix-PR opens, `_close_superseded_fix_prs` closes every
  earlier still-open fix-PR for the exact same `(category, file,
  start_line, end_line)` - the same underlying one-line-range issue -
  with a comment pointing at the new one, so there's only ever one open
  fix-PR per unresolved finding.

### On-demand fixes for findings automatic auto-fix skips

`category="security"` findings, and anything above the repo's configured
severity ceiling, never get an automatic attempt - but their inline comment
still renders an **"Apply this fix" checkbox**
(`app/checks/rendering.py::render_inline_comment_body`). Checking it in the
GitHub UI edits the comment, which GitHub delivers as a
`pull_request_review_comment` "edited" webhook event
(`app/tasks/github_webhook.py::_handle_pr_review_comment`) - the checkbox
transition is what triggers the fix, nothing else about the edit does.

This path differs from the automatic one in one deliberate way: instead of
opening a separate fix-PR, it **commits the fix directly to the branch
being reviewed** (`app/autofix/service.py::apply_manual_fix`), using the
same generate-then-verify pipeline and the same required-checks gate. The
resulting push is an ordinary push GitHub already knows how to handle - it
re-triggers a normal review and updates the PR in place, exactly like a
human pushing the same commit would.

- Same eligibility floor as automatic auto-fix (`missing_tests` excluded
  structurally either way) - see `manual_fix_eligible`. The checkbox is
  never offered for a finding automatic auto-fix would already attempt on
  its own.
- One-shot, same as the automatic path: an existing `AutoFixAttempt` for
  the finding is never re-attempted, so re-checking an already-actioned box
  does nothing.
- Before committing, the target file's live content on the branch is
  compared against what it was when the finding was reported
  (`status="stale_target"` if it's drifted) - refuses to silently overwrite
  a concurrent edit rather than blindly applying a now-stale line range.
- Uses `GitHubClient.update_branch_ref`, which never force-pushes: a
  genuine non-fast-forward conflict is surfaced as `status="error"`, not
  resolved by discarding whatever moved the branch.
- Recorded in the same `AutoFixAttempt` table (`trigger="manual"`,
  `status="committed"` on success, `actor_login` set to whoever checked the
  box) - `trigger="automatic"` is the original behavior above.
- The resulting commit's own push webhook is intentionally ignored (every
  bot-authored push is, to avoid an automation loop - see
  `app.tasks.github_webhook._handle_push`), so a fresh review/check run for
  it is triggered explicitly instead, right after the commit lands
  (`app.tasks.review_trigger.trigger_review_for_commit`, the same snapshot-
  building/check-run/analysis-queueing logic the push handler itself uses).
  Without this, the branch's required check would keep pointing at the
  pre-fix commit.

### Enabling it

Requires **both** a global switch and per-repository consent - either alone
does nothing:

```bash
# .env
AUTOFIX_ENABLED=true
```

```yaml
# .reviewrush.yml
auto_fix:
  enabled: true
  maximum_severity: low   # or "medium" - never higher
```

The on-demand checkbox needs no extra config beyond the above, but the
GitHub App must be **subscribed to the `pull_request_review_comment` event**
(App settings → Permissions & events → Subscribe to events) and have
**write access to pull request reviews** - without both, GitHub never
delivers the "edited" webhook a checkbox click produces, and the box will
appear to do nothing when checked.

## Repository-aware context (Phase 10)

Before the AI reviewer (Phase 6) builds its prompt, it asks
`app/context/service.py` for repository context — if `CONTEXT_ENABLED=true` —
which checks out the repo tree at the diff's `head_sha` (the same tarball
mechanism `analysis/workspace.py` uses, no Docker required) and returns:

- A lexical/structural **repo profile**: languages, frameworks (sniffed from
  manifest files), test directories, and ownership files (`app/context/profile.py`).
- Repository **guidance docs** (`AGENTS.md`, `CONTRIBUTING.md`, etc.), read
  bounded per file (`app/context/guidance.py`).
- **Retrieved context items** for each symbol the diff actually changed —
  its definition, callers/references found by lexical search, related tests,
  and nearby config — each tagged with its path, line range, and a `reason`
  explaining why it was retrieved (`app/context/retrieval.py`).

Symbols are extracted with the stdlib `ast` module for Python and regex
heuristics for JS/TS/Go/Java/Ruby/Rust (`app/context/symbols.py`) — lexical
and structural retrieval, per the roadmap, before reaching for embeddings.
`RepoFileIndex` persists each file's symbol metadata (never code text) keyed
by content hash, so a rebuild **only re-indexes files the diff actually
touched**; every snippet shown to the model is still read live from that
review's own workspace, so content from an old commit can never leak into a
new review. Retrieval is capped by `CONTEXT_MAX_BYTES` (smallest items kept
first, same pattern as the diff prompt budget).

The context section is appended to the AI prompt clearly marked as untrusted,
retrieved data — the model is instructed to use it only as supporting
evidence, and may cite a context item's id in an issue's `context_refs`;
`app/ai/validation.py` rejects any `context_refs` id that wasn't actually
shown to the model that run. Like the AI review and analysis sandbox, this is
immutable per diff snapshot (`RepoContextSnapshot.diff_snapshot_id` is
unique) and off by default.

### Enabling it

```bash
# .env
CONTEXT_ENABLED=true
```

## RAG and scalable code indexing (Phase 11)

On top of Phase 10, every changed file's symbols are also chunked into
`RepoSymbolChunk` rows (`app/context/chunks.py`) — one per symbol, storing
path/symbol/kind/line-range/`content_sha` and lexically-detected
`relationships` (other symbols called within the chunk), but never chunk
text, mirroring `RepoFileIndex`'s "metadata only" invariant.

Semantic retrieval is a further opt-in (`CONTEXT_EMBEDDINGS_ENABLED=true`):
each chunk's embedding is computed by a local Ollama embeddings model
(`app/context/embeddings.py`, same zero-external-key pattern as the AI
reviewer) and stored in a pgvector column. For each symbol the diff
changed, `app/context/rerank.py` runs a repository-scoped
(`repository_id`-filtered, never crossing tenants) cosine-similarity lookup
for related chunks elsewhere in the repo, converts the nearest ones into
context items read live from the workspace (same no-stale-text guarantee as
lexical retrieval), and merges them with the lexical/structural candidates.

The merged candidate set is then **re-ranked** — by kind (definition/test >
reference > semantic > config), same-directory path relevance, and
symbol-name specificity — before the byte budget (`CONTEXT_MAX_BYTES`) is
applied; `apply_budget` now keeps items in that relevance order rather than
smallest-first.

If chunk indexing or semantic retrieval throws (a bad provider response, a
pgvector error), the failure is caught and logged, and the review continues
with whatever lexical/structural context it already had —
`RepoContextSnapshot.degraded` records that this happened, the documented
degraded mode rather than a failed review.

When a GitHub App installation is deleted, or a repository is removed from
one, `RepoFileIndex` and `RepoSymbolChunk` rows for those repositories are
deleted (`purge_repository_index`, wired into the `installation` /
`installation_repositories` webhook handlers) — the searchable index cannot
outlive the installation's access. `RepoContextSnapshot` rows are left
alone; like `AIReview`/`MergeAttempt` they're an immutable per-review audit
record, not a live index.

### Enabling it

```bash
# .env
CONTEXT_ENABLED=true
CONTEXT_EMBEDDINGS_ENABLED=true
CONTEXT_EMBEDDINGS_MODEL=nomic-embed-text   # ollama pull nomic-embed-text
```

Requires the pgvector-enabled Postgres image in `docker-compose.yml`
(`pgvector/pgvector:pg16`) and the `0011_symbol_chunks` migration applied.

## Dashboard, configuration, and auditability (Phase 12)

A JSON API under `/api/v1/dashboard/*` (`app/api/v1/dashboard.py`,
`app/dashboard/`) gives repository administrators visibility and control,
plus a minimal dependency-free HTML/JS client served at `/dashboard/`
(`app/static/dashboard/index.html`) — no frontend build step.

- **Login** is GitHub OAuth (the App's own user-to-server flow, not a
  personal access token): `GET /api/v1/dashboard/auth/login` redirects to
  GitHub, `GET /api/v1/dashboard/auth/callback` exchanges the code, looks up
  the user's accessible installations via `GET /user/installations`
  (GitHub's own authorization model — never derived from our database), and
  issues a signed, stateless session cookie (`app/dashboard/session.py`)
  that expires after `DASHBOARD_SESSION_TTL_SECONDS` (default 1h). There is
  no server-side session store; re-login re-derives access from GitHub.
- **Authorization**: every repository-scoped route depends on
  `get_authorized_repository` (`app/dashboard/deps.py`), which 404s (not
  403, to avoid leaking which repository ids exist) unless the caller's
  session lists that repository's installation.
- **Run history and drill-down**: `GET .../runs` and
  `GET .../runs/{diff_snapshot_id}` (`app/dashboard/runs.py`) read the
  existing immutable `DiffSnapshot`/`ToolRun`/`AIReview`/`PolicyDecision`/
  `MergeAttempt` rows — nothing new is stored for this.
- **Configuration editor**: `PUT .../config` validates the submitted
  document against the same `RepoConfig` schema as `.reviewrush.yml`
  (`app/repo_config.py`) and, only if it's valid, appends a new
  `RepositoryConfigVersion` row (`app/dashboard/config_service.py`) —
  versions are never mutated, so history and the responsible actor are
  always reconstructable. When a repository has an active dashboard
  override, `app.policy.service` and `app.merge.service` read it instead of
  fetching `.reviewrush.yml` from GitHub; it is still merged with the
  `POLICY_ORG_*` organization floor exactly like the file-based config, so a
  dashboard edit can only tighten policy, never weaken it below the floor.
- **Metrics**: `GET .../metrics` aggregates review time, findings by
  severity, blocked-merge counts, and AI provider/model token usage from
  existing rows. `false_positive_rate` is reported as `null` — there is no
  developer-feedback mechanism yet (that's Phase 15's `Feedback` model), so
  this deliberately doesn't fabricate a number.
- **Audit log**: `AuditEvent` (`app/models/dashboard.py`) is an immutable,
  append-only table. Dashboard actions (config edits, rerun, cancel,
  disconnect) write `actor_type="user"` rows; `app.policy.service` and
  `app.merge.service` also write `actor_type="system"` rows for every policy
  decision and merge attempt, so `GET .../audit-log` covers both human and
  automated events.
- **Manual rerun**: `POST .../runs/{id}/rerun` is the one deliberate,
  audited exception to this codebase's "results are immutable per
  `diff_snapshot_id`" rule everywhere else — it deletes the stored
  `ToolRun`/`AIReview`/`PolicyDecision` rows for that run and re-queues the
  pipeline from the deterministic-analysis stage. It requires an
  authenticated, authorized dashboard user and is recorded in the audit log
  before anything is deleted.
- **Manual cancel**: `POST .../runs/{id}/cancel` sets
  `DiffSnapshot.status = "cancelled"`; each of the five chained Celery tasks
  (`app/tasks/{analysis,ai_review,policy,checks,merge}.py`) checks this and
  no-ops rather than starting new work. This is best-effort: a stage that's
  already executing when cancel is called is not preemptively killed.
- **Disconnect**: `POST .../disconnect` deactivates the repository
  (`is_active=False`) so new webhook activity for it is ignored, and records
  a `retention_days` value for a separately scheduled cleanup process to act
  on later — it does not itself delete historical review data.

### Enabling it

```bash
# .env
DASHBOARD_ENABLED=true
GITHUB_OAUTH_CLIENT_ID=...
GITHUB_OAUTH_CLIENT_SECRET=...
DASHBOARD_SESSION_SECRET=$(openssl rand -hex 32)
DASHBOARD_BASE_URL=https://your-deployment-host
```

Register the OAuth callback as
`<DASHBOARD_BASE_URL>/api/v1/dashboard/auth/callback` in the GitHub App's
"User authorization callback URL" (or a separate OAuth App during
development). Apply the `0012_dashboard` migration. `DASHBOARD_SESSION_SECRET`
must be a long random value in production and must never be reused from
`GITHUB_WEBHOOK_SECRET` or any other secret.

## Reliability, observability, and production hardening (Phase 13)

- **Retries**: every Celery task (`app/tasks/{github_webhook,analysis,ai_review,
  policy,checks,merge}.py`) classifies its own exceptions via
  `app.tasks._reliability.is_transient` — a DB/Redis connection error, or a
  GitHub network/429/5xx error — and retries only those, with exponential
  backoff and full jitter, up to `RELIABILITY_TASK_MAX_RETRIES`. A
  non-transient (business/validation) exception fails once and stops, same
  as before this phase. `GitHubClient` (`app/github/client.py`) separately
  retries its own idempotent GET/PATCH/PUT calls the same way; create-type
  POSTs (open a PR, post a comment, create a check run) are deliberately
  never retried at the HTTP layer — a lost response after a successful POST
  could otherwise create a duplicate. A POST failure still propagates to the
  task-level retry above, which re-runs the whole operation; every one of
  those operations already checks-before-creating (open-PR lookup, comment
  fingerprint dedup), so the retried task can't itself duplicate anything.
- **Dead-letter handling**: a task that exhausts its retries (or fails
  non-transiently) is recorded in `task_failures`
  (`app/models/reliability.py`, migration `0013_reliability.py`) with its
  exception, traceback, and retry count. Visible per-repository at
  `GET /api/v1/dashboard/repositories/{id}/task-failures` and in the
  dashboard UI, with a `.../resolve` action for an operator to acknowledge
  one (never deleted — same append-only pattern as the rest of this
  codebase's evidence tables).
- **Concurrency locks**: `app/locking.py` is a Redis-backed advisory lock
  (`SET NX PX`, TTL-bounded so a crashed worker can never wedge it forever).
  Used around PR create/update (keyed per-repository) and auto-merge (keyed
  per-repository) so two overlapping webhook deliveries can't race each
  other into opening a duplicate PR or double-merging. Off entirely via
  `RELIABILITY_LOCK_ENABLED=false`, and fails open (proceeds unsynchronized,
  logging a warning) if Redis itself is unreachable — correctness still
  rests on the idempotency already built into every downstream operation
  either way.
- **Automatic supersede-cancellation**: `_supersede_previous_snapshots`
  (`app/tasks/github_webhook.py`) marks every other still-active
  `DiffSnapshot` for a repository `cancelled` as soon as a newer push
  produces its own snapshot (excluding any snapshot that already merged
  successfully). Every pipeline task stage already checks
  `status == "cancelled"` before starting new work, so this makes automatic
  the same no-op behavior the dashboard's manual cancel button
  (Phase 12) relies on.
- **Metrics**: `GET /metrics` (Prometheus text format, `app/api/v1/metrics.py`
  + `app/observability/metrics.py`) exposes webhook latency, Celery queue
  depth, per-stage review duration, tool/model failure counts, GitHub
  rate-limit remaining, task retries/dead-letters, and quota rejections.
  Toggle with `METRICS_ENABLED`.
- **Distributed tracing**: OpenTelemetry, instrumenting FastAPI, Celery, and
  httpx (`app/observability/tracing.py`), off by default
  (`TRACING_ENABLED=false`) since it requires a reachable OTLP collector.
  When enabled, trace context propagates automatically from the webhook
  request through the full Celery task chain to GitHub/model calls.
- **Cost and quota limits**: off by default (`QUOTA_ENABLED=false`).
  `app.ai.service._quota_exceeded` counts `AIReview` rows in the trailing 24h
  per repository and per installation; exceeding either skips the model call
  and persists `AIReview(status="quota_exceeded")` — the existing Phase 7
  policy engine already treats any non-`"completed"` status as
  `HUMAN_REVIEW`, so this can never accidentally auto-approve.
- See [`docs/reliability.md`](docs/reliability.md) for backup, migration
  rollback, and incident-response guidance, and
  [`docs/load-testing.md`](docs/load-testing.md) for the fault-injection and
  load-testing approach.

### Enabling it

```bash
# .env
RELIABILITY_LOCK_ENABLED=true
METRICS_ENABLED=true
TRACING_ENABLED=false          # needs a reachable OTLP collector
QUOTA_ENABLED=false            # opt in to cap AI review spend
```

Apply the `0013_reliability` migration. Metrics and locking work with the
infrastructure this project already requires (Redis, Postgres) — no new
service to stand up unless tracing is turned on.

## Fine-tuning a custom code-review model (Phase 16)

Off by default (`FINETUNE_ENABLED=false`) and appropriate only after
thousands of consented, human-validated review examples exist and prompting/
retrieval alone have reached their practical limit — see
[`docs/fine-tuning.md`](docs/fine-tuning.md) for the full pipeline: dataset
export (`app/finetune/export.py`), an operator-supplied external LoRA/QLoRA
trainer invocation (`app/finetune/training.py` — this project does not
bundle a trainer), evaluation against the frozen benchmark and comparison
against the current baseline (`app/finetune/comparison.py`), canary/shadow
traffic (`app/finetune/shadow.py`) that never affects a live decision, and
immediate rollback (`app/finetune/rollback.py`). A fine-tuned model still
must clear the unchanged Phase 15 promotion gate
(`app.evaluation.promotion.promote_configuration`) before it can influence a
live review — fine-tuning only ever changes which `ReviewModel` the
*advisory* AI reviewer calls; the policy engine still controls merging.

### Enabling it

```bash
# .env
FINETUNE_ENABLED=true
FINETUNE_ADMIN_TOKEN=<long random value>
FINETUNE_TRAINER_COMMAND=/path/to/your/lora-trainer
```

Apply the `0016_finetune` migration.

## Multi-tenant SaaS readiness (Phase 17)

One `Organization` (the billing/RBAC tenant boundary) is auto-created per GitHub App
Installation (`app/tenancy/provisioning.py`), and dashboard sessions now carry a
role (`owner`/`admin`/`member`) per organization, synced at login
(`app/tenancy/membership.py`). This adds:

- Per-organization plan limits (AI review volume, connected repository count),
  layered on top of the existing Phase 13 quota, that can only ever skip an AI model
  call or leave a repository inactive — never disable a required deterministic check
  or widen auto-merge eligibility (`app/tenancy/plans.py`, `app/ai/service.py`).
- Self-service data export/deletion for an organization's own retained review evidence
  (`POST /api/v1/dashboard/organizations/{id}/export` and `.../delete-data`) — see
  [`docs/data-retention-and-deletion.md`](docs/data-retention-and-deletion.md).
- Optional Redis-backed rate limiting for the webhook and dashboard API
  (`TENANCY_RATE_LIMIT_ENABLED`), failing open if Redis is unreachable and closed
  (429) once a caller's per-minute budget is exceeded.
- Per-organization AI provider/model override (`ai_provider_override`/
  `ai_model_override` via `PUT /api/v1/dashboard/organizations/{id}/settings`,
  admin-only).

See [`docs/multi-tenancy.md`](docs/multi-tenancy.md) for the isolation boundary at
every layer (app/DB/cache/queue/runner/retrieval), [`SECURITY.md`](SECURITY.md) for
the vulnerability-reporting process, and
[`docs/incident-response.md`](docs/incident-response.md) for the incident process.
[`docs/terms-and-privacy.md`](docs/terms-and-privacy.md) is a drafting template only —
it requires legal review before use.

### Enabling rate limiting

```bash
# .env
TENANCY_RATE_LIMIT_ENABLED=true
TENANCY_WEBHOOK_RATE_LIMIT_PER_MINUTE=120
TENANCY_DASHBOARD_RATE_LIMIT_PER_MINUTE=120
```

Apply the `0017_multitenancy` migration.

## Notes

- The scheduled data-retention purge job implied by Phase 12's
  `retention_days` field is not yet implemented (currently recorded but not
  acted on automatically). An organization can still delete its retained data
  immediately and explicitly via the Phase 17 endpoint above.
- Phase 17's billing is internal metering only — no payment processor is
  integrated. See `docs/multi-tenancy.md` "Usage limits and billing-vs-safety".
