"""Canary/shadow evaluation (Phase 16): re-runs an already-completed
review's diff through a candidate model, purely for comparison.

This must never touch the live decision path. It runs strictly after
`AIReview`/`PolicyDecision`/comments already exist for the diff snapshot,
writes only to `ShadowEvalResult`, and any failure here is swallowed (logged,
recorded with `status="error"`) rather than propagated - a broken candidate
model must never be able to fail or delay the real pipeline it is shadowing.
"""

import logging
from typing import Any

from app.ai.model import build_review_model
from app.ai.prompt import build_review_prompt
from app.ai.service import run_reviewer_pass
from app.config import Settings, get_settings
from app.context.service import build_repository_context_for_snapshot
from app.models import AIReview, DiffSnapshot, Repository, ShadowEvalResult, ToolRun
from app.repo_config import RepoConfig

logger = logging.getLogger(__name__)


def run_shadow_eval(
    db: Any,
    *,
    ai_review_id: int,
    settings: Settings | None = None,
    finetune_job_id: int | None = None,
) -> ShadowEvalResult | None:
    """Runs the configured shadow candidate model against the same diff an
    already-completed AIReview was scored on. Returns None (no row written)
    when shadow evaluation is disabled or no candidate model is configured -
    the same opt-in short-circuit pattern as `run_ai_review_for_snapshot`.
    """
    settings = settings or get_settings()
    if not settings.finetune_shadow_eval_enabled or not settings.finetune_shadow_candidate_model:
        return None

    ai_review = db.get(AIReview, ai_review_id)
    if ai_review is None or ai_review.status != "completed":
        return None

    diff_snapshot = db.get(DiffSnapshot, ai_review.diff_snapshot_id)
    repository = db.get(Repository, ai_review.repository_id)
    if diff_snapshot is None or repository is None:
        return None

    candidate_provider = settings.finetune_shadow_candidate_provider
    candidate_model = settings.finetune_shadow_candidate_model

    try:
        changed_files = list(diff_snapshot.changed_files)
        tool_runs = db.query(ToolRun).filter_by(diff_snapshot_id=diff_snapshot.id).all()
        context_snapshot = build_repository_context_for_snapshot(db, repository, diff_snapshot)

        review_prompt = build_review_prompt(
            repository=repository,
            diff_snapshot=diff_snapshot,
            changed_files=changed_files,
            tool_runs=tool_runs,
            repo_config=RepoConfig(),
            settings=settings,
            context_snapshot=context_snapshot,
        )
        changed_files_by_path = {(f.new_path or f.old_path or ""): f for f in changed_files}

        candidate_settings = settings.model_copy(
            update={"ai_provider": candidate_provider, "ai_model": candidate_model}
        )
        model = build_review_model(candidate_settings)
        if model is None:
            raise RuntimeError(f"unknown shadow provider: {candidate_provider}")

        outcome = run_reviewer_pass(
            model, review_prompt, changed_files_by_path, settings.ai_max_issues
        )
        if outcome.status != "completed" or outcome.output is None:
            result = ShadowEvalResult(
                ai_review_id=ai_review.id,
                finetune_job_id=finetune_job_id,
                candidate_provider=candidate_provider,
                candidate_model=candidate_model,
                live_issue_count=len(ai_review.findings),
                candidate_issue_count=0,
                comparison={},
                status="error",
                error_message=outcome.error_message or f"candidate status={outcome.status}",
            )
        else:
            live_categories = {f.category for f in ai_review.findings}
            candidate_categories = {i.category for i in outcome.output.issues}
            union = live_categories | candidate_categories
            overlap = len(live_categories & candidate_categories) / len(union) if union else 1.0
            result = ShadowEvalResult(
                ai_review_id=ai_review.id,
                finetune_job_id=finetune_job_id,
                candidate_provider=candidate_provider,
                candidate_model=candidate_model,
                live_issue_count=len(ai_review.findings),
                candidate_issue_count=len(outcome.output.issues),
                comparison={
                    "decision_diff": outcome.output.decision != ai_review.decision,
                    "category_overlap": overlap,
                    "candidate_decision": outcome.output.decision,
                    "live_decision": ai_review.decision,
                },
                status="completed",
            )
    except Exception as exc:
        logger.exception("shadow eval failed", extra={"ai_review_id": ai_review_id})
        result = ShadowEvalResult(
            ai_review_id=ai_review_id,
            finetune_job_id=finetune_job_id,
            candidate_provider=candidate_provider,
            candidate_model=candidate_model,
            live_issue_count=0,
            candidate_issue_count=0,
            comparison={},
            status="error",
            error_message=str(exc),
        )

    db.add(result)
    db.commit()
    db.refresh(result)
    return result
