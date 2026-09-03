import logging
import time
from functools import lru_cache

import redis
from fastapi import HTTPException, status

from app.config import Settings, get_settings

logger = logging.getLogger(__name__)

_RATE_LIMIT_KEY_PREFIX = "reviewrush:ratelimit:"


@lru_cache
def _redis_client() -> redis.Redis:
    return redis.Redis.from_url(get_settings().redis_url, decode_responses=True)


def check_rate_limit(*, scope: str, key: str, limit_per_minute: int) -> None:
    """Fixed-window-per-minute abuse-prevention limiter (Phase 17), keyed by
    an arbitrary caller-chosen identity (e.g. a GitHub installation id for
    the webhook endpoint, a GitHub user id for the dashboard API).

    Fails **open** if Redis is unreachable - mirroring `app.locking`'s
    existing tradeoff (correctness/availability of the underlying feature
    matters more than the abuse-prevention backstop when the backend itself
    is down) - but fails **closed** with a 429 once the limit is actually
    hit. `limit_per_minute <= 0` disables the check entirely (treated as
    "no limit configured" rather than "block everything").
    """
    if limit_per_minute <= 0:
        return

    window = int(time.time() // 60)
    redis_key = f"{_RATE_LIMIT_KEY_PREFIX}{scope}:{key}:{window}"

    try:
        client = _redis_client()
        count = int(client.incr(redis_key))  # type: ignore[arg-type]
        if count == 1:
            client.expire(redis_key, 120)
    except redis.RedisError:
        logger.warning(
            "rate limit backend unreachable, proceeding without a limit",
            extra={"scope": scope, "key": key},
        )
        return

    if count > limit_per_minute:
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "rate limit exceeded")


def check_webhook_rate_limit(settings: Settings, github_installation_id: int | None) -> None:
    if not settings.tenancy_rate_limit_enabled or github_installation_id is None:
        return
    check_rate_limit(
        scope="webhook",
        key=str(github_installation_id),
        limit_per_minute=settings.tenancy_webhook_rate_limit_per_minute,
    )


def check_dashboard_rate_limit(settings: Settings, github_user_id: int) -> None:
    if not settings.tenancy_rate_limit_enabled:
        return
    check_rate_limit(
        scope="dashboard",
        key=str(github_user_id),
        limit_per_minute=settings.tenancy_dashboard_rate_limit_per_minute,
    )
