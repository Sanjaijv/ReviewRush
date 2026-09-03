"""Shared retry-classification and dead-letter recording for every Celery
task in this codebase (Phase 13).

Every task already runs inside a broad `try/except Exception` that logs,
rolls back, and returns a "failed" status string rather than letting the
exception propagate - useful for keeping one bad delivery from crashing the
worker, but on its own it means a transient DB/Redis/GitHub blip and a
genuine bug look identical: both just stop, once, forever. This module adds
the missing distinction: a transient failure is retried with exponential
backoff and jitter (via Celery's own `task.retry`); a non-transient failure
(or one that has exhausted its retries) is written to `task_failures` so an
operator can see where and why a review stopped, instead of that only
existing in worker logs.
"""

import logging
import random
import traceback as traceback_module
from typing import Any

import httpx
import redis
from celery import Task
from sqlalchemy.exc import OperationalError

from app.config import get_settings
from app.db import SessionLocal
from app.models import TaskFailure
from app.observability.metrics import task_dead_letters_total, task_retries_total

logger = logging.getLogger(__name__)

_RETRYABLE_HTTP_STATUS = {429, 500, 502, 503, 504}
_MAX_STORED_MESSAGE_CHARS = 4000
_MAX_STORED_TRACEBACK_CHARS = 8000


def is_transient(exc: BaseException) -> bool:
    """True only for infrastructure-transient failures: a DB or Redis
    connection problem, or a GitHub network/429/5xx error that reached this
    layer (i.e. one `GitHubClient` itself didn't already retry and resolve -
    see `app.github.client` for what it retries internally). A validation
    error, a programming bug, or a non-retryable HTTP status is never
    transient and must fail once, not retry blindly against a state that
    will never change.
    """
    if isinstance(exc, OperationalError | redis.RedisError):
        return True
    if isinstance(exc, httpx.TransportError):
        return True
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code in _RETRYABLE_HTTP_STATUS
    return False


def _safe_task_args(args: tuple[Any, ...], kwargs: dict[str, Any]) -> dict[str, Any]:
    # Task arguments in this codebase are always small (ids, a delivery id,
    # an event type) - never raw webhook payloads or secrets - so storing
    # them verbatim is safe. Still stringify defensively in case a future
    # task argument isn't JSON-serializable as-is.
    return {"args": [repr(a) for a in args], "kwargs": {k: repr(v) for k, v in kwargs.items()}}


def record_dead_letter(
    *,
    task_name: str,
    task_id: str | None,
    args: tuple[Any, ...],
    kwargs: dict[str, Any],
    exc: BaseException,
    retry_count: int,
    repository_id: int | None = None,
    diff_snapshot_id: int | None = None,
) -> None:
    """Persist one dead-letter row for a task that has permanently failed
    (a non-transient exception, or a transient one whose retries are
    exhausted). Best-effort: a failure to write the dead-letter row must
    never mask the original task failure it was trying to record.
    """
    task_dead_letters_total.labels(task_name=task_name).inc()
    db = SessionLocal()
    try:
        db.add(
            TaskFailure(
                repository_id=repository_id,
                diff_snapshot_id=diff_snapshot_id,
                task_name=task_name,
                task_id=task_id or "",
                task_args=_safe_task_args(args, kwargs),
                retry_count=retry_count,
                exception_type=type(exc).__name__,
                exception_message=str(exc)[:_MAX_STORED_MESSAGE_CHARS],
                traceback=traceback_module.format_exc()[:_MAX_STORED_TRACEBACK_CHARS],
            )
        )
        db.commit()
    except Exception:
        logger.exception(
            "failed to record dead-letter task failure", extra={"task_name": task_name}
        )
        db.rollback()
    finally:
        db.close()


def handle_task_failure(
    task: Task,
    exc: Exception,
    *,
    task_name: str,
    args: tuple[Any, ...],
    kwargs: dict[str, Any] | None = None,
    repository_id: int | None = None,
    diff_snapshot_id: int | None = None,
) -> None:
    """Call from a task's `except Exception as exc:` block, after logging
    and rolling back the session, in place of just falling through to
    `return "failed"`.

    Retries transient failures with exponential backoff and jitter, up to
    `settings.reliability_task_max_retries`; raises Celery's `Retry` to
    reschedule (the caller's `return "failed"` is never reached in that
    case - `task.retry` always raises). Otherwise records a dead-letter row
    and returns normally, preserving today's "log it, mark it failed,
    return" behavior for every case that isn't a genuine retry.
    """
    settings = get_settings()
    kwargs = kwargs or {}

    if is_transient(exc) and task.request.retries < settings.reliability_task_max_retries:
        task_retries_total.labels(task_name=task_name).inc()
        capped_backoff = min(
            2**task.request.retries, settings.reliability_task_retry_backoff_max_seconds
        )
        # Full jitter (0..capped_backoff): spreads out a burst of workers
        # that all hit the same transient failure (e.g. a GitHub outage) at
        # once, instead of having them all retry in lockstep.
        countdown = random.uniform(0, capped_backoff)
        logger.warning(
            "transient task failure, retrying",
            extra={
                "task_name": task_name,
                "retry_count": task.request.retries,
                "countdown_seconds": round(countdown, 1),
            },
        )
        raise task.retry(
            exc=exc, countdown=countdown, max_retries=settings.reliability_task_max_retries
        )

    record_dead_letter(
        task_name=task_name,
        task_id=task.request.id,
        args=args,
        kwargs=kwargs,
        exc=exc,
        retry_count=task.request.retries,
        repository_id=repository_id,
        diff_snapshot_id=diff_snapshot_id,
    )
