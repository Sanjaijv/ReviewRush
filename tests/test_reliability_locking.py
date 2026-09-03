import threading
import time
import uuid
from unittest.mock import patch

import pytest

from app.config import Settings
from app.locking import LockNotAcquired, repository_lock


def _settings(**overrides) -> Settings:
    base = dict(reliability_lock_enabled=True, reliability_lock_timeout_seconds=5)
    base.update(overrides)
    return Settings(**base)


def test_lock_is_exclusive_between_two_holders() -> None:
    key = f"test-{uuid.uuid4().hex}"
    settings = _settings(reliability_lock_wait_seconds=0.3)

    with patch("app.locking.get_settings", return_value=settings):
        with pytest.raises(LockNotAcquired):
            with repository_lock(key):
                with repository_lock(key):
                    pass  # pragma: no cover - never reached


def test_lock_is_released_on_exit_and_reusable() -> None:
    key = f"test-{uuid.uuid4().hex}"
    settings = _settings(reliability_lock_wait_seconds=1.0)

    with patch("app.locking.get_settings", return_value=settings):
        with repository_lock(key):
            pass
        # The first `with` block released the lock on exit - a second
        # acquisition of the same key must succeed immediately, not wait.
        with repository_lock(key):
            pass


def test_lock_unblocks_a_waiter_once_released() -> None:
    key = f"test-{uuid.uuid4().hex}"
    settings = _settings(reliability_lock_wait_seconds=2.0)
    events: list[str] = []

    def holder() -> None:
        with patch("app.locking.get_settings", return_value=settings):
            with repository_lock(key):
                events.append("acquired")
                time.sleep(0.3)
        events.append("released")

    t = threading.Thread(target=holder)
    t.start()
    time.sleep(0.05)  # let the holder acquire first

    with patch("app.locking.get_settings", return_value=settings):
        with repository_lock(key):
            events.append("waiter_acquired")
    t.join()

    assert events == ["acquired", "released", "waiter_acquired"]


def test_lock_disabled_never_blocks() -> None:
    key = f"test-{uuid.uuid4().hex}"
    settings = _settings(reliability_lock_enabled=False)

    with patch("app.locking.get_settings", return_value=settings):
        with repository_lock(key):
            with repository_lock(key):
                pass  # would deadlock/raise if the lock were actually held
