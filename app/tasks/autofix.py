import logging
from typing import Any

from app.autofix.service import run_auto_fix_for_snapshot
from app.celery_app import celery_app
from app.db import SessionLocal
from app.github.auth import get_installation_access_token
from app.github.client import GitHubClient
from app.models import DiffSnapshot, Repository
from app.tasks._reliability import handle_task_failure

logger = logging.getLogger(__name__)


@celery_app.task(name="reviewrush.run_auto_fix", bind=True)
def run_auto_fix_task(self: Any, repository_id: int, diff_snapshot_id: int) -> str:
    db: Any = SessionLocal()
    try:
        repository = db.get(Repository, repository_id)
        diff_snapshot = db.get(DiffSnapshot, diff_snapshot_id)
        if repository is None or diff_snapshot is None:
            logger.warning(
                "auto-fix task received unknown repository or diff snapshot",
                extra={"repository_id": repository_id, "diff_snapshot_id": diff_snapshot_id},
            )
            return "skipped"
        if diff_snapshot.status == "cancelled":
            return "cancelled"

        token = get_installation_access_token(repository.installation.github_installation_id)
        with GitHubClient(token) as client:
            attempts = run_auto_fix_for_snapshot(db, client, repository, diff_snapshot)
        return f"completed:{len(attempts)}"
    except Exception as exc:
        logger.exception(
            "auto-fix task failed",
            extra={"repository_id": repository_id, "diff_snapshot_id": diff_snapshot_id},
        )
        db.rollback()
        handle_task_failure(
            self,
            exc,
            task_name="reviewrush.run_auto_fix",
            args=(repository_id, diff_snapshot_id),
            repository_id=repository_id,
            diff_snapshot_id=diff_snapshot_id,
        )
        return "failed"
    finally:
        db.close()
