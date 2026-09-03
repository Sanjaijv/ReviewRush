import uuid
from unittest.mock import patch

import pytest
import redis
from fastapi import HTTPException

from app.tenancy.rate_limit import check_rate_limit


class _FakeRedis:
    """Minimal in-memory stand-in for the two Redis calls this limiter makes,
    so these tests don't depend on a real Redis server being reachable."""

    def __init__(self) -> None:
        self._counts: dict[str, int] = {}

    def incr(self, key: str) -> int:
        self._counts[key] = self._counts.get(key, 0) + 1
        return self._counts[key]

    def expire(self, key: str, seconds: int) -> None:
        pass


def _fake_client() -> _FakeRedis:
    return _FakeRedis()


def test_disabled_limit_never_blocks() -> None:
    key = uuid.uuid4().hex
    with patch("app.tenancy.rate_limit._redis_client", return_value=_fake_client()):
        for _ in range(10):
            check_rate_limit(scope="test", key=key, limit_per_minute=0)


def test_limit_blocks_once_exceeded() -> None:
    key = uuid.uuid4().hex
    client = _fake_client()
    with patch("app.tenancy.rate_limit._redis_client", return_value=client):
        for _ in range(3):
            check_rate_limit(scope="test", key=key, limit_per_minute=3)

        with pytest.raises(HTTPException) as exc_info:
            check_rate_limit(scope="test", key=key, limit_per_minute=3)
    assert exc_info.value.status_code == 429


def test_different_keys_have_independent_budgets() -> None:
    scope = f"test-{uuid.uuid4().hex}"
    client = _fake_client()
    with patch("app.tenancy.rate_limit._redis_client", return_value=client):
        check_rate_limit(scope=scope, key="a", limit_per_minute=1)
        # A different key must not be blocked by "a" already using its budget.
        check_rate_limit(scope=scope, key="b", limit_per_minute=1)


def test_fails_open_when_redis_unreachable() -> None:
    key = uuid.uuid4().hex

    class _BrokenRedis:
        def incr(self, key: str) -> int:
            raise redis.ConnectionError("unreachable")

    with patch("app.tenancy.rate_limit._redis_client", return_value=_BrokenRedis()):
        # Must not raise, even far past any real limit.
        check_rate_limit(scope="test", key=key, limit_per_minute=1)
