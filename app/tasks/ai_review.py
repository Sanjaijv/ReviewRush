import logging
from typing import Any

from app.ai.service import run_ai_review_for_snapshot
from app.celery_app import celery_app
from app.config import get_settings
from app.db import SessionLocal
from app.models import DiffSnapshot, Repository
from app.reviewers.service import run_specialized_reviews_for_snapshot
from app.tasks._reliability import handle_task_failure
from app.tasks.policy import run_policy_decision_task

logger = logging.getLogger(__name__)


@celery_app.task(name="reviewrush.run_ai_review", bind=True)
def run_ai_review_task(self: Any, repository_id: int, diff_snapshot_id: int) -> str:
    db: Any = SessionLocal()
    try:
        repository = db.get(Repository, repository_id)
        diff_snapshot = db.get(DiffSnapshot, diff_snapshot_id)
        if repository is None or diff_snapshot is None:
            logger.warning(
                "AI review task received unknown repository or diff snapshot",
                extra={"repository_id": repository_id, "diff_snapshot_id": diff_snapshot_id},
            )
            return "skipped"
        if diff_snapshot.status == "cancelled":
            return "cancelled"

        ai_review = run_ai_review_for_snapshot(db, repository, diff_snapshot)
        # Specialized reviewers (Phase 14) enrich the general reviewer's
        # AIReview in place when enabled; a no-op (returns ai_review
        # unchanged) when the feature is off, the general review didn't
        # complete, or no specialist was selected for this diff.
        run_specialized_reviews_for_snapshot(db, repository, diff_snapshot, ai_review)
        # The policy engine (Phase 7) always runs after the AI reviewer, even
        # when AI review is disabled or failed: a missing AIReview must still
        # resolve to a HUMAN_REVIEW decision, not silently produce no
        # PolicyDecision at all.
        run_policy_decision_task.delay(repository_id, diff_snapshot_id)
        # Canary/shadow evaluation (Phase 16): fires only when explicitly
        # enabled and only after the real decision chain above is already
        # queued - a candidate model's comparison run can never precede or
        # gate the live policy decision.
        settings = get_settings()
        if (
            settings.finetune_shadow_eval_enabled
            and ai_review is not None
            and ai_review.status == "completed"
        ):
            from app.tasks.finetune import run_shadow_eval_task

            run_shadow_eval_task.delay(ai_review.id)
        return "completed"
    except Exception as exc:
        logger.exception(
            "AI review failed",
            extra={"repository_id": repository_id, "diff_snapshot_id": diff_snapshot_id},
        )
        db.rollback()
        handle_task_failure(
            self,
            exc,
            task_name="reviewrush.run_ai_review",
            args=(repository_id, diff_snapshot_id),
            repository_id=repository_id,
            diff_snapshot_id=diff_snapshot_id,
        )
        return "failed"
    finally:
        db.close()
