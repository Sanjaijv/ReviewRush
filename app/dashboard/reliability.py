from datetime import UTC, datetime
from typing import Any

from app.dashboard.audit import record_audit_event
from app.dashboard.deps import DashboardUser
from app.models import Repository, TaskFailure


class TaskFailureNotFound(Exception):
    pass


def list_task_failures(
    db: Any,
    repository_id: int,
    *,
    include_resolved: bool = False,
    limit: int = 100,
    offset: int = 0,
) -> list[TaskFailure]:
    """List dead-lettered task failures for a repository (Phase 13), most
    recent first. Scoped to failures that carried a repository_id at
    dead-letter time - a task with no specific repository context (e.g. an
    installation-level webhook event) isn't attributable to any one
    repository's dashboard view.
    """
    query = db.query(TaskFailure).filter_by(repository_id=repository_id)
    if not include_resolved:
        query = query.filter(TaskFailure.resolved_at.is_(None))
    return query.order_by(TaskFailure.created_at.desc()).offset(offset).limit(limit).all()


def summarize_task_failure(failure: TaskFailure) -> dict[str, Any]:
    return {
        "id": failure.id,
        "diff_snapshot_id": failure.diff_snapshot_id,
        "task_name": failure.task_name,
        "task_id": failure.task_id,
        "retry_count": failure.retry_count,
        "exception_type": failure.exception_type,
        "exception_message": failure.exception_message,
        "resolved_at": failure.resolved_at.isoformat() if failure.resolved_at else None,
        "resolved_by": failure.resolved_by,
        "created_at": failure.created_at.isoformat(),
    }


def resolve_task_failure(
    db: Any, repository: Repository, task_failure_id: int, user: DashboardUser
) -> TaskFailure:
    """Mark a dead-lettered task failure acknowledged. Never deletes the
    row - `resolved_at`/`resolved_by` record that an operator has seen and
    handled it, the same append-only pattern as every other evidence table
    in this codebase.
    """
    failure = (
        db.query(TaskFailure)
        .filter_by(id=task_failure_id, repository_id=repository.id)
        .one_or_none()
    )
    if failure is None:
        raise TaskFailureNotFound(
            f"no task failure {task_failure_id} for repository {repository.id}"
        )

    failure.resolved_at = datetime.now(UTC)
    failure.resolved_by = user.login
    record_audit_event(
        db,
        action="task_failure.resolved",
        target_type="task_failure",
        target_id=str(failure.id),
        repository_id=repository.id,
        actor_type="user",
        actor_user_id=user.github_user_id,
        actor_login=user.login,
        metadata={"task_name": failure.task_name},
    )
    db.commit()
    db.refresh(failure)
    return failure
