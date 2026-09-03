import logging
from typing import Any

from app.celery_app import celery_app
from app.checks.service import run_github_checks_for_snapshot
from app.db import SessionLocal
from app.models import DiffSnapshot, Repository
from app.tasks._reliability import handle_task_failure
from app.tasks.merge import attempt_auto_merge_task

logger = logging.getLogger(__name__)


@celery_app.task(name="reviewrush.run_github_checks", bind=True)
def run_github_checks_task(self: Any, repository_id: int, diff_snapshot_id: int) -> str:
    db: Any = SessionLocal()
    try:
        repository = db.get(Repository, repository_id)
        diff_snapshot = db.get(DiffSnapshot, diff_snapshot_id)
        if repository is None or diff_snapshot is None:
            logger.warning(
                "github checks task received unknown repository or diff snapshot",
                extra={"repository_id": repository_id, "diff_snapshot_id": diff_snapshot_id},
            )
            return "skipped"
        if diff_snapshot.status == "cancelled":
            return "cancelled"

        run_github_checks_for_snapshot(db, repository, diff_snapshot)
        # Phase 9 always chains after checks/comments are published, so the
        # check run GitHub sees when computing mergeable_state already
        # reflects this snapshot's own completed conclusion.
        attempt_auto_merge_task.delay(repository_id, diff_snapshot_id)
        return "completed"
    except Exception as exc:
        logger.exception(
            "publishing github checks/comments failed",
            extra={"repository_id": repository_id, "diff_snapshot_id": diff_snapshot_id},
        )
        db.rollback()
        handle_task_failure(
            self,
            exc,
            task_name="reviewrush.run_github_checks",
            args=(repository_id, diff_snapshot_id),
            repository_id=repository_id,
            diff_snapshot_id=diff_snapshot_id,
        )
        return "failed"
    finally:
        db.close()
