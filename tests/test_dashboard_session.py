import time

import jwt
import pytest

from app.config import Settings
from app.dashboard.session import InvalidSession, create_session_token, verify_session_token


def _settings(**overrides) -> Settings:
    overrides.setdefault("dashboard_session_secret", "test-secret")
    return Settings(**overrides)


def test_roundtrip() -> None:
    settings = _settings()
    token = create_session_token(
        settings, github_user_id=42, login="octocat", avatar_url="a.png", installation_ids=[1, 2]
    )

    payload = verify_session_token(settings, token)

    assert int(payload["sub"]) == 42
    assert payload["login"] == "octocat"
    assert payload["installation_ids"] == [1, 2]


def test_missing_secret_raises_on_create() -> None:
    settings = _settings(dashboard_session_secret="")
    with pytest.raises(RuntimeError):
        create_session_token(
            settings, github_user_id=1, login="x", avatar_url="", installation_ids=[]
        )


def test_missing_secret_raises_on_verify() -> None:
    settings = _settings(dashboard_session_secret="")
    with pytest.raises(InvalidSession):
        verify_session_token(settings, "whatever")


def test_expired_token_is_rejected() -> None:
    settings = _settings()
    now = int(time.time())
    expired_payload = {
        "sub": 1,
        "login": "x",
        "avatar_url": "",
        "installation_ids": [],
        "iat": now - 7200,
        "exp": now - 3600,
    }
    token = jwt.encode(expired_payload, settings.dashboard_session_secret, algorithm="HS256")

    with pytest.raises(InvalidSession):
        verify_session_token(settings, token)


def test_token_signed_with_different_secret_is_rejected() -> None:
    settings = _settings()
    forged = jwt.encode(
        {"sub": 1, "login": "x", "avatar_url": "", "installation_ids": [], "exp": time.time() + 60},
        "someone-elses-secret",
        algorithm="HS256",
    )

    with pytest.raises(InvalidSession):
        verify_session_token(settings, forged)
