from unittest.mock import MagicMock, patch

import httpx
import redis
from sqlalchemy.exc import OperationalError

from app.tasks._reliability import is_transient
from app.tasks.merge import attempt_auto_merge_task


def test_is_transient_classifies_connection_and_db_errors() -> None:
    assert is_transient(redis.ConnectionError("boom")) is True
    assert is_transient(OperationalError("stmt", {}, Exception("boom"))) is True
    assert is_transient(httpx.ConnectTimeout("boom")) is True


def test_is_transient_classifies_retryable_http_status() -> None:
    request = httpx.Request("GET", "https://api.github.com/x")
    for status in (429, 500, 502, 503, 504):
        response = httpx.Response(status, request=request)
        exc = httpx.HTTPStatusError("boom", request=request, response=response)
        assert is_transient(exc) is True


def test_is_transient_rejects_non_transient_http_status_and_value_errors() -> None:
    request = httpx.Request("GET", "https://api.github.com/x")
    for status in (400, 401, 403, 404, 422):
        response = httpx.Response(status, request=request)
        exc = httpx.HTTPStatusError("boom", request=request, response=response)
        assert is_transient(exc) is False
    assert is_transient(ValueError("bad input")) is False


def test_transient_failure_is_retried_not_dead_lettered() -> None:
    """A task whose body raises a transient exception takes the retry
    branch of `handle_task_failure`, not the dead-letter branch.

    Calling the task function directly (as this codebase's existing task
    tests all do, e.g. tests/test_tasks_merge.py) makes Celery consider it
    "called directly" (no real broker/worker request) - in that mode
    `task.retry()` documentedly re-raises the original exception rather
    than the `Retry` exception it would raise inside a real worker (which
    the worker's own execution wrapper catches to actually reschedule the
    task with the configured countdown). Either way, the important
    assertion is the same: retrying never falls through to dead-lettering.
    """
    db = MagicMock()
    repository = MagicMock()
    diff_snapshot = MagicMock()
    diff_snapshot.status = "complete"
    db.get.side_effect = [repository, diff_snapshot]

    transient_exc = redis.ConnectionError("redis unreachable")

    with patch("app.tasks.merge.SessionLocal", return_value=db):
        with patch(
            "app.tasks.merge.attempt_auto_merge_for_snapshot", side_effect=transient_exc
        ):
            with patch("app.tasks._reliability.record_dead_letter") as dead_letter_mock:
                raised = None
                try:
                    attempt_auto_merge_task(repository_id=1, diff_snapshot_id=2)
                except Exception as exc:
                    raised = exc

    assert raised is transient_exc
    dead_letter_mock.assert_not_called()


def test_non_transient_failure_is_dead_lettered_not_retried() -> None:
    db = MagicMock()
    repository = MagicMock()
    diff_snapshot = MagicMock()
    diff_snapshot.status = "complete"
    db.get.side_effect = [repository, diff_snapshot]

    with patch("app.tasks.merge.SessionLocal", return_value=db):
        with patch(
            "app.tasks.merge.attempt_auto_merge_for_snapshot", side_effect=ValueError("bad state")
        ):
            with patch("app.tasks._reliability.record_dead_letter") as dead_letter_mock:
                result = attempt_auto_merge_task(repository_id=1, diff_snapshot_id=2)

    assert result == "failed"
    dead_letter_mock.assert_called_once()
    _, kwargs = dead_letter_mock.call_args
    assert kwargs["task_name"] == "reviewrush.attempt_auto_merge"
    assert kwargs["repository_id"] == 1
    assert kwargs["diff_snapshot_id"] == 2
