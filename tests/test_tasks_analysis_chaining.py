from unittest.mock import MagicMock, patch

from app.tasks.analysis import run_analysis_pipeline_task


def test_pipeline_task_enqueues_ai_review_task_after_completing() -> None:
    db = MagicMock()
    repository = MagicMock()
    diff_snapshot = MagicMock()
    db.get.side_effect = [repository, diff_snapshot]

    with patch("app.tasks.analysis.SessionLocal", return_value=db):
        with patch("app.tasks.analysis.run_analysis_for_snapshot") as run_mock:
            with patch("app.tasks.analysis.run_ai_review_task") as ai_task_mock:
                result = run_analysis_pipeline_task(repository_id=1, diff_snapshot_id=2)

    run_mock.assert_called_once_with(db, repository, diff_snapshot)
    ai_task_mock.delay.assert_called_once_with(1, 2)
    assert result == "completed"


def test_pipeline_task_skips_ai_review_when_repository_missing() -> None:
    db = MagicMock()
    db.get.return_value = None

    with patch("app.tasks.analysis.SessionLocal", return_value=db):
        with patch("app.tasks.analysis.run_ai_review_task") as ai_task_mock:
            result = run_analysis_pipeline_task(repository_id=1, diff_snapshot_id=2)

    ai_task_mock.delay.assert_not_called()
    assert result == "skipped"
