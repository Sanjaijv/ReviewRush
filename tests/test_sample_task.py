from app.celery_app import celery_app
from app.tasks.sample import ping


def test_worker_completes_sample_task_eagerly() -> None:
    celery_app.conf.task_always_eager = True
    celery_app.conf.task_eager_propagates = True
    try:
        result = ping.delay()
        assert result.get(timeout=5) == "pong"
    finally:
        celery_app.conf.task_always_eager = False
