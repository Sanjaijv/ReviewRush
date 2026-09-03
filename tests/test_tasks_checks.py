from unittest.mock import MagicMock, patch

from app.tasks.checks import run_github_checks_task


def test_task_skips_when_repository_or_snapshot_missing() -> None:
    db = MagicMock()
    db.get.return_value = None

    with patch("app.tasks.checks.SessionLocal", return_value=db):
        with patch("app.tasks.checks.run_github_checks_for_snapshot") as run_mock:
            with patch("app.tasks.checks.attempt_auto_merge_task") as merge_task_mock:
                result = run_github_checks_task(repository_id=1, diff_snapshot_id=1)

    assert result == "skipped"
    run_mock.assert_not_called()
    merge_task_mock.delay.assert_not_called()
    db.close.assert_called_once()


def test_task_calls_service_and_returns_completed() -> None:
    db = MagicMock()
    repository = MagicMock()
    diff_snapshot = MagicMock()
    db.get.side_effect = [repository, diff_snapshot]

    with patch("app.tasks.checks.SessionLocal", return_value=db):
        with patch("app.tasks.checks.run_github_checks_for_snapshot") as run_mock:
            with patch("app.tasks.checks.attempt_auto_merge_task") as merge_task_mock:
                result = run_github_checks_task(repository_id=1, diff_snapshot_id=2)

    run_mock.assert_called_once_with(db, repository, diff_snapshot)
    merge_task_mock.delay.assert_called_once_with(1, 2)
    assert result == "completed"
    db.close.assert_called_once()


def test_task_rolls_back_and_returns_failed_on_exception() -> None:
    db = MagicMock()
    repository = MagicMock()
    diff_snapshot = MagicMock()
    db.get.side_effect = [repository, diff_snapshot]

    with patch("app.tasks.checks.SessionLocal", return_value=db):
        with patch(
            "app.tasks.checks.run_github_checks_for_snapshot", side_effect=RuntimeError("boom")
        ):
            with patch("app.tasks.checks.attempt_auto_merge_task") as merge_task_mock:
                result = run_github_checks_task(repository_id=1, diff_snapshot_id=2)

    assert result == "failed"
    db.rollback.assert_called_once()
    db.close.assert_called_once()
    merge_task_mock.delay.assert_not_called()
