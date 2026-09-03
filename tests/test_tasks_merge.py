from unittest.mock import MagicMock, patch

from app.tasks.merge import attempt_auto_merge_task


def test_task_skips_when_repository_or_snapshot_missing() -> None:
    db = MagicMock()
    db.get.return_value = None

    with patch("app.tasks.merge.SessionLocal", return_value=db):
        with patch("app.tasks.merge.attempt_auto_merge_for_snapshot") as run_mock:
            result = attempt_auto_merge_task(repository_id=1, diff_snapshot_id=1)

    assert result == "skipped"
    run_mock.assert_not_called()
    db.close.assert_called_once()


def test_task_returns_attempt_outcome() -> None:
    db = MagicMock()
    repository = MagicMock()
    diff_snapshot = MagicMock()
    db.get.side_effect = [repository, diff_snapshot]
    attempt = MagicMock()
    attempt.outcome = "merged"

    with patch("app.tasks.merge.SessionLocal", return_value=db):
        with patch(
            "app.tasks.merge.attempt_auto_merge_for_snapshot", return_value=attempt
        ) as run_mock:
            result = attempt_auto_merge_task(repository_id=1, diff_snapshot_id=2)

    run_mock.assert_called_once_with(db, repository, diff_snapshot)
    assert result == "merged"
    db.close.assert_called_once()


def test_task_rolls_back_and_returns_failed_on_exception() -> None:
    db = MagicMock()
    repository = MagicMock()
    diff_snapshot = MagicMock()
    db.get.side_effect = [repository, diff_snapshot]

    with patch("app.tasks.merge.SessionLocal", return_value=db):
        with patch(
            "app.tasks.merge.attempt_auto_merge_for_snapshot", side_effect=RuntimeError("boom")
        ):
            result = attempt_auto_merge_task(repository_id=1, diff_snapshot_id=2)

    assert result == "failed"
    db.rollback.assert_called_once()
    db.close.assert_called_once()
