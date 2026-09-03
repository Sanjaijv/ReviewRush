import logging
import time
import uuid
from collections.abc import Generator
from contextlib import contextmanager
from functools import lru_cache

import redis

from app.config import get_settings

logger = logging.getLogger(__name__)

_LOCK_KEY_PREFIX = "reviewrush:lock:"

# Released via a Lua script so a lock is only ever deleted by the token that
# created it - a slow holder whose lock already expired must never have its
# *new* lock torn down by a late `release()` call from the previous attempt.
_RELEASE_SCRIPT = """
if redis.call("get", KEYS[1]) == ARGV[1] then
    return redis.call("del", KEYS[1])
else
    return 0
end
"""


@lru_cache
def _redis_client() -> redis.Redis:
    return redis.Redis.from_url(get_settings().redis_url, decode_responses=True)


class LockNotAcquired(Exception):
    """Raised when a repository/PR concurrency lock could not be acquired
    within the configured wait time - the caller should skip its critical
    section rather than proceed unsynchronized.
    """


@contextmanager
def repository_lock(key: str) -> Generator[None, None, None]:
    """Best-effort distributed advisory lock (Redis SET NX PX), keyed by an
    arbitrary caller-chosen string (typically a repository id, or a
    repository+PR pair).

    Guards against two concurrent webhook deliveries or worker retries for
    the same repository racing to open duplicate PRs or double-merge - not
    a substitute for GitHub's own optimistic-concurrency checks (PR number
    lookup, `sha=` on merge), which still apply underneath it.

    A lock held past `reliability_lock_timeout_seconds` expires on its own
    (TTL), so a crashed worker can never wedge the repository forever.
    No-ops (always yields) when `reliability_lock_enabled` is off, or when
    Redis itself is unreachable - correctness in that case still rests on
    the idempotency already built into every downstream operation.
    """
    settings = get_settings()
    if not settings.reliability_lock_enabled:
        yield
        return

    lock_key = f"{_LOCK_KEY_PREFIX}{key}"
    token = uuid.uuid4().hex
    client = _redis_client()
    deadline = time.monotonic() + settings.reliability_lock_wait_seconds
    acquired = False

    try:
        while time.monotonic() < deadline:
            acquired = bool(
                client.set(
                    lock_key, token, nx=True, px=settings.reliability_lock_timeout_seconds * 1000
                )
            )
            if acquired:
                break
            time.sleep(0.1)
    except redis.RedisError:
        logger.warning("lock backend unreachable, proceeding without a lock", extra={"key": key})
        yield
        return

    if not acquired:
        raise LockNotAcquired(f"could not acquire lock {key!r} within the configured wait time")

    try:
        yield
    finally:
        try:
            client.eval(_RELEASE_SCRIPT, 1, lock_key, token)
        except redis.RedisError:
            logger.warning("failed to release lock, will expire via TTL", extra={"key": key})
