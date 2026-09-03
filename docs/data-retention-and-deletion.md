# Data retention and deletion

## What is retained

For each connected repository, ReviewRush stores: diff snapshots, deterministic-check
(`ToolRun`) results, AI review output and findings, policy decisions, posted review
comments (metadata, not full GitHub content beyond what was posted), merge attempt
records, and dashboard audit events. See `docs/multi-tenancy.md` for the full list of
tables and `app/tenancy/export.py` for exactly what an export contains.

## How long

- **Active repositories**: retained indefinitely by default, for as long as the
  repository stays connected - this is what makes rerun/audit/evaluation history
  useful.
- **Disconnected repositories**: `POST /api/v1/dashboard/repositories/{id}/disconnect`
  (`app/dashboard/control.py`) records a `retention_days` value (organization default:
  `Organization.retention_days_default`, falling back to
  `Settings.dashboard_default_retention_days`) for how long evidence should be kept
  after disconnection, for a separately scheduled cleanup process to enforce. This
  release records the policy; it does not yet run that scheduled cleanup job.
- **Feedback rows** (`FindingFeedback`) carry their own `retention_days`, set at
  submission time (Phase 15).

## Organization-initiated export and deletion

Per Phase 17, an organization admin/owner can act on their own retained data directly,
without waiting on a scheduled retention job:

- `POST /api/v1/dashboard/organizations/{id}/export` - any organization member can
  request a synchronous JSON export of everything the organization's repositories have
  retained (`app/tenancy/export.py`).
- `POST /api/v1/dashboard/organizations/{id}/delete-data` - an `owner`/`admin` can
  permanently delete that retained evidence immediately, with the organization's slug
  required in the request body as an explicit confirmation
  (`app/tenancy/deletion.py`).

Deletion removes review evidence (diffs, findings, checks, comments, merge history, the
RAG index) but intentionally leaves the `Repository`/`PullRequest`/`Installation`
account structure and the `AuditEvent` audit trail in place - the audit event recording
that the deletion happened, and who requested it, is written *before* the delete and
therefore survives it. This mirrors Section 7 of the roadmap ("preserve an immutable
audit record of automated merge decisions") - deletion of evidence must not be able to
also erase the record that evidence once existed and was removed.

## Region

`Organization.region` records a declared data-residency preference. This release has no
region-pinned infrastructure to enforce it against - it is stored so a future
region-aware deployment has somewhere to read the requirement from, and should not be
represented to customers as an enforced guarantee until that infrastructure exists.
