import logging
from typing import Any

from app.autofix.service import run_auto_fix_for_snapshot, run_manual_fix
from app.celery_app import celery_app
from app.db import SessionLocal
from app.github.auth import get_installation_access_token
from app.github.client import GitHubClient
from app.models import AIFinding, DiffSnapshot, PullRequest, Repository, ReviewComment
from app.tasks._reliability import handle_task_failure
from app.tasks.review_trigger import trigger_review_for_commit

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


@celery_app.task(name="reviewrush.run_manual_fix", bind=True)
def run_manual_fix_task(
    self: Any,
    repository_id: int,
    diff_snapshot_id: int,
    ai_finding_id: int,
    review_comment_id: int | None,
    actor_login: str,
    current_comment_body: str,
) -> str:
    db: Any = SessionLocal()
    try:
        repository = db.get(Repository, repository_id)
        diff_snapshot = db.get(DiffSnapshot, diff_snapshot_id)
        finding = db.get(AIFinding, ai_finding_id)
        if repository is None or diff_snapshot is None or finding is None:
            logger.warning(
                "manual-fix task received unknown repository, diff snapshot, or finding",
                extra={
                    "repository_id": repository_id,
                    "diff_snapshot_id": diff_snapshot_id,
                    "ai_finding_id": ai_finding_id,
                },
            )
            return "skipped"
        review_comment = (
            db.get(ReviewComment, review_comment_id) if review_comment_id is not None else None
        )

        token = get_installation_access_token(repository.installation.github_installation_id)
        with GitHubClient(token) as client:
            attempt = run_manual_fix(
                db, client, repository, diff_snapshot, finding, review_comment, actor_login,
                current_comment_body,
            )
            # A direct commit to the reviewed branch never gets its own push
            # webhook acted on - `_handle_push` intentionally ignores every
            # bot-authored push, to avoid an automation loop. Without this,
            # the fix would land with no fresh review, no new check run, and
            # a required check left pointing at the pre-fix commit.
            if attempt is not None and attempt.status == "committed" and attempt.commit_sha:
                pull_request = (
                    db.get(PullRequest, diff_snapshot.pull_request_id)
                    if diff_snapshot.pull_request_id is not None
                    else None
                )
                if pull_request is not None:
                    trigger_review_for_commit(
                        db, client, repository, pull_request.base_branch,
                        attempt.commit_sha, pull_request,
                    )
        return "skipped" if attempt is None else attempt.status
    except Exception as exc:
        logger.exception(
            "manual-fix task failed",
            extra={"repository_id": repository_id, "ai_finding_id": ai_finding_id},
        )
        db.rollback()
        handle_task_failure(
            self,
            exc,
            task_name="reviewrush.run_manual_fix",
            args=(repository_id, diff_snapshot_id, ai_finding_id),
            repository_id=repository_id,
            diff_snapshot_id=diff_snapshot_id,
        )
        return "failed"
    finally:
        db.close()
