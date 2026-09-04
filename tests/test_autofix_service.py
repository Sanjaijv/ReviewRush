from contextlib import contextmanager
from unittest.mock import patch

import pytest
from sqlalchemy import text

from app.ai.model import ModelResponse
from app.analysis.workspace import Workspace
from app.autofix.service import attempt_fix
from app.config import Settings
from app.models import (
    AIFinding,
    AIReview,
    AutoFixAttempt,
    DiffSnapshot,
    Installation,
    PullRequest,
    Repository,
)
from app.repo_config import AutoFixConfig, RepoConfig


@pytest.fixture(autouse=True)
def _cleanup(db_session):
    yield
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
    def __init__(self) -> None:
        self.calls: list[tuple] = []

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
