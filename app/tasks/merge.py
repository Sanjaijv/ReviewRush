import logging
from typing import Any

from app.celery_app import celery_app
from app.db import SessionLocal
from app.locking import LockNotAcquired, repository_lock
from app.merge.service import attempt_auto_merge_for_snapshot
from app.models import DiffSnapshot, Repository
from app.tasks._reliability import handle_task_failure

logger = logging.getLogger(__name__)


@celery_app.task(name="reviewrush.attempt_auto_merge", bind=True)
def attempt_auto_merge_task(self: Any, repository_id: int, diff_snapshot_id: int) -> str:
    db: Any = SessionLocal()
    try:
        repository = db.get(Repository, repository_id)
        diff_snapshot = db.get(DiffSnapshot, diff_snapshot_id)
        if repository is None or diff_snapshot is None:
            logger.warning(
                "auto-merge task received unknown repository or diff snapshot",
                extra={"repository_id": repository_id, "diff_snapshot_id": diff_snapshot_id},
            )
            return "skipped"
        if diff_snapshot.status == "cancelled":
            return "cancelled"

        # Concurrency lock (Phase 13): two auto-merge attempts for the same
        # repository must never race - GitHub's own `sha=` merge guard
        # backstops this, but the lock avoids two workers even attempting
        # simultaneous merge/comment/check-run writes for the same PR.
        try:
            with repository_lock(f"merge:{repository_id}"):
                attempt = attempt_auto_merge_for_snapshot(db, repository, diff_snapshot)
        except LockNotAcquired:
            logger.info(
                "auto-merge lock contended, skipping this attempt",
                extra={"repository_id": repository_id, "diff_snapshot_id": diff_snapshot_id},
            )
            return "lock_contended"
        return attempt.outcome
    except Exception as exc:
        logger.exception(
            "auto-merge attempt failed",
            extra={"repository_id": repository_id, "diff_snapshot_id": diff_snapshot_id},
        )
        db.rollback()
        handle_task_failure(
            self,
            exc,
            task_name="reviewrush.attempt_auto_merge",
            args=(repository_id, diff_snapshot_id),
            repository_id=repository_id,
            diff_snapshot_id=diff_snapshot_id,
        )
        return "failed"
    finally:
        db.close()
