import logging
from typing import Any

from app.analysis.service import run_analysis_for_snapshot
from app.celery_app import celery_app
from app.db import SessionLocal
from app.models import DiffSnapshot, Repository
from app.tasks._reliability import handle_task_failure
from app.tasks.ai_review import run_ai_review_task

logger = logging.getLogger(__name__)


@celery_app.task(name="reviewrush.run_analysis_pipeline", bind=True)
def run_analysis_pipeline_task(self: Any, repository_id: int, diff_snapshot_id: int) -> str:
    db: Any = SessionLocal()
    try:
        repository = db.get(Repository, repository_id)
        diff_snapshot = db.get(DiffSnapshot, diff_snapshot_id)
        if repository is None or diff_snapshot is None:
            logger.warning(
                "analysis task received unknown repository or diff snapshot",
                extra={"repository_id": repository_id, "diff_snapshot_id": diff_snapshot_id},
            )
            return "skipped"
        if diff_snapshot.status == "cancelled":
            return "cancelled"

        run_analysis_for_snapshot(db, repository, diff_snapshot)
        # The AI reviewer (Phase 6) always chains after the deterministic
        # pipeline so its prompt can include tool results; the task itself
        # checks AI_REVIEW_ENABLED and no-ops when the feature is off.
        run_ai_review_task.delay(repository_id, diff_snapshot_id)
        return "completed"
    except Exception as exc:
        logger.exception(
            "deterministic analysis pipeline failed",
            extra={"repository_id": repository_id, "diff_snapshot_id": diff_snapshot_id},
        )
        db.rollback()
        handle_task_failure(
            self,
            exc,
            task_name="reviewrush.run_analysis_pipeline",
            args=(repository_id, diff_snapshot_id),
            repository_id=repository_id,
            diff_snapshot_id=diff_snapshot_id,
        )
        return "failed"
    finally:
        db.close()
