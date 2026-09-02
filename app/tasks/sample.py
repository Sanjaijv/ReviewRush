from app.celery_app import celery_app


@celery_app.task(name="reviewrush.ping")
def ping() -> str:
    """Sample task proving the worker can receive and complete work."""
    return "pong"
