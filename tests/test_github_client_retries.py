from unittest.mock import MagicMock, patch

import httpx
import pytest

from app.github.client import GitHubClient


def _client_with_mocked_transport() -> tuple[GitHubClient, MagicMock]:
    client = GitHubClient("test-token")
    transport = MagicMock()
    client._client = transport
    return client, transport


def _response(status_code: int, json_body: object = None) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status_code
    resp.headers = {}
    resp.json.return_value = json_body
    if status_code >= 400:
        resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            "error", request=MagicMock(), response=resp
        )
    else:
        resp.raise_for_status.return_value = None
    return resp


@patch("time.sleep", return_value=None)
def test_idempotent_get_retries_transient_status_then_succeeds(_sleep: MagicMock) -> None:
    client, transport = _client_with_mocked_transport()
    transport.get.side_effect = [
        _response(503),
        _response(502),
        _response(200, {"number": 7}),
    ]

    result = client.get_pull_request("acme", "widgets", 7)

    assert result == {"number": 7}
    assert transport.get.call_count == 3


@patch("time.sleep", return_value=None)
def test_idempotent_get_exhausts_retries_and_raises(_sleep: MagicMock) -> None:
    client, transport = _client_with_mocked_transport()
    transport.get.return_value = _response(503)

    with pytest.raises(httpx.HTTPStatusError):
        client.get_pull_request("acme", "widgets", 7)

    # stop_after_attempt(5): exactly 5 attempts, no more.
    assert transport.get.call_count == 5


def test_non_transient_status_is_never_retried() -> None:
    client, transport = _client_with_mocked_transport()
    transport.get.return_value = _response(422)

    with pytest.raises(httpx.HTTPStatusError):
        client.get_pull_request("acme", "widgets", 7)

    assert transport.get.call_count == 1


def test_404_on_get_ref_sha_is_not_an_error() -> None:
    client, transport = _client_with_mocked_transport()
    transport.get.return_value = _response(404)

    result = client.get_ref_sha("acme", "widgets", "missing-branch")

    assert result is None
    assert transport.get.call_count == 1


def test_create_type_post_is_never_retried_by_the_client() -> None:
    """A create-type POST (open a PR, post a comment, create a check run)
    must fail immediately on a transient status rather than being retried
    at the HTTP layer - see app/github/client.py for why: a lost response
    after a successful create could otherwise create a duplicate. The
    Celery task-level retry is what re-runs the whole (idempotent,
    check-before-create) operation instead.
    """
    client, transport = _client_with_mocked_transport()
    transport.post.return_value = _response(503)

    with pytest.raises(httpx.HTTPStatusError):
        client.create_pull_request(
            "acme", "widgets", title="t", body="b", head="feature", base="main"
        )

    assert transport.post.call_count == 1


@patch("time.sleep", return_value=None)
def test_network_error_is_retried_for_idempotent_calls(_sleep: MagicMock) -> None:
    client, transport = _client_with_mocked_transport()
    transport.get.side_effect = [
        httpx.ConnectTimeout("timed out"),
        _response(200, {"number": 7}),
    ]

    result = client.get_pull_request("acme", "widgets", 7)

    assert result == {"number": 7}
    assert transport.get.call_count == 2
