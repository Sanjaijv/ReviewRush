from contextlib import contextmanager
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import text

from app.ai.model import ModelResponse
from app.analysis.workspace import Workspace
from app.autofix.service import (
    _find_pull_request,
    apply_manual_fix,
    attempt_fix,
    manual_fix_eligible,
)
from app.config import Settings
from app.models import (
    AIFinding,
    AIReview,
    AutoFixAttempt,
    DiffSnapshot,
    Installation,
    PullRequest,
    Repository,
    ReviewComment,
)
from app.repo_config import AutoFixConfig, RepoConfig


def test_find_pull_request_prefers_pull_request_id_fk_over_head_sha() -> None:
    """A stale `PullRequest.head_sha` (already moved on to a newer push
    while this snapshot's slow autofix job was still running) must not stop
    `_find_pull_request` from finding the PR when `pull_request_id` was
    stamped at snapshot creation time - that FK is what this test guards.
    """
    db = MagicMock()
    matched = PullRequest(
        id=9, repository_id=1, github_pr_number=2, head_branch="foundations",
        base_branch="main", head_sha="a-much-newer-sha", state="open",
    )
    db.get.return_value = matched
    diff_snapshot = DiffSnapshot(
        id=1, repository_id=1, head_sha="the-old-sha-this-snapshot-was-built-for",
        base_sha="base", pull_request_id=9,
    )
    repository = Repository(id=1, owner="acme", name="widgets", full_name="acme/widgets")

    result = _find_pull_request(db, repository, diff_snapshot)

    assert result is matched
    db.get.assert_called_once_with(PullRequest, 9)
    db.query.assert_not_called()


def test_find_pull_request_falls_back_to_head_sha_match_when_fk_missing() -> None:
    db = MagicMock()
    matched = PullRequest(
        id=9, repository_id=1, github_pr_number=2, head_branch="foundations",
        base_branch="main", head_sha="sha1", state="open",
    )
    db.query.return_value.filter_by.return_value.one_or_none.return_value = matched
    diff_snapshot = DiffSnapshot(
        id=1, repository_id=1, head_sha="sha1", base_sha="base", pull_request_id=None,
    )
    repository = Repository(id=1, owner="acme", name="widgets", full_name="acme/widgets")

    result = _find_pull_request(db, repository, diff_snapshot)

    assert result is matched
    db.get.assert_not_called()


def _finding(**overrides) -> AIFinding:
    defaults = dict(
        id=1, file="app.py", start_line=2, end_line=2, severity="low",
        category="maintainability", title="t", evidence="e",
    )
    defaults.update(overrides)
    return AIFinding(**defaults)


def _repo_config(*, enabled=True, maximum_severity="low") -> RepoConfig:
    return RepoConfig(auto_fix=AutoFixConfig(enabled=enabled, maximum_severity=maximum_severity))


def test_manual_fix_eligible_false_when_autofix_globally_disabled() -> None:
    finding = _finding(category="security", severity="high")
    assert manual_fix_eligible(finding, _repo_config(), Settings(autofix_enabled=False)) is False


def test_manual_fix_eligible_false_when_repo_has_not_opted_in() -> None:
    finding = _finding(category="security", severity="high")
    settings = Settings(autofix_enabled=True)
    assert manual_fix_eligible(finding, _repo_config(enabled=False), settings) is False


def test_manual_fix_eligible_false_for_missing_tests_category() -> None:
    # Structurally excluded either way - needs a new file, not a line-range edit.
    finding = _finding(category="missing_tests", severity="high")
    settings = Settings(autofix_enabled=True)
    assert manual_fix_eligible(finding, _repo_config(), settings) is False


def test_manual_fix_eligible_true_for_security_regardless_of_severity() -> None:
    finding = _finding(category="security", severity="low")
    settings = Settings(autofix_enabled=True)
    assert manual_fix_eligible(finding, _repo_config(), settings) is True


def test_manual_fix_eligible_true_when_severity_above_ceiling() -> None:
    finding = _finding(category="maintainability", severity="high")
    settings = Settings(autofix_enabled=True)
    assert manual_fix_eligible(finding, _repo_config(maximum_severity="low"), settings) is True


def test_manual_fix_eligible_false_when_already_auto_eligible() -> None:
    # The whole point of the checkbox is findings automatic auto-fix would
    # never attempt on its own - a finding it *would* attempt gets no
    # checkbox, it's either already handled or about to be.
    finding = _finding(category="maintainability", severity="low")
    settings = Settings(autofix_enabled=True)
    assert manual_fix_eligible(finding, _repo_config(maximum_severity="low"), settings) is False


@pytest.fixture(autouse=True)
def _cleanup(db_session):
    yield
    db_session.execute(text("DELETE FROM review_comments"))
    db_session.execute(text("DELETE FROM auto_fix_attempts"))
    db_session.execute(text("DELETE FROM audit_events"))
    db_session.execute(text("DELETE FROM ai_findings"))
    db_session.execute(text("DELETE FROM ai_reviews"))
    db_session.execute(text("DELETE FROM pull_requests"))
    db_session.execute(text("DELETE FROM diff_snapshots"))
    db_session.execute(text("DELETE FROM repositories"))
    db_session.execute(text("DELETE FROM organization_members"))
    db_session.execute(text("DELETE FROM organizations"))
    db_session.execute(text("DELETE FROM installations"))
    db_session.commit()


class _FakeModel:
    def __init__(self, response: ModelResponse) -> None:
        self._response = response
        self.calls: list[dict] = []

    def generate(self, *, system, messages, response_schema=None):
        self.calls.append({"system": system, "messages": messages})
        return self._response


class _FakeGitHubClient:
    def __init__(
        self, *, live_file_content: str | None = None, live_head_sha: str = "sha1"
    ) -> None:
        self.calls: list[tuple] = []
        self._live_file_content = live_file_content
        self._live_head_sha = live_head_sha
        self.updated_comments: list[tuple[int, str]] = []

    def get_commit_tree_sha(self, owner, repo, commit_sha):
        self.calls.append(("get_commit_tree_sha", owner, repo, commit_sha))
        return "base-tree-sha"

    def create_blob(self, owner, repo, content):
        self.calls.append(("create_blob", owner, repo, content))
        return "blob-sha"

    def create_tree(self, owner, repo, base_tree, path, blob_sha):
        self.calls.append(("create_tree", owner, repo, base_tree, path, blob_sha))
        return "new-tree-sha"

    def create_commit(self, owner, repo, message, tree, parent):
        self.calls.append(("create_commit", owner, repo, message, tree, parent))
        return "new-commit-sha"

    def create_ref(self, owner, repo, ref, sha):
        self.calls.append(("create_ref", owner, repo, ref, sha))

    def create_pull_request(self, owner, repo, title, body, head, base):
        self.calls.append(("create_pull_request", owner, repo, title, body, head, base))
        return {"number": 99, "html_url": "https://github.com/acme/widgets/pull/99"}

    def get_ref_sha(self, owner, repo, branch):
        self.calls.append(("get_ref_sha", owner, repo, branch))
        return self._live_head_sha

    def get_file_contents(self, owner, repo, path, ref):
        self.calls.append(("get_file_contents", owner, repo, path, ref))
        return self._live_file_content

    def update_branch_ref(self, owner, repo, branch, sha):
        self.calls.append(("update_branch_ref", owner, repo, branch, sha))

    def update_review_comment(self, owner, repo, comment_id, body):
        self.calls.append(("update_review_comment", owner, repo, comment_id, body))
        self.updated_comments.append((comment_id, body))


def _response(content) -> ModelResponse:
    return ModelResponse(
        content=content, raw_text=str(content), prompt_tokens=10, completion_tokens=5,
        latency_ms=1,
    )


def _setup(db_session) -> tuple[Repository, DiffSnapshot, AIFinding]:
    installation = Installation(
        github_installation_id=6001, account_login="acme", account_type="Organization"
    )
    db_session.add(installation)
    db_session.commit()

    repository = Repository(
        installation_id=installation.id, github_repo_id=1, owner="acme", name="widgets",
        full_name="acme/widgets",
    )
    db_session.add(repository)
    db_session.commit()

    snapshot = DiffSnapshot(repository_id=repository.id, head_sha="sha1", base_sha="mainsha")
    db_session.add(snapshot)
    db_session.commit()

    db_session.add(
        PullRequest(
            repository_id=repository.id, github_pr_number=42, head_branch="feature-x",
            base_branch="main", head_sha="sha1",
        )
    )
    db_session.commit()

    review = AIReview(
        repository_id=repository.id, diff_snapshot_id=snapshot.id, status="completed",
        decision="comment", risk="low", confidence=0.9,
    )
    review.findings = [
        AIFinding(
            repository_id=repository.id, file="app.py", start_line=2, end_line=2,
            severity="low", category="maintainability", title="nit", evidence="evidence text",
        )
    ]
    db_session.add(review)
    db_session.commit()
    return repository, snapshot, review.findings[0]


def _config() -> RepoConfig:
    return RepoConfig(auto_fix=AutoFixConfig(enabled=True, maximum_severity="low"))


def _fake_workspace(tmp_path):
    """Returns a workspace_for-shaped callable backed by a real tmp_path
    instead of a downloaded tarball, so attempt_fix's file read/write and
    path-safety checks run against real files.
    """
    (tmp_path / "app.py").write_text("line1\noriginal line to fix\nline3\n")

    @contextmanager
    def _factory(client, repository, head_sha):
        yield Workspace(run_subdir="fake-run-subdir", host_path=tmp_path)

    return _factory


def test_attempt_fix_opens_pr_when_verification_passes(db_session, tmp_path) -> None:
    repository, snapshot, finding = _setup(db_session)
    fake_client = _FakeGitHubClient()
    model = _FakeModel(
        _response(
            {"applicable": True, "replacement_lines": ["fixed line"], "explanation": "why"}
        )
    )

    with patch("app.autofix.service.workspace_for", _fake_workspace(tmp_path)), \
         patch("app.autofix.service.build_review_model", return_value=model), \
         patch("app.autofix.service._verify_fix", return_value=None):
        attempt = attempt_fix(
            db_session, fake_client, repository, snapshot, finding, _config(), Settings()
        )

    assert attempt.status == "pr_opened"
    assert attempt.pull_request_number == 99
    assert attempt.branch_name is not None and attempt.branch_name.startswith("reviewrush-fix/")

    push_calls = [c[0] for c in fake_client.calls]
    assert push_calls == [
        "get_commit_tree_sha", "create_blob", "create_tree", "create_commit",
        "create_ref", "create_pull_request",
    ]
    pr_call = fake_client.calls[-1]
    assert pr_call[5] == attempt.branch_name  # head
    assert pr_call[6] == "feature-x"  # base = original PR's own head branch

    # persisted exactly once, idempotent row
    rows = db_session.query(AutoFixAttempt).filter_by(ai_finding_id=finding.id).all()
    assert len(rows) == 1


def test_attempt_fix_records_verification_failure_without_pushing(db_session, tmp_path) -> None:
    repository, snapshot, finding = _setup(db_session)
    fake_client = _FakeGitHubClient()
    model = _FakeModel(
        _response(
            {"applicable": True, "replacement_lines": ["fixed line"], "explanation": "why"}
        )
    )

    with patch("app.autofix.service.workspace_for", _fake_workspace(tmp_path)), \
         patch("app.autofix.service.build_review_model", return_value=model), \
         patch("app.autofix.service._verify_fix", return_value="gitleaks"):
        attempt = attempt_fix(
            db_session, fake_client, repository, snapshot, finding, _config(), Settings()
        )

    assert attempt.status == "verification_failed"
    assert "gitleaks" in (attempt.error_message or "")
    assert fake_client.calls == []


def test_attempt_fix_records_not_applicable_without_verifying(db_session, tmp_path) -> None:
    repository, snapshot, finding = _setup(db_session)
    fake_client = _FakeGitHubClient()
    model = _FakeModel(
        _response({"applicable": False, "replacement_lines": [], "explanation": "too risky"})
    )

    with patch("app.autofix.service.workspace_for", _fake_workspace(tmp_path)), \
         patch("app.autofix.service.build_review_model", return_value=model), \
         patch("app.autofix.service._verify_fix") as verify_mock:
        attempt = attempt_fix(
            db_session, fake_client, repository, snapshot, finding, _config(), Settings()
        )

    assert attempt.status == "not_applicable"
    verify_mock.assert_not_called()
    assert fake_client.calls == []


def test_attempt_fix_records_invalid_output(db_session, tmp_path) -> None:
    repository, snapshot, finding = _setup(db_session)
    fake_client = _FakeGitHubClient()
    model = _FakeModel(_response({"not": "the right shape"}))

    with patch("app.autofix.service.workspace_for", _fake_workspace(tmp_path)), \
         patch("app.autofix.service.build_review_model", return_value=model):
        attempt = attempt_fix(
            db_session, fake_client, repository, snapshot, finding, _config(), Settings()
        )

    assert attempt.status == "invalid_output"
    assert fake_client.calls == []


def _add_security_finding(db_session, repository, snapshot) -> AIFinding:
    """A finding automatic auto-fix would never attempt (category=security)
    - exactly what `manual_fix_eligible` is meant to offer the checkbox for.
    """
    ai_review = db_session.query(AIReview).filter_by(diff_snapshot_id=snapshot.id).one()
    finding = AIFinding(
        repository_id=repository.id, file="app.py", start_line=2, end_line=2,
        severity="high", category="security", title="SQL injection", evidence="evidence text",
    )
    ai_review.findings.append(finding)
    db_session.commit()
    return finding


def _add_review_comment(db_session, repository, snapshot, finding) -> ReviewComment:
    pull_request = db_session.query(PullRequest).filter_by(repository_id=repository.id).one()
    comment = ReviewComment(
        repository_id=repository.id, pull_request_id=pull_request.id,
        diff_snapshot_id=snapshot.id, ai_finding_id=finding.id, kind="inline",
        fingerprint="fp1", github_comment_id=555, head_sha=snapshot.head_sha,
    )
    db_session.add(comment)
    db_session.commit()
    return comment


def test_apply_manual_fix_commits_directly_to_branch_when_verification_passes(
    db_session, tmp_path
) -> None:
    repository, snapshot, _ = _setup(db_session)
    finding = _add_security_finding(db_session, repository, snapshot)
    review_comment = _add_review_comment(db_session, repository, snapshot, finding)
    fake_client = _FakeGitHubClient(live_file_content="line1\noriginal line to fix\nline3\n")
    model = _FakeModel(
        _response({"applicable": True, "replacement_lines": ["fixed line"], "explanation": "why"})
    )

    with patch("app.autofix.service.workspace_for", _fake_workspace(tmp_path)), \
         patch("app.autofix.service.build_review_model", return_value=model), \
         patch("app.autofix.service._verify_fix", return_value=None):
        attempt = apply_manual_fix(
            db_session, fake_client, repository, snapshot, finding, _config(), Settings(),
            actor_login="octocat", review_comment=review_comment,
            current_comment_body="- [x] Apply this fix",
        )

    assert attempt.status == "committed"
    assert attempt.trigger == "manual"
    assert attempt.actor_login == "octocat"
    assert attempt.commit_sha == "new-commit-sha"

    push_calls = [c[0] for c in fake_client.calls]
    assert "create_ref" not in push_calls
    assert "create_pull_request" not in push_calls
    assert "update_branch_ref" in push_calls
    update_call = next(c for c in fake_client.calls if c[0] == "update_branch_ref")
    assert update_call[3] == "feature-x"  # the PR's own head branch, not a new one

    assert len(fake_client.updated_comments) == 1
    _, updated_body = fake_client.updated_comments[0]
    assert "Applied" in updated_body


def test_apply_manual_fix_refuses_when_target_file_changed_since_review(
    db_session, tmp_path
) -> None:
    repository, snapshot, _ = _setup(db_session)
    finding = _add_security_finding(db_session, repository, snapshot)
    review_comment = _add_review_comment(db_session, repository, snapshot, finding)
    # Live content on the branch no longer matches what was read at review
    # time - must refuse rather than blindly overwrite it.
    fake_client = _FakeGitHubClient(live_file_content="someone else already changed this file\n")
    model = _FakeModel(
        _response({"applicable": True, "replacement_lines": ["fixed line"], "explanation": "why"})
    )

    with patch("app.autofix.service.workspace_for", _fake_workspace(tmp_path)), \
         patch("app.autofix.service.build_review_model", return_value=model), \
         patch("app.autofix.service._verify_fix", return_value=None):
        attempt = apply_manual_fix(
            db_session, fake_client, repository, snapshot, finding, _config(), Settings(),
            actor_login="octocat", review_comment=review_comment,
            current_comment_body="- [x] Apply this fix",
        )

    assert attempt.status == "stale_target"
    push_calls = [c[0] for c in fake_client.calls]
    assert "update_branch_ref" not in push_calls
    assert "create_commit" not in push_calls

    assert len(fake_client.updated_comments) == 1
    _, updated_body = fake_client.updated_comments[0]
    assert "Fix attempt failed" in updated_body


def test_apply_manual_fix_is_one_shot_and_does_not_retry_an_existing_attempt(
    db_session, tmp_path
) -> None:
    repository, snapshot, _ = _setup(db_session)
    finding = _add_security_finding(db_session, repository, snapshot)
    existing = AutoFixAttempt(
        repository_id=repository.id, diff_snapshot_id=snapshot.id, ai_finding_id=finding.id,
        trigger="manual", status="error", error_message="first attempt failed",
    )
    db_session.add(existing)
    db_session.commit()

    fake_client = _FakeGitHubClient()
    model = _FakeModel(_response({"applicable": True, "replacement_lines": [], "explanation": ""}))

    with patch("app.autofix.service.workspace_for", _fake_workspace(tmp_path)), \
         patch("app.autofix.service.build_review_model", return_value=model):
        attempt = apply_manual_fix(
            db_session, fake_client, repository, snapshot, finding, _config(), Settings(),
            actor_login="octocat",
        )

    assert attempt.id == existing.id
    assert attempt.status == "error"
    assert fake_client.calls == []
    assert model.calls == []
