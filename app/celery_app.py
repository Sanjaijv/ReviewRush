from celery import Celery

from app.config import get_settings
from app.observability.tracing import setup_tracing

settings = get_settings()
# Configures tracing once per process: harmless to call from both the API
# process (which also calls it in app/main.py, a no-op the second time) and
# the worker process (which only ever imports this module).
setup_tracing(settings)

celery_app = Celery(
    "reviewrush",
    broker=settings.celery_broker,
    backend=settings.celery_backend,
    include=[
        "app.tasks.sample",
        "app.tasks.github_webhook",
        "app.tasks.analysis",
        "app.tasks.ai_review",
        "app.tasks.policy",
        "app.tasks.checks",
        "app.tasks.merge",
        "app.tasks.finetune",
    ],
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
