# Multi-tenancy (Phase 17)

ReviewRush's tenant boundary is the **Organization**, introduced in Phase 17
(`app/models/tenancy.py`). One Organization is created automatically for every GitHub
App Installation (`app/tenancy/provisioning.py`) - this mirrors GitHub's own access
control exactly rather than inventing a cross-installation grouping the app has no
reliable signal to verify.

## Isolation per layer

| Layer | Enforcement |
|---|---|
| Application (dashboard API) | Every dashboard route depends on `get_authorized_repository` or `get_authorized_organization` (`app/dashboard/deps.py`), which 404s (not 403s) for anything outside the caller's `installation_ids`/`organization_roles` - captured from GitHub's own `/user/installations` at login, never derived from our own database. |
| Application (webhook) | Every webhook payload carries its own `installation`/`repository`, and every downstream query filters by `repository_id`/`installation_id`. |
| Database | Every row that matters for isolation (`Repository`, `DiffSnapshot`, `AIReview`, ...) carries a `repository_id` (transitively `installation_id` -> `organization_id`) foreign key; there is no cross-tenant query path in the codebase that omits that filter. |
| Cache/locks | `app/locking.py` keys are always repository/PR-scoped strings; `app/tenancy/rate_limit.py` keys are always installation-id (webhook) or GitHub-user-id (dashboard) scoped. |
| Queue (Celery) | Task arguments are always ids (`repository_id`, `diff_snapshot_id`, ...), re-resolved against the database inside the task - a task can't act on data it wasn't given the id for. |
| Runner (deterministic analysis sandbox) | Each analysis run gets its own container/workspace (`app/analysis/`), destroyed after the run; no shared filesystem or process state between repositories. |
| Retrieval (RAG index) | `RepoFileIndex`/`RepoSymbolChunk` rows and pgvector queries are always filtered by `repository_id` (`app/context/retrieval.py`). |

## Roles

`OrganizationMember.role` is one of `owner`, `admin`, `member`, synced at dashboard
login (`app/tenancy/membership.py`): the installer of a personal-account installation
is `owner`; anyone else GitHub reports as having installation access is inserted as
`member` on first login. Promotion beyond `member` is a deliberate action, never a
side effect of logging in again. `admin`/`owner` is required for organization settings,
data export, and data deletion (`app/dashboard/deps.py::require_org_admin`).

## Usage limits and billing-vs-safety

`app/tenancy/plans.py` defines per-plan defaults for AI review volume and connected
repository count, overridable per Organization. Exceeding a plan limit only ever:

- skips the AI model call for that review (`AIReview.status = "quota_exceeded"`,
  which the Phase 7 policy engine already treats as `HUMAN_REVIEW`), or
- leaves a newly-connected repository beyond the plan's repository cap inactive.

It never disables `analysis_semgrep_required`/`analysis_gitleaks_required` or any other
mandatory deterministic check, and it can never widen auto-merge eligibility - see
`app/ai/service.py::_quota_exceeded` and the accompanying test in
`tests/test_tenancy_quota.py`.

## Data export and deletion

`POST /api/v1/dashboard/organizations/{id}/export` (any member) and
`POST /api/v1/dashboard/organizations/{id}/delete-data` (`owner`/`admin`, requires the
organization's slug as confirmation) implement the Phase 17 acceptance criterion that
an organization can export or delete its retained data. Deletion removes review
evidence (diffs, AI findings, tool runs, policy decisions, comments, merge history,
RAG index) but never the immutable `AuditEvent` trail Section 7 of the roadmap
requires - the audit event recording the deletion is written before anything is
removed. See `app/tenancy/export.py` / `app/tenancy/deletion.py`.

## Ownership

Security and operational ownership of this deployment (on-call, incident response,
vulnerability triage) is the responsibility of whoever operates it - fill in a named
contact/rotation here before running this in production for external customers. See
`SECURITY.md` for the vulnerability-reporting process and `docs/incident-response.md`
for the incident process.
