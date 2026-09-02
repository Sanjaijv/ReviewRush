from unittest.mock import MagicMock

import httpx
import pytest

from app.github.pr_automation import (
    AUTOMATED_SECTION_END,
    AUTOMATED_SECTION_START,
    build_title,
    merge_pr_body,
    render_automated_section,
    resolve_branches,
    sync_pull_request_for_push,
)
from app.repo_config import RepoConfig


class _FakeRepository:
    def __init__(self, owner="acme", name="widgets", source_branch=None, target_branch=None):
        self.id = 1
        self.owner = owner
        self.name = name
        self.full_name = f"{owner}/{name}"
        self.source_branch = source_branch
        self.target_branch = target_branch


def test_resolve_branches_prefers_config_over_repository_over_default() -> None:
    repository = _FakeRepository(source_branch="dev", target_branch="release")
    config = RepoConfig()
    assert resolve_branches(repository, config) == ("dev", "release")

    config.branches.source = "feature-x"
    config.branches.target = "staging"
    assert resolve_branches(repository, config) == ("feature-x", "staging")

    bare_repository = _FakeRepository()
    assert resolve_branches(bare_repository, RepoConfig()) == ("foundations", "main")


def test_build_title_single_commit_uses_commit_message() -> None:
    commits = [{"message": "fix: correct off-by-one error\n\nlonger body"}]
    assert build_title(commits, "foundations", "main") == "fix: correct off-by-one error"


def test_build_title_multiple_commits() -> None:
    commits = [{"message": "a"}, {"message": "b"}]
    assert build_title(commits, "foundations", "main") == "2 commits from foundations"


def test_build_title_no_commits() -> None:
    assert build_title([], "foundations", "main") == "Sync foundations into main"


def test_render_automated_section_includes_markers_and_commits() -> None:
    commits = [{"id": "abc1234567", "message": "add feature", "author": {"username": "dev"}}]
    section = render_automated_section(commits, "abc1234567", "foundations", "main")
    assert section.startswith(AUTOMATED_SECTION_START)
    assert section.endswith(AUTOMATED_SECTION_END)
    assert "`abc1234` add feature (@dev)" in section
    assert "Head: `abc1234567`" in section


def test_merge_pr_body_replaces_existing_automated_section() -> None:
    existing = (
        f"Human intro.\n\n{AUTOMATED_SECTION_START}\nold content\n{AUTOMATED_SECTION_END}"
        "\n\nHuman notes below."
    )
    new_section = f"{AUTOMATED_SECTION_START}\nnew content\n{AUTOMATED_SECTION_END}"
    merged = merge_pr_body(existing, new_section)
    assert "old content" not in merged
    assert "new content" in merged
    assert "Human intro." in merged
    assert "Human notes below." in merged


def test_merge_pr_body_appends_when_no_markers_present() -> None:
    existing = "A human wrote this PR description."
    new_section = f"{AUTOMATED_SECTION_START}\ncontent\n{AUTOMATED_SECTION_END}"
    merged = merge_pr_body(existing, new_section)
    assert merged.startswith("A human wrote this PR description.")
    assert new_section in merged


def test_merge_pr_body_with_no_existing_body() -> None:
    new_section = f"{AUTOMATED_SECTION_START}\ncontent\n{AUTOMATED_SECTION_END}"
    assert merge_pr_body(None, new_section) == new_section
    assert merge_pr_body("", new_section) == new_section


def test_sync_skips_when_push_is_superseded() -> None:
    db = MagicMock()
    client = MagicMock()
    client.get_ref_sha.return_value = "newer-sha"
    repository = _FakeRepository()

    sync_pull_request_for_push(
        db=db,
        client=client,
        repository=repository,
        source_branch="foundations",
        target_branch="main",
        head_sha="stale-sha",
        commits=[],
    )

    client.list_open_pull_requests.assert_not_called()
    db.add.assert_not_called()


def test_sync_creates_pr_when_none_open() -> None:
    db = MagicMock()
    db.query.return_value.filter_by.return_value.one_or_none.return_value = None
    client = MagicMock()
    client.get_ref_sha.return_value = "sha123"
    client.list_open_pull_requests.return_value = []
    client.create_pull_request.return_value = {
        "number": 42,
        "state": "open",
        "base": {"sha": "base-sha"},
    }
    repository = _FakeRepository()

    sync_pull_request_for_push(
        db=db,
        client=client,
        repository=repository,
        source_branch="foundations",
        target_branch="main",
        head_sha="sha123",
        commits=[{"id": "sha123", "message": "hello"}],
    )

    client.create_pull_request.assert_called_once()
    db.add.assert_called_once()
    db.commit.assert_called_once()


def test_sync_updates_existing_pr_without_creating() -> None:
    db = MagicMock()
    db.query.return_value.filter_by.return_value.one_or_none.return_value = None
    client = MagicMock()
    client.get_ref_sha.return_value = "sha123"
    client.list_open_pull_requests.return_value = [
        {"number": 7, "body": "Human text.", "state": "open", "base": {"sha": "base-sha"}}
    ]
    client.update_pull_request.return_value = {
        "number": 7,
        "state": "open",
        "base": {"sha": "base-sha"},
    }
    repository = _FakeRepository()

    sync_pull_request_for_push(
        db=db,
        client=client,
        repository=repository,
        source_branch="foundations",
        target_branch="main",
        head_sha="sha123",
        commits=[],
    )

    client.create_pull_request.assert_not_called()
    client.update_pull_request.assert_called_once()
    updated_body = client.update_pull_request.call_args.kwargs["body"]
    assert "Human text." in updated_body
    assert AUTOMATED_SECTION_START in updated_body


def test_sync_swallows_422_when_nothing_to_compare() -> None:
    db = MagicMock()
    client = MagicMock()
    client.get_ref_sha.return_value = "sha123"
    client.list_open_pull_requests.return_value = []
    request = httpx.Request("POST", "https://api.github.com/repos/acme/widgets/pulls")
    response = httpx.Response(422, request=request)
    client.create_pull_request.side_effect = httpx.HTTPStatusError(
        "unprocessable", request=request, response=response
    )
    repository = _FakeRepository()

    sync_pull_request_for_push(
        db=db,
        client=client,
        repository=repository,
        source_branch="foundations",
        target_branch="main",
        head_sha="sha123",
        commits=[],
    )

    db.add.assert_not_called()


def test_sync_reraises_non_422_errors() -> None:
    db = MagicMock()
    client = MagicMock()
    client.get_ref_sha.return_value = "sha123"
    client.list_open_pull_requests.return_value = []
    request = httpx.Request("POST", "https://api.github.com/repos/acme/widgets/pulls")
    response = httpx.Response(500, request=request)
    client.create_pull_request.side_effect = httpx.HTTPStatusError(
        "server error", request=request, response=response
    )
    repository = _FakeRepository()

    with pytest.raises(httpx.HTTPStatusError):
        sync_pull_request_for_push(
            db=db,
            client=client,
            repository=repository,
            source_branch="foundations",
            target_branch="main",
            head_sha="sha123",
            commits=[],
        )
