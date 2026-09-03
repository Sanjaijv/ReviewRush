from unittest.mock import MagicMock, patch

import httpx
import pytest

from app.config import Settings
from app.dashboard.oauth import (
    build_authorize_url,
    exchange_code_for_token,
    fetch_accessible_installation_ids,
    fetch_authenticated_user,
    new_state,
)


def _settings(**overrides) -> Settings:
    return Settings(
        github_oauth_client_id="client-id", github_oauth_client_secret="client-secret", **overrides
    )


def test_new_state_is_unique_and_url_safe() -> None:
    a, b = new_state(), new_state()
    assert a != b
    assert len(a) > 20


def test_build_authorize_url_includes_client_id_and_state() -> None:
    url = build_authorize_url(_settings(), redirect_uri="https://x/cb", state="s1")
    assert "client_id=client-id" in url
    assert "state=s1" in url
    assert url.startswith("https://github.com/login/oauth/authorize")


def test_build_authorize_url_requires_client_id() -> None:
    with pytest.raises(RuntimeError):
        build_authorize_url(Settings(), redirect_uri="https://x/cb", state="s1")


def test_exchange_code_for_token_requires_credentials() -> None:
    with pytest.raises(RuntimeError):
        exchange_code_for_token(Settings(), code="c", redirect_uri="https://x/cb")


def test_exchange_code_for_token_returns_access_token() -> None:
    response = MagicMock()
    response.json.return_value = {"access_token": "user-token-123"}
    response.raise_for_status.return_value = None

    with patch("httpx.post", return_value=response) as post:
        token = exchange_code_for_token(_settings(), code="c", redirect_uri="https://x/cb")

    assert token == "user-token-123"
    post.assert_called_once()


def test_exchange_code_for_token_raises_on_error_body() -> None:
    response = MagicMock()
    response.json.return_value = {"error": "bad_verification_code"}
    response.raise_for_status.return_value = None

    with patch("httpx.post", return_value=response):
        with pytest.raises(RuntimeError):
            exchange_code_for_token(_settings(), code="c", redirect_uri="https://x/cb")


def test_fetch_authenticated_user_parses_response() -> None:
    response = MagicMock()
    response.json.return_value = {"id": 7, "login": "octocat", "avatar_url": "a.png"}
    response.raise_for_status.return_value = None

    with patch("httpx.get", return_value=response):
        user = fetch_authenticated_user("token")

    assert user.id == 7
    assert user.login == "octocat"


def test_fetch_accessible_installation_ids_paginates() -> None:
    first_response = httpx.Response(
        200,
        json={"installations": [{"id": 1}, {"id": 2}]},
        headers={"Link": '<https://api.github.com/user/installations?page=2>; rel="next"'},
        request=httpx.Request("GET", "https://api.github.com/user/installations"),
    )
    second_response = httpx.Response(
        200,
        json={"installations": [{"id": 3}]},
        request=httpx.Request("GET", "https://api.github.com/user/installations"),
    )

    with patch.object(httpx.Client, "get", side_effect=[first_response, second_response]):
        ids = fetch_accessible_installation_ids("token")

    assert ids == [1, 2, 3]
