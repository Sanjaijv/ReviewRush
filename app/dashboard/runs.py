from typing import Any

from app.models import AIReview, DiffSnapshot, MergeAttempt, PolicyDecision, ToolRun


def list_review_runs(
    db: Any, repository_id: int, *, limit: int = 50, offset: int = 0
) -> list[DiffSnapshot]:
    return (
        db.query(DiffSnapshot)
        .filter_by(repository_id=repository_id)
        .order_by(DiffSnapshot.created_at.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )


def summarize_run(diff_snapshot: DiffSnapshot) -> dict[str, Any]:
    return {
        "id": diff_snapshot.id,
        "head_sha": diff_snapshot.head_sha,
        "base_sha": diff_snapshot.base_sha,
        "status": diff_snapshot.status,
        "file_count": diff_snapshot.file_count,
        "total_changed_lines": diff_snapshot.total_changed_lines,
        "created_at": diff_snapshot.created_at.isoformat(),
    }


def get_run_detail(db: Any, repository_id: int, diff_snapshot_id: int) -> dict[str, Any] | None:
    """Drill-down view for one review run: the diff snapshot plus every
    downstream artifact tied to it (tool runs, the AI review and its
    findings, the policy decision, and any merge attempts) - everything a
    human needs to reconstruct why a merge decision came out the way it did.
    """
    diff_snapshot = (
        db.query(DiffSnapshot)
        .filter_by(id=diff_snapshot_id, repository_id=repository_id)
        .one_or_none()
    )
    if diff_snapshot is None:
        return None

    tool_runs = db.query(ToolRun).filter_by(diff_snapshot_id=diff_snapshot_id).all()
    ai_review = db.query(AIReview).filter_by(diff_snapshot_id=diff_snapshot_id).one_or_none()
    policy_decision = (
        db.query(PolicyDecision).filter_by(diff_snapshot_id=diff_snapshot_id).one_or_none()
    )
    merge_attempts = (
        db.query(MergeAttempt)
        .filter_by(diff_snapshot_id=diff_snapshot_id)
        .order_by(MergeAttempt.created_at.asc())
        .all()
    )

    return {
        "run": summarize_run(diff_snapshot),
        "changed_files": [
            {
                "path": f.new_path or f.old_path,
                "status": f.status,
                "additions": f.additions,
                "deletions": f.deletions,
            }
            for f in diff_snapshot.changed_files
        ],
        "tool_runs": [
            {
                "check_name": t.check_name,
                "category": t.category,
                "conclusion": t.conclusion,
                "required": t.required,
                "duration_ms": t.duration_ms,
                "summary": t.summary,
            }
            for t in tool_runs
        ],
        "ai_review": (
            {
                "status": ai_review.status,
                "decision": ai_review.decision,
                "risk": ai_review.risk,
                "confidence": ai_review.confidence,
                "summary": ai_review.summary,
                "provider": ai_review.provider,
                "model": ai_review.model,
                "findings": [
                    {
                        "file": f.file,
                        "start_line": f.start_line,
                        "end_line": f.end_line,
                        "severity": f.severity,
                        "category": f.category,
                        "title": f.title,
                        "recommendation": f.recommendation,
                    }
                    for f in ai_review.findings
                ],
            }
            if ai_review is not None
            else None
        ),
        "policy_decision": (
            {
                "decision": policy_decision.decision,
                "risk": policy_decision.risk,
                "reasons": policy_decision.reasons,
                "policy_version": policy_decision.policy_version,
            }
            if policy_decision is not None
            else None
        ),
        "merge_attempts": [
            {
                "outcome": m.outcome,
                "reasons": m.reasons,
                "created_at": m.created_at.isoformat(),
            }
            for m in merge_attempts
        ],
    }
