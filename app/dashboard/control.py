from datetime import UTC, datetime
from typing import Any

from app.dashboard.audit import record_audit_event
from app.dashboard.deps import DashboardUser
from app.models import AIReview, DiffSnapshot, PolicyDecision, Repository, ToolRun


class RunNotFound(Exception):
    pass


def _get_snapshot(db: Any, repository_id: int, diff_snapshot_id: int) -> DiffSnapshot:
    snapshot = (
        db.query(DiffSnapshot)
        .filter_by(id=diff_snapshot_id, repository_id=repository_id)
        .one_or_none()
    )
    if snapshot is None:
        raise RunNotFound(f"no review run {diff_snapshot_id} for repository {repository_id}")
    return snapshot


def rerun_review(
    db: Any, repository: Repository, diff_snapshot_id: int, user: DashboardUser
) -> DiffSnapshot:
    """Explicitly, and only on direct admin request, discard the pipeline's
    stored results for one review run and re-queue it from the deterministic
    analysis stage.

    Every other code path in this system treats ToolRun/AIReview/
    PolicyDecision as immutable per diff_snapshot_id specifically so a
    result already consumed by a later decision can never shift under it.
    This function is the one deliberate, audited exception to that rule -
    it requires an authenticated, authorized dashboard user, and the
    override is recorded in the audit log before anything is deleted.
    ReviewComment rows are left in place so a rerun's comments are edited
    in place on GitHub rather than duplicated.
    """
    from app.tasks.analysis import run_analysis_pipeline_task

    snapshot = _get_snapshot(db, repository.id, diff_snapshot_id)

    record_audit_event(
        db,
        action="review.rerun_requested",
        target_type="diff_snapshot",
        target_id=str(snapshot.id),
        repository_id=repository.id,
        actor_type="user",
        actor_user_id=user.github_user_id,
        actor_login=user.login,
        metadata={"head_sha": snapshot.head_sha},
    )

    db.query(ToolRun).filter_by(diff_snapshot_id=snapshot.id).delete()
    ai_review = db.query(AIReview).filter_by(diff_snapshot_id=snapshot.id).one_or_none()
    if ai_review is not None:
        db.delete(ai_review)
    db.query(PolicyDecision).filter_by(diff_snapshot_id=snapshot.id).delete()

    snapshot.status = "complete"
    db.commit()
    db.refresh(snapshot)

    run_analysis_pipeline_task.delay(repository.id, snapshot.id)
    return snapshot


def cancel_review(
    db: Any, repository: Repository, diff_snapshot_id: int, user: DashboardUser
) -> DiffSnapshot:
    """Mark a review run cancelled so each pipeline task stage no-ops the
    next time it checks in, rather than starting new work for this
    snapshot. Best-effort: a stage that is already executing when this is
    called is not preemptively killed.
    """
    snapshot = _get_snapshot(db, repository.id, diff_snapshot_id)

    snapshot.status = "cancelled"
    record_audit_event(
        db,
        action="review.cancelled",
        target_type="diff_snapshot",
        target_id=str(snapshot.id),
        repository_id=repository.id,
        actor_type="user",
        actor_user_id=user.github_user_id,
        actor_login=user.login,
        metadata={"head_sha": snapshot.head_sha},
    )
    db.commit()
    db.refresh(snapshot)
    return snapshot


def disconnect_repository(
    db: Any, repository: Repository, user: DashboardUser, retention_days: int | None
) -> Repository:
    """Deactivate a repository from the dashboard: new webhook activity for
    it is ignored (`is_active=False`) and `retention_days` records how long
    to keep its stored evidence, for a separately scheduled cleanup process
    to act on. Historical rows are not deleted here - a disconnect is a
    stop-processing switch, not a data-deletion job.
    """
    repository.is_active = False
    repository.disconnected_at = datetime.now(UTC)
    repository.disconnected_by = user.login
    repository.retention_days = retention_days

    record_audit_event(
        db,
        action="repository.disconnected",
        target_type="repository",
        target_id=str(repository.id),
        repository_id=repository.id,
        actor_type="user",
        actor_user_id=user.github_user_id,
        actor_login=user.login,
        metadata={"retention_days": retention_days},
    )
    db.commit()
    db.refresh(repository)
    return repository
