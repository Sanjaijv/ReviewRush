from typing import Any

from sqlalchemy import func

from app.models import (
    AIFinding,
    AIReview,
    DiffSnapshot,
    FindingFeedback,
    MergeAttempt,
    PolicyDecision,
)


def compute_repository_metrics(db: Any, repository_id: int) -> dict[str, Any]:
    """Aggregate the Phase 12 dashboard metrics from existing immutable
    review evidence - no separate metrics store, so there is nothing here
    that can drift from the underlying rows.

    `false_positive_rate` is derived from Phase 15 developer feedback:
    consented "incorrect" reactions over consented "useful"+"incorrect"
    reactions. It is `None` (not 0.0) whenever no consented feedback of
    either kind exists yet - a repository with zero labeled feedback has an
    *unknown* false-positive rate, not a perfect one.
    """
    total_reviews = db.query(func.count(DiffSnapshot.id)).filter(
        DiffSnapshot.repository_id == repository_id
    ).scalar() or 0

    avg_review_time_ms = (
        db.query(func.avg(AIReview.latency_ms))
        .filter(AIReview.repository_id == repository_id, AIReview.status == "completed")
        .scalar()
    )

    findings_by_severity = dict(
        db.query(AIFinding.severity, func.count(AIFinding.id))
        .filter(AIFinding.repository_id == repository_id)
        .group_by(AIFinding.severity)
        .all()
    )

    decisions_by_outcome = dict(
        db.query(PolicyDecision.decision, func.count(PolicyDecision.id))
        .filter(PolicyDecision.repository_id == repository_id)
        .group_by(PolicyDecision.decision)
        .all()
    )
    blocked_merges = decisions_by_outcome.get("BLOCK", 0) + decisions_by_outcome.get(
        "HUMAN_REVIEW", 0
    )

    merge_attempts_by_outcome = dict(
        db.query(MergeAttempt.outcome, func.count(MergeAttempt.id))
        .filter(MergeAttempt.repository_id == repository_id)
        .group_by(MergeAttempt.outcome)
        .all()
    )

    model_usage_rows = (
        db.query(
            AIReview.provider,
            AIReview.model,
            func.count(AIReview.id),
            func.sum(AIReview.prompt_tokens),
            func.sum(AIReview.completion_tokens),
        )
        .filter(AIReview.repository_id == repository_id, AIReview.status == "completed")
        .group_by(AIReview.provider, AIReview.model)
        .all()
    )
    model_usage = [
        {
            "provider": provider,
            "model": model,
            "review_count": count,
            "prompt_tokens": int(prompt_tokens or 0),
            "completion_tokens": int(completion_tokens or 0),
        }
        for provider, model, count, prompt_tokens, completion_tokens in model_usage_rows
    ]

    feedback_by_reaction = dict(
        db.query(FindingFeedback.reaction, func.count(FindingFeedback.id))
        .filter(FindingFeedback.repository_id == repository_id, FindingFeedback.consent.is_(True))
        .group_by(FindingFeedback.reaction)
        .all()
    )
    useful_count = feedback_by_reaction.get("useful", 0)
    incorrect_count = feedback_by_reaction.get("incorrect", 0)
    labeled_count = useful_count + incorrect_count
    false_positive_rate = incorrect_count / labeled_count if labeled_count else None

    return {
        "total_reviews": total_reviews,
        "avg_review_time_ms": float(avg_review_time_ms) if avg_review_time_ms is not None else None,
        "findings_by_severity": findings_by_severity,
        "policy_decisions_by_outcome": decisions_by_outcome,
        "blocked_merges": blocked_merges,
        "merge_attempts_by_outcome": merge_attempts_by_outcome,
        "model_usage": model_usage,
        "feedback_by_reaction": feedback_by_reaction,
        "false_positive_rate": false_positive_rate,
        "false_positive_rate_note": (
            None
            if labeled_count
            else "not available - no consented developer feedback recorded yet"
        ),
    }
