from unittest.mock import MagicMock

from app.github.client import GitHubClient


def _client_with_mocked_transport() -> tuple[GitHubClient, MagicMock]:
    client = GitHubClient("test-token")
    transport = MagicMock()
    client._client = transport
    return client, transport


def test_get_commit_tree_sha_reads_commit_tree() -> None:
    client, transport = _client_with_mocked_transport()
    transport.get.return_value.json.return_value = {"tree": {"sha": "tree-sha-1"}}

    result = client.get_commit_tree_sha("acme", "widgets", "commit-sha-1")

    transport.get.assert_called_once_with("/repos/acme/widgets/git/commits/commit-sha-1")
    assert result == "tree-sha-1"


def test_create_blob_sends_utf8_content() -> None:
    client, transport = _client_with_mocked_transport()
    transport.post.return_value.json.return_value = {"sha": "blob-sha-1"}

    result = client.create_blob("acme", "widgets", "print('hi')\n")

    args, kwargs = transport.post.call_args
    assert args[0] == "/repos/acme/widgets/git/blobs"
    assert kwargs["json"] == {"content": "print('hi')\n", "encoding": "utf-8"}
    assert result == "blob-sha-1"


def test_create_tree_replaces_one_path_on_base_tree() -> None:
    client, transport = _client_with_mocked_transport()
    transport.post.return_value.json.return_value = {"sha": "tree-sha-2"}

    result = client.create_tree("acme", "widgets", "base-tree-1", "app/foo.py", "blob-sha-1")

    args, kwargs = transport.post.call_args
    assert args[0] == "/repos/acme/widgets/git/trees"
    assert kwargs["json"] == {
        "base_tree": "base-tree-1",
        "tree": [{"path": "app/foo.py", "mode": "100644", "type": "blob", "sha": "blob-sha-1"}],
    }
    assert result == "tree-sha-2"


def test_create_commit_sends_single_parent() -> None:
    client, transport = _client_with_mocked_transport()
    transport.post.return_value.json.return_value = {"sha": "commit-sha-2"}

    result = client.create_commit(
        "acme", "widgets", "fix: thing", "tree-sha-2", "commit-sha-1"
    )

    args, kwargs = transport.post.call_args
    assert args[0] == "/repos/acme/widgets/git/commits"
    assert kwargs["json"] == {
        "message": "fix: thing", "tree": "tree-sha-2", "parents": ["commit-sha-1"]
    }
    assert result == "commit-sha-2"


def test_create_ref_creates_branch_at_sha() -> None:
    client, transport = _client_with_mocked_transport()
    transport.post.return_value.json.return_value = {"ref": "refs/heads/my-fix"}

    client.create_ref("acme", "widgets", "refs/heads/my-fix", "commit-sha-2")

    args, kwargs = transport.post.call_args
    assert args[0] == "/repos/acme/widgets/git/refs"
    assert kwargs["json"] == {"ref": "refs/heads/my-fix", "sha": "commit-sha-2"}
