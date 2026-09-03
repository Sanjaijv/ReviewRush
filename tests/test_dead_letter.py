from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

from app.dashboard.deps import DashboardUser
from app.dashboard.reliability import (
    TaskFailureNotFound,
    resolve_task_failure,
    summarize_task_failure,
)
from app.models import Repository, TaskFailure
from app.tasks._reliability import record_dead_letter


def _user() -> DashboardUser:
    return DashboardUser(
        github_user_id=42, login="octocat", avatar_url="", installation_ids=frozenset({1})
    )


def test_record_dead_letter_persists_exception_details() -> None:
    db = MagicMock()

    with patch("app.tasks._reliability.SessionLocal", return_value=db):
        try:
            raise ValueError("bad state")
        except ValueError as exc:
            record_dead_letter(
                task_name="reviewrush.run_analysis_pipeline",
                task_id="task-123",
                args=(1, 2),
                kwargs={},
                exc=exc,
                retry_count=0,
                repository_id=1,
                diff_snapshot_id=2,
            )

    db.add.assert_called_once()
    row = db.add.call_args[0][0]
    assert isinstance(row, TaskFailure)
    assert row.task_name == "reviewrush.run_analysis_pipeline"
    assert row.task_id == "task-123"
    assert row.repository_id == 1
    assert row.diff_snapshot_id == 2
    assert row.exception_type == "ValueError"
    assert "bad state" in row.exception_message
    assert "ValueError" in row.traceback
    db.commit.assert_called_once()
    db.close.assert_called_once()


def test_record_dead_letter_never_raises_when_persisting_fails() -> None:
    """A failure to write the dead-letter row itself must never mask the
    original task failure it was trying to record.
    """
    db = MagicMock()
    db.commit.side_effect = RuntimeError("db unreachable")

    with patch("app.tasks._reliability.SessionLocal", return_value=db):
        record_dead_letter(
            task_name="reviewrush.run_analysis_pipeline",
            task_id="task-123",
            args=(),
            kwargs={},
            exc=ValueError("boom"),
            retry_count=0,
        )

    db.rollback.assert_called_once()


def test_resolve_task_failure_sets_resolved_fields() -> None:
    failure = TaskFailure(
        id=1,
        repository_id=1,
        task_name="reviewrush.run_analysis_pipeline",
        task_id="t1",
        exception_type="ValueError",
        exception_message="boom",
        traceback="",
    )
    db = MagicMock()
    db.query.return_value.filter_by.return_value.one_or_none.return_value = failure
    repository = Repository(id=1, installation_id=1, github_repo_id=1, owner="acme", name="w")

    resolved = resolve_task_failure(db, repository, 1, _user())

    assert resolved.resolved_at is not None
    assert resolved.resolved_by == "octocat"
    db.commit.assert_called_once()


def test_resolve_task_failure_raises_when_not_found() -> None:
    db = MagicMock()
    db.query.return_value.filter_by.return_value.one_or_none.return_value = None
    repository = Repository(id=1, installation_id=1, github_repo_id=1, owner="acme", name="w")

    try:
        resolve_task_failure(db, repository, 999, _user())
        raised = False
    except TaskFailureNotFound:
        raised = True
    assert raised


def test_summarize_task_failure_shape() -> None:
    failure = TaskFailure(
        id=1,
        repository_id=1,
        diff_snapshot_id=2,
        task_name="reviewrush.run_ai_review",
        task_id="t1",
        retry_count=3,
        exception_type="ValueError",
        exception_message="boom",
        traceback="",
        created_at=datetime.now(UTC),
    )
    summary = summarize_task_failure(failure)
    assert summary["task_name"] == "reviewrush.run_ai_review"
    assert summary["retry_count"] == 3
    assert summary["resolved_at"] is None
