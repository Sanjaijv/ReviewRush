from functools import lru_cache

import redis

from app.config import get_settings
from app.observability.metrics import celery_queue_depth

# Celery's default queue name when no routing is configured - every task in
# this codebase runs on it, since `app/celery_app.py` doesn't declare
# per-task routes.
_QUEUES = ["celery"]


@lru_cache
def _redis_client() -> redis.Redis:
    return redis.Redis.from_url(get_settings().celery_broker, decode_responses=True)


def sample_queue_depth() -> None:
    """Refresh the queue-depth gauge from Redis (the Celery broker) list
    lengths. Best-effort: called on every /metrics scrape, so a transient
    Redis error here must not fail the scrape - the gauge just keeps its
    last known value.
    """
    try:
        client = _redis_client()
        for queue in _QUEUES:
            celery_queue_depth.labels(queue=queue).set(int(client.llen(queue)))  # type: ignore[arg-type]
    except redis.RedisError:
        pass
