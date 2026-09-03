import logging
from typing import Any

from app.celery_app import celery_app
from app.db import SessionLocal
from app.models import DiffSnapshot, Repository
from app.policy.service import run_policy_decision_for_snapshot
from app.tasks._reliability import handle_task_failure
from app.tasks.checks import run_github_checks_task

logger = logging.getLogger(__name__)


@celery_app.task(name="reviewrush.run_policy_decision", bind=True)
def run_policy_decision_task(self: Any, repository_id: int, diff_snapshot_id: int) -> str:
    db: Any = SessionLocal()
    try:
        repository = db.get(Repository, repository_id)
        diff_snapshot = db.get(DiffSnapshot, diff_snapshot_id)
        if repository is None or diff_snapshot is None:
            logger.warning(
                "policy decision task received unknown repository or diff snapshot",
                extra={"repository_id": repository_id, "diff_snapshot_id": diff_snapshot_id},
            )
            return "skipped"
        if diff_snapshot.status == "cancelled":
            return "cancelled"

        run_policy_decision_for_snapshot(db, repository, diff_snapshot)
        # Phase 8 always chains after the policy decision so it can complete
        # the check run and post the summary/inline comments from the final,
        # authoritative decision - never from an intermediate AI-only result.
        run_github_checks_task.delay(repository_id, diff_snapshot_id)
        return "completed"
    except Exception as exc:
        logger.exception(
            "policy decision failed",
            extra={"repository_id": repository_id, "diff_snapshot_id": diff_snapshot_id},
        )
        db.rollback()
        handle_task_failure(
            self,
            exc,
            task_name="reviewrush.run_policy_decision",
            args=(repository_id, diff_snapshot_id),
            repository_id=repository_id,
            diff_snapshot_id=diff_snapshot_id,
        )
        return "failed"
    finally:
        db.close()
