from celery import Celery

from app.config import get_settings

settings = get_settings()

celery_app = Celery(
    "reviewrush",
    broker=settings.celery_broker,
    backend=settings.celery_backend,
    include=["app.tasks.sample"],
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    task_track_started=True,
)


def redis_is_ready() -> bool:
    try:
        conn = celery_app.connection()
        conn.ensure_connection(max_retries=1, timeout=2)
        conn.close()
        return True
    except Exception:
        return False
