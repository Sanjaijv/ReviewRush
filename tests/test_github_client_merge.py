from unittest.mock import MagicMock

from app.github.client import GitHubClient


def _client_with_mocked_transport() -> tuple[GitHubClient, MagicMock]:
    client = GitHubClient("test-token")
    transport = MagicMock()
    client._client = transport
    return client, transport


def test_get_pull_request_fetches_by_number() -> None:
    client, transport = _client_with_mocked_transport()
    transport.get.return_value.json.return_value = {"number": 7, "head": {"sha": "sha1"}}

    result = client.get_pull_request("acme", "widgets", 7)

    transport.get.assert_called_once_with("/repos/acme/widgets/pulls/7")
    assert result["number"] == 7


def test_list_check_runs_for_ref_hits_commit_check_runs_endpoint() -> None:
    client, transport = _client_with_mocked_transport()
    transport.get.return_value.json.return_value = {"check_runs": []}

    client.list_check_runs_for_ref("acme", "widgets", "sha1")

    args, kwargs = transport.get.call_args
    assert args[0] == "/repos/acme/widgets/commits/sha1/check-runs"
    assert kwargs["params"]["per_page"] == 100


def test_list_reviews_returns_list() -> None:
    client, transport = _client_with_mocked_transport()
    transport.get.return_value.json.return_value = [{"state": "APPROVED"}]

    result = client.list_reviews("acme", "widgets", 7)

    assert result == [{"state": "APPROVED"}]


def test_merge_pull_request_sends_sha_and_method() -> None:
    client, transport = _client_with_mocked_transport()
    transport.put.return_value.json.return_value = {"merged": True, "sha": "mergesha"}

    result = client.merge_pull_request("acme", "widgets", 7, sha="sha1", merge_method="squash")

    args, kwargs = transport.put.call_args
    assert args[0] == "/repos/acme/widgets/pulls/7/merge"
    assert kwargs["json"] == {"sha": "sha1", "merge_method": "squash"}
    assert result == {"merged": True, "sha": "mergesha"}
