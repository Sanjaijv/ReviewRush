from typing import Any

from app.models import (
    AIFinding,
    AIReview,
    AuditEvent,
    DiffSnapshot,
    MergeAttempt,
    Organization,
    PolicyDecision,
    PullRequest,
    Repository,
    ReviewComment,
    ToolRun,
)


def _repository_ids(db: Any, organization: Organization) -> list[int]:
    return [
        r.id
        for r in db.query(Repository)
        .filter_by(installation_id=organization.installation_id)
        .all()
    ]


def export_organization_data(db: Any, organization: Organization) -> dict[str, Any]:
    """Build a JSON-serializable export of everything ReviewRush retains for
    one Organization's repositories (Phase 17 acceptance criterion: "an
    organization can export its retained data").

    Synchronous and in-memory: this release has no blob-storage/async-job
    integration, so it is only suitable for organizations of a size that
    fits comfortably in one response - fine for the plan tiers this phase
    introduces (`app.tenancy.plans`), but a future larger-scale offering
    would need to make this an async job that writes to object storage
    instead.
    """
    repository_ids = _repository_ids(db, organization)

    repositories = db.query(Repository).filter(Repository.id.in_(repository_ids)).all()
    pull_requests = (
        db.query(PullRequest).filter(PullRequest.repository_id.in_(repository_ids)).all()
    )
    diff_snapshots = (
        db.query(DiffSnapshot).filter(DiffSnapshot.repository_id.in_(repository_ids)).all()
    )
    ai_reviews = db.query(AIReview).filter(AIReview.repository_id.in_(repository_ids)).all()
    ai_findings = db.query(AIFinding).filter(AIFinding.repository_id.in_(repository_ids)).all()
    tool_runs = db.query(ToolRun).filter(ToolRun.repository_id.in_(repository_ids)).all()
    policy_decisions = (
        db.query(PolicyDecision).filter(PolicyDecision.repository_id.in_(repository_ids)).all()
    )
    review_comments = (
        db.query(ReviewComment).filter(ReviewComment.repository_id.in_(repository_ids)).all()
    )
    merge_attempts = (
        db.query(MergeAttempt).filter(MergeAttempt.repository_id.in_(repository_ids)).all()
    )
    audit_events = (
        db.query(AuditEvent).filter(AuditEvent.repository_id.in_(repository_ids)).all()
    )

    return {
        "organization": {
            "id": organization.id,
            "slug": organization.slug,
            "name": organization.name,
            "plan": organization.plan,
            "region": organization.region,
        },
        "repositories": [
            {"id": r.id, "full_name": r.full_name, "is_active": r.is_active} for r in repositories
        ],
        "pull_requests": [
            {
                "id": p.id,
                "repository_id": p.repository_id,
                "github_pr_number": p.github_pr_number,
                "state": p.state,
            }
            for p in pull_requests
        ],
        "diff_snapshots": [
            {
                "id": d.id,
                "repository_id": d.repository_id,
                "head_sha": d.head_sha,
                "created_at": d.created_at.isoformat(),
            }
            for d in diff_snapshots
        ],
        "ai_reviews": [
            {
                "id": a.id,
                "repository_id": a.repository_id,
                "diff_snapshot_id": a.diff_snapshot_id,
                "status": a.status,
                "decision": a.decision,
                "risk": a.risk,
                "confidence": a.confidence,
            }
            for a in ai_reviews
        ],
        "ai_findings": [
            {
                "id": f.id,
                "ai_review_id": f.ai_review_id,
                "file": f.file,
                "severity": f.severity,
                "category": f.category,
                "title": f.title,
            }
            for f in ai_findings
        ],
        "tool_runs": [
            {
                "id": t.id,
                "repository_id": t.repository_id,
                "check_name": t.check_name,
                "conclusion": t.conclusion,
            }
            for t in tool_runs
        ],
        "policy_decisions": [
            {
                "id": p.id,
                "repository_id": p.repository_id,
                "diff_snapshot_id": p.diff_snapshot_id,
                "decision": p.decision,
                "risk": p.risk,
                "reasons": p.reasons,
            }
            for p in policy_decisions
        ],
        "review_comments": [
            {
                "id": c.id,
                "repository_id": c.repository_id,
                "pull_request_id": c.pull_request_id,
                "kind": c.kind,
                "status": c.status,
            }
            for c in review_comments
        ],
        "merge_attempts": [
            {
                "id": m.id,
                "repository_id": m.repository_id,
                "diff_snapshot_id": m.diff_snapshot_id,
                "outcome": m.outcome,
                "reasons": m.reasons,
            }
            for m in merge_attempts
        ],
        "audit_events": [
            {
                "id": e.id,
                "repository_id": e.repository_id,
                "action": e.action,
                "target_type": e.target_type,
                "target_id": e.target_id,
                "created_at": e.created_at.isoformat(),
            }
            for e in audit_events
        ],
    }
