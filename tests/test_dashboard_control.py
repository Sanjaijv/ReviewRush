from unittest.mock import MagicMock, patch

import pytest

from app.dashboard.control import (
    RunNotFound,
    cancel_review,
    disconnect_repository,
    rerun_review,
)
from app.dashboard.deps import DashboardUser
from app.models import AIReview, DiffSnapshot, Repository


def _user() -> DashboardUser:
    return DashboardUser(
        github_user_id=42, login="octocat", avatar_url="", installation_ids=frozenset({1})
    )


def _repository() -> Repository:
    return Repository(id=1, installation_id=1, github_repo_id=1, owner="acme", name="widgets")


def _db(*, snapshot: DiffSnapshot | None, ai_review: AIReview | None = None) -> MagicMock:
    db = MagicMock()

    def query_side_effect(model):
        q = MagicMock()
        if model is DiffSnapshot:
            q.filter_by.return_value.one_or_none.return_value = snapshot
        elif model is AIReview:
            q.filter_by.return_value.one_or_none.return_value = ai_review
        return q

    db.query.side_effect = query_side_effect
    return db


def test_rerun_missing_run_raises() -> None:
    db = _db(snapshot=None)

    with pytest.raises(RunNotFound):
        rerun_review(db, _repository(), 999, _user())


def test_rerun_deletes_stale_rows_and_requeues() -> None:
    snapshot = DiffSnapshot(
        id=5, repository_id=1, head_sha="sha1", base_sha="base", status="complete"
    )
    ai_review = AIReview(id=9, repository_id=1, diff_snapshot_id=5, status="completed")
    db = _db(snapshot=snapshot, ai_review=ai_review)

    with patch("app.tasks.analysis.run_analysis_pipeline_task") as task:
        result = rerun_review(db, _repository(), 5, _user())

        task.delay.assert_called_once_with(1, 5)

    assert result.status == "complete"
    db.delete.assert_called_once_with(ai_review)
    # An AuditEvent was recorded before the stale rows were touched.
    added_types = {type(c.args[0]).__name__ for c in db.add.call_args_list}
    assert "AuditEvent" in added_types


def test_cancel_sets_status_without_deleting_anything() -> None:
    snapshot = DiffSnapshot(
        id=5, repository_id=1, head_sha="sha1", base_sha="base", status="complete"
    )
    db = _db(snapshot=snapshot)

    result = cancel_review(db, _repository(), 5, _user())

    assert result.status == "cancelled"
    db.delete.assert_not_called()


def test_cancel_missing_run_raises() -> None:
    db = _db(snapshot=None)

    with pytest.raises(RunNotFound):
        cancel_review(db, _repository(), 999, _user())


def test_disconnect_deactivates_and_records_retention() -> None:
    repository = _repository()
    db = MagicMock()

    updated = disconnect_repository(db, repository, _user(), retention_days=30)

    assert updated.is_active is False
    assert updated.disconnected_by == "octocat"
    assert updated.retention_days == 30
    assert updated.disconnected_at is not None
    added_types = {type(c.args[0]).__name__ for c in db.add.call_args_list}
    assert "AuditEvent" in added_types
