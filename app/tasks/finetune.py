import logging
from typing import Any

from app.celery_app import celery_app
from app.config import get_settings
from app.db import SessionLocal
from app.finetune.shadow import run_shadow_eval
from app.finetune.training import run_job
from app.tasks._reliability import handle_task_failure

logger = logging.getLogger(__name__)


@celery_app.task(name="reviewrush.run_finetune_job", bind=True)
def run_finetune_job_task(self: Any, job_id: int) -> str:
    db: Any = SessionLocal()
    try:
        settings = get_settings()
        job = run_job(db, job_id, settings=settings)
        return job.status
    except Exception as exc:
        logger.exception("fine-tune job task failed", extra={"job_id": job_id})
        db.rollback()
        handle_task_failure(
            self, exc, task_name="reviewrush.run_finetune_job", args=(job_id,),
        )
        return "failed"
    finally:
        db.close()


@celery_app.task(name="reviewrush.run_shadow_eval", bind=True)
def run_shadow_eval_task(self: Any, ai_review_id: int, finetune_job_id: int | None = None) -> str:
    """Best-effort canary/shadow comparison, chained after a live AIReview
    completes. Never retried through the infra-retry path
    (`handle_task_failure`) - a broken shadow candidate is not an
    infrastructure failure worth retrying, and it must never be allowed to
    affect the review it is shadowing.
    """
    db: Any = SessionLocal()
    try:
        result = run_shadow_eval(db, ai_review_id=ai_review_id, finetune_job_id=finetune_job_id)
        return "skipped" if result is None else result.status
    except Exception:
        logger.exception("shadow eval task failed", extra={"ai_review_id": ai_review_id})
        db.rollback()
        return "failed"
    finally:
        db.close()
