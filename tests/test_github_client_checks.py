from unittest.mock import MagicMock

from app.github.client import GitHubClient


def _client_with_mocked_transport() -> tuple[GitHubClient, MagicMock]:
    client = GitHubClient("test-token")
    transport = MagicMock()
    client._client = transport
    return client, transport


def test_create_check_run_defaults_to_in_progress() -> None:
    client, transport = _client_with_mocked_transport()
    transport.post.return_value.json.return_value = {"id": 1}

    client.create_check_run("acme", "widgets", "ReviewRush", "sha1")

    _, kwargs = transport.post.call_args
    assert kwargs["json"]["status"] == "in_progress"
    assert "conclusion" not in kwargs["json"]


def test_create_check_run_with_conclusion_creates_completed_run() -> None:
    client, transport = _client_with_mocked_transport()
    transport.post.return_value.json.return_value = {"id": 1}

    client.create_check_run(
        "acme", "widgets", "ReviewRush", "sha1", conclusion="success", title="t", summary="s"
    )

    _, kwargs = transport.post.call_args
    assert kwargs["json"]["status"] == "completed"
    assert kwargs["json"]["conclusion"] == "success"
    assert kwargs["json"]["output"] == {"title": "t", "summary": "s"}


def test_update_check_run_sends_completed_status() -> None:
    client, transport = _client_with_mocked_transport()
    transport.patch.return_value.json.return_value = {"id": 1}

    client.update_check_run(
        "acme", "widgets", 1, conclusion="failure", title="t", summary="s", text="details"
    )

    _, kwargs = transport.patch.call_args
    assert kwargs["json"]["status"] == "completed"
    assert kwargs["json"]["conclusion"] == "failure"
    assert kwargs["json"]["output"]["text"] == "details"


def test_create_review_comment_uses_diff_position() -> None:
    client, transport = _client_with_mocked_transport()
    transport.post.return_value.json.return_value = {"id": 55}

    result = client.create_review_comment(
        "acme", "widgets", 7, commit_id="sha1", path="src/app.py", position=3, body="issue"
    )

    assert result == {"id": 55}
    _, kwargs = transport.post.call_args
    assert kwargs["json"] == {
        "commit_id": "sha1",
        "path": "src/app.py",
        "position": 3,
        "body": "issue",
    }


def test_update_issue_comment_patches_body() -> None:
    client, transport = _client_with_mocked_transport()
    transport.patch.return_value.json.return_value = {"id": 9}

    client.update_issue_comment("acme", "widgets", 9, "new body")

    args, kwargs = transport.patch.call_args
    assert args[0] == "/repos/acme/widgets/issues/comments/9"
    assert kwargs["json"] == {"body": "new body"}
