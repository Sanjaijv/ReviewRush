# Incident response

This document describes how to respond to a security or availability incident
affecting ReviewRush. It complements `SECURITY.md` (how vulnerabilities are reported)
and `docs/multi-tenancy.md` (isolation boundaries an incident might have crossed).

## Roles

- **Incident commander (IC)**: coordinates the response, owns the decision to
  escalate/contain/notify, and is the single point of external communication.
- **Responder(s)**: investigate, contain, and remediate under the IC's direction.
- Fill in named individuals/rotations for these roles before operating this in
  production for external tenants.

## Severity levels

| Severity | Definition | Examples |
|---|---|---|
| SEV1 | Active cross-tenant data exposure, credential/secret leak, or full outage | Organization A can read Organization B's review data; GitHub App private key exposed |
| SEV2 | Degraded isolation or safety guarantee without confirmed exposure, or partial outage | A dependency vulnerability in the request path; auto-merge running with a stale policy decision |
| SEV3 | Isolated bug with no security/isolation impact | A dashboard UI rendering bug |

## Process

1. **Detect** - via `GET /metrics` alerting, `/api/v1/health/ready`, a vulnerability
   report (`SECURITY.md`), or a user report.
2. **Triage** - assign a severity and an IC within 15 minutes for SEV1/SEV2.
3. **Contain** - the fastest safe stop is usually one of:
   - Disable the affected feature flag in `app/config.py` (e.g.
     `merge_auto_merge_enabled=false`, `ai_review_enabled=false`,
     `dashboard_enabled=false`) and redeploy/restart - every optional surface in this
     codebase is built to fail closed to human review when disabled, not to error.
   - Suspend the specific GitHub App Installation (revoke via GitHub if the isolation
     boundary itself is suspected to be broken for one tenant).
   - Rotate the credential in question (`GITHUB_PRIVATE_KEY`, `GITHUB_WEBHOOK_SECRET`,
     `DASHBOARD_SESSION_SECRET`, `EVAL_ADMIN_TOKEN`, `FINETUNE_ADMIN_TOKEN`) - rotating
     `DASHBOARD_SESSION_SECRET` immediately invalidates every existing dashboard
     session.
4. **Eradicate** - fix the root cause, add or update a regression test
   (`tests/test_multitenancy_isolation.py` is the place for a cross-tenant isolation
   regression specifically).
5. **Recover** - re-enable the feature flag(s) disabled in containment.
6. **Notify** - for a confirmed SEV1 involving another tenant's data, notify affected
   organizations per `docs/data-retention-and-deletion.md`/`docs/terms-and-privacy.md`
   commitments and applicable law.
7. **Post-incident review** - a written summary (timeline, root cause, what changed) is
   required for every SEV1/SEV2, appended to this repository's incident log (kept
   outside version control if it would contain customer-identifying detail).

## Immutable evidence

`AuditEvent` rows (`app/models/dashboard.py`) are the authoritative, immutable record
of every automated merge decision and dashboard admin action - they are never deleted,
including by the Phase 17 organization data-deletion endpoint
(`app/tenancy/deletion.py`). Reconstructing "what happened" for an incident should
start there.
