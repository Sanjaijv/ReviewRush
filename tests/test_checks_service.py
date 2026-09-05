from contextlib import contextmanager
from unittest.mock import MagicMock, patch

from app.checks.service import _find_pull_request, run_github_checks_for_snapshot, start_check_run
from app.config import Settings
from app.models import (
    AIFinding,
    AIReview,
    ChangedFile,
    DiffSnapshot,
    PolicyDecision,
    PullRequest,
    ReviewComment,
    ToolRun,
)


class _FakeInstallation:
    github_installation_id = 1


class _FakeRepository:
    def __init__(self) -> None:
        self.id = 1
        self.owner = "acme"
        self.name = "widgets"
        self.full_name = "acme/widgets"
        self.installation = _FakeInstallation()


def _repository() -> _FakeRepository:
    return _FakeRepository()


def _snapshot(**overrides) -> DiffSnapshot:
    defaults = dict(
        id=1,
        repository_id=1,
        head_sha="sha1",
        base_sha="base",
        github_check_run_id=None,
    )
    defaults.update(overrides)
    snapshot = DiffSnapshot(**defaults)
    snapshot.changed_files = [
        ChangedFile(
            new_path="src/app.py",
            old_path="src/app.py",
            status="modified",
            patch="@@ -1,1 +1,2 @@\n line one\n+line two\n",
        )
    ]
    return snapshot


class _FakeQuery:
    def __init__(self, rows_by_filter):
        self._rows_by_filter = rows_by_filter

    def filter_by(self, **kwargs):
        key = tuple(sorted(kwargs.items()))
        return _FakeFiltered(self._rows_by_filter.get(key, self._rows_by_filter.get(None)))


class _FakeFiltered:
    def __init__(self, value):
        self._value = value

    def one_or_none(self):
        return self._value

    def all(self):
        return self._value or []


def _make_db(*, decision, ai_review, tool_runs, pull_request, existing_comments=None):
    existing_comments = existing_comments or {}

    def query_side_effect(model):
        if model is PolicyDecision:
            return _FakeQuery({None: decision})
        if model is AIReview:
            return _FakeQuery({None: ai_review})
        if model is ToolRun:
            return _FakeQuery({None: tool_runs or []})
        if model is PullRequest:
            return _FakeQuery({None: pull_request})
        if model is ReviewComment:
            return _ReviewCommentQuery(existing_comments)
        raise AssertionError(f"unexpected query for {model}")

    db = MagicMock()
    db.query.side_effect = query_side_effect
    return db


class _ReviewCommentQuery:
    def __init__(self, existing_comments: dict[tuple[str, str], ReviewComment]):
        self._existing_comments = existing_comments
        self._filters: dict = {}

    def filter_by(self, **kwargs):
        self._filters = kwargs
        return self

    def one_or_none(self):
        key = (self._filters.get("kind"), self._filters.get("fingerprint"))
        return self._existing_comments.get(key)

    def all(self):
        return [
            row
            for row in self._existing_comments.values()
            if row.kind == self._filters.get("kind") and row.status == self._filters.get("status")
        ]


def _github_client() -> MagicMock:
    client = MagicMock()
    client.__enter__.return_value = client
    client.__exit__.return_value = False
    client.get_file_contents.return_value = None
    client.create_check_run.return_value = {"id": 123}
    client.create_issue_comment.return_value = {"id": 555}
    client.create_review_comment.return_value = {"id": 777}
    return client


@contextmanager
def _patched():
    with (
        patch("app.checks.service.get_settings", return_value=Settings()),
        patch("app.checks.service.get_installation_access_token", return_value="tok"),
    ):
        yield


def test_skips_entirely_when_no_policy_decision() -> None:
    db = _make_db(decision=None, ai_review=None, tool_runs=[], pull_request=None)
    client_cls_patch = patch("app.checks.service.GitHubClient")

    with _patched(), client_cls_patch as client_cls:
        run_github_checks_for_snapshot(db, _repository(), _snapshot())
        client_cls.assert_not_called()


def test_completes_check_run_and_skips_comments_without_pull_request() -> None:
    decision = PolicyDecision(
        id=1, repository_id=1, diff_snapshot_id=1, decision="APPROVE", risk="LOW", reasons=["ok"]
    )
    db = _make_db(decision=decision, ai_review=None, tool_runs=[], pull_request=None)
    client = _github_client()

    with _patched(), patch("app.checks.service.GitHubClient", return_value=client):
        run_github_checks_for_snapshot(db, _repository(), _snapshot(github_check_run_id=999))

    client.update_check_run.assert_called_once()
    _, kwargs = client.update_check_run.call_args
    assert kwargs["conclusion"] == "success"
    client.create_issue_comment.assert_not_called()


def test_posts_summary_and_inline_comment_for_eligible_finding() -> None:
    decision = PolicyDecision(
        id=1,
        repository_id=1,
        diff_snapshot_id=1,
        decision="HUMAN_REVIEW",
        risk="MEDIUM",
        reasons=["protected path"],
    )
    finding = AIFinding(
        id=1,
        ai_review_id=1,
        repository_id=1,
        file="src/app.py",
        start_line=2,
        end_line=2,
        severity="high",
        category="security",
        title="Missing check",
        evidence="...",
    )
    ai_review = AIReview(id=1, repository_id=1, diff_snapshot_id=1, status="completed", summary="s")
    ai_review.findings = [finding]
    pull_request = PullRequest(
        id=1, repository_id=1, github_pr_number=9, head_branch="foundations", base_branch="main"
    )
    db = _make_db(
        decision=decision, ai_review=ai_review, tool_runs=[], pull_request=pull_request
    )
    client = _github_client()

    with _patched(), patch("app.checks.service.GitHubClient", return_value=client):
        run_github_checks_for_snapshot(db, _repository(), _snapshot(github_check_run_id=999))

    client.create_review_comment.assert_called_once()
    _, kwargs = client.create_review_comment.call_args
    assert kwargs["path"] == "src/app.py"
    assert kwargs["position"] == 3  # position of the "+line two" line in the patch

    client.create_issue_comment.assert_called_once()
    args, _ = client.create_issue_comment.call_args
    assert "HUMAN_REVIEW" in args[-1]


def test_low_severity_finding_is_not_posted_inline() -> None:
    decision = PolicyDecision(
        id=1, repository_id=1, diff_snapshot_id=1, decision="APPROVE", risk="LOW", reasons=["ok"]
    )
    finding = AIFinding(
        id=1,
        ai_review_id=1,
        repository_id=1,
        file="src/app.py",
        start_line=2,
        end_line=2,
        severity="low",
        category="maintainability",
        title="Nit",
        evidence="...",
    )
    ai_review = AIReview(id=1, repository_id=1, diff_snapshot_id=1, status="completed", summary="s")
    ai_review.findings = [finding]
    pull_request = PullRequest(
        id=1, repository_id=1, github_pr_number=9, head_branch="foundations", base_branch="main"
    )
    db = _make_db(
        decision=decision, ai_review=ai_review, tool_runs=[], pull_request=pull_request
    )
    client = _github_client()

    with _patched(), patch("app.checks.service.GitHubClient", return_value=client):
        run_github_checks_for_snapshot(db, _repository(), _snapshot(github_check_run_id=999))

    client.create_review_comment.assert_not_called()
    client.create_issue_comment.assert_called_once()


def test_rerun_reuses_existing_summary_comment_instead_of_creating_new() -> None:
    decision = PolicyDecision(
        id=1, repository_id=1, diff_snapshot_id=1, decision="APPROVE", risk="LOW", reasons=["ok"]
    )
    ai_review = AIReview(id=1, repository_id=1, diff_snapshot_id=1, status="completed", summary="s")
    ai_review.findings = []
    pull_request = PullRequest(
        id=1, repository_id=1, github_pr_number=9, head_branch="foundations", base_branch="main"
    )
    existing_summary = ReviewComment(
        id=1,
        repository_id=1,
        pull_request_id=1,
        diff_snapshot_id=0,
        kind="summary",
        fingerprint="summary",
        github_comment_id=555,
        status="posted",
        head_sha="sha0",
    )
    db = _make_db(
        decision=decision,
        ai_review=ai_review,
        tool_runs=[],
        pull_request=pull_request,
        existing_comments={("summary", "summary"): existing_summary},
    )
    client = _github_client()

    with _patched(), patch("app.checks.service.GitHubClient", return_value=client):
        run_github_checks_for_snapshot(db, _repository(), _snapshot(github_check_run_id=999))

    client.create_issue_comment.assert_not_called()
    client.update_issue_comment.assert_called_once()
    args, _ = client.update_issue_comment.call_args
    assert args[2] == 555


def test_outdated_inline_comment_is_edited_and_minimized() -> None:
    decision = PolicyDecision(
        id=1, repository_id=1, diff_snapshot_id=1, decision="APPROVE", risk="LOW", reasons=["ok"]
    )
    ai_review = AIReview(id=1, repository_id=1, diff_snapshot_id=1, status="completed", summary="s")
    ai_review.findings = []  # the finding that existed last push is gone now
    pull_request = PullRequest(
        id=1, repository_id=1, github_pr_number=9, head_branch="foundations", base_branch="main"
    )
    stale_inline = ReviewComment(
        id=2,
        repository_id=1,
        pull_request_id=1,
        diff_snapshot_id=0,
        kind="inline",
        fingerprint="old-fp",
        github_comment_id=42,
        github_node_id="PRRC_kwabc123",
        status="posted",
        head_sha="sha0",
    )
    db = _make_db(
        decision=decision,
        ai_review=ai_review,
        tool_runs=[],
        pull_request=pull_request,
        existing_comments={("inline", "old-fp"): stale_inline},
    )
    client = _github_client()

    with _patched(), patch("app.checks.service.GitHubClient", return_value=client):
        run_github_checks_for_snapshot(db, _repository(), _snapshot(github_check_run_id=999))

    client.update_review_comment.assert_called_once()
    args, _ = client.update_review_comment.call_args
    assert args[2] == 42

    client.minimize_comment.assert_called_once_with("PRRC_kwabc123", classifier="OUTDATED")
    assert stale_inline.status == "outdated"


def test_resolved_manual_fix_comment_is_never_touched_by_the_outdated_sweep() -> None:
    """A comment app.autofix.service._update_manual_fix_comment already
    marked status="resolved" (a terminal manual-fix outcome, "Applied" or
    "Fix attempt failed") must never be picked up here even though its
    finding is gone from the current diff - confirmed live: without this,
    the very re-review a successful manual fix triggers immediately
    overwrote its own "Applied" text with the generic outdated marker.
    """
    decision = PolicyDecision(
        id=1, repository_id=1, diff_snapshot_id=1, decision="APPROVE", risk="LOW", reasons=["ok"]
    )
    ai_review = AIReview(id=1, repository_id=1, diff_snapshot_id=1, status="completed", summary="s")
    ai_review.findings = []  # the finding this manual fix resolved is gone now
    pull_request = PullRequest(
        id=1, repository_id=1, github_pr_number=9, head_branch="foundations", base_branch="main"
    )
    resolved_inline = ReviewComment(
        id=2,
        repository_id=1,
        pull_request_id=1,
        diff_snapshot_id=0,
        kind="inline",
        fingerprint="old-fp",
        github_comment_id=42,
        github_node_id="PRRC_kwabc123",
        status="resolved",
        head_sha="sha0",
    )
    db = _make_db(
        decision=decision,
        ai_review=ai_review,
        tool_runs=[],
        pull_request=pull_request,
        existing_comments={("inline", "old-fp"): resolved_inline},
    )
    client = _github_client()

    with _patched(), patch("app.checks.service.GitHubClient", return_value=client):
        run_github_checks_for_snapshot(db, _repository(), _snapshot(github_check_run_id=999))

    client.update_review_comment.assert_not_called()
    client.minimize_comment.assert_not_called()
    assert resolved_inline.status == "resolved"


def test_outdated_inline_comment_without_node_id_is_edited_but_not_minimized() -> None:
    """Rows created before the github_node_id column existed have no node id
    to minimize - they still fall back to the pre-existing edit-only
    behavior instead of erroring.
    """
    decision = PolicyDecision(
        id=1, repository_id=1, diff_snapshot_id=1, decision="APPROVE", risk="LOW", reasons=["ok"]
    )
    ai_review = AIReview(id=1, repository_id=1, diff_snapshot_id=1, status="completed", summary="s")
    ai_review.findings = []
    pull_request = PullRequest(
        id=1, repository_id=1, github_pr_number=9, head_branch="foundations", base_branch="main"
    )
    stale_inline = ReviewComment(
        id=2,
        repository_id=1,
        pull_request_id=1,
        diff_snapshot_id=0,
        kind="inline",
        fingerprint="old-fp",
        github_comment_id=42,
        github_node_id=None,
        status="posted",
        head_sha="sha0",
    )
    db = _make_db(
        decision=decision,
        ai_review=ai_review,
        tool_runs=[],
        pull_request=pull_request,
        existing_comments={("inline", "old-fp"): stale_inline},
    )
    client = _github_client()

    with _patched(), patch("app.checks.service.GitHubClient", return_value=client):
        run_github_checks_for_snapshot(db, _repository(), _snapshot(github_check_run_id=999))

    client.update_review_comment.assert_called_once()
    client.minimize_comment.assert_not_called()
    assert stale_inline.status == "outdated"


def test_minimize_failure_does_not_prevent_marking_outdated() -> None:
    decision = PolicyDecision(
        id=1, repository_id=1, diff_snapshot_id=1, decision="APPROVE", risk="LOW", reasons=["ok"]
    )
    ai_review = AIReview(id=1, repository_id=1, diff_snapshot_id=1, status="completed", summary="s")
    ai_review.findings = []
    pull_request = PullRequest(
        id=1, repository_id=1, github_pr_number=9, head_branch="foundations", base_branch="main"
    )
    stale_inline = ReviewComment(
        id=2,
        repository_id=1,
        pull_request_id=1,
        diff_snapshot_id=0,
        kind="inline",
        fingerprint="old-fp",
        github_comment_id=42,
        github_node_id="PRRC_kwabc123",
        status="posted",
        head_sha="sha0",
    )
    db = _make_db(
        decision=decision,
        ai_review=ai_review,
        tool_runs=[],
        pull_request=pull_request,
        existing_comments={("inline", "old-fp"): stale_inline},
    )
    client = _github_client()
    client.minimize_comment.side_effect = RuntimeError("minimizeComment failed")

    with _patched(), patch("app.checks.service.GitHubClient", return_value=client):
        run_github_checks_for_snapshot(db, _repository(), _snapshot(github_check_run_id=999))

    assert stale_inline.status == "outdated"


def test_find_pull_request_prefers_pull_request_id_fk_over_head_sha() -> None:
    """A stale `PullRequest.head_sha` (already moved on to a newer push
    while this snapshot's checks were still running) must not stop
    `_find_pull_request` from finding the PR when `pull_request_id` was
    stamped at snapshot creation time.
    """
    db = MagicMock()
    matched = PullRequest(
        id=9, repository_id=1, github_pr_number=2, head_branch="foundations",
        base_branch="main", head_sha="a-much-newer-sha", state="open",
    )
    db.get.return_value = matched
    diff_snapshot = _snapshot(id=1, pull_request_id=9)
    with patch("app.checks.service.get_settings", return_value=Settings()):
        result = _find_pull_request(db, _repository(), diff_snapshot)

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
    diff_snapshot = _snapshot(id=1, head_sha="sha1", pull_request_id=None)

    result = _find_pull_request(db, _repository(), diff_snapshot)

    assert result is matched
    db.get.assert_not_called()


def test_start_check_run_is_best_effort_on_malformed_response() -> None:
    db = MagicMock()
    client = MagicMock()
    client.create_check_run.return_value = MagicMock()  # not a dict -> no "id"
    snapshot = _snapshot()

    with patch("app.checks.service.get_settings", return_value=Settings()):
        start_check_run(client, _repository(), snapshot, db)

    assert snapshot.github_check_run_id is None
    db.commit.assert_not_called()
    db.rollback.assert_called_once()


def test_start_check_run_stores_id_on_success() -> None:
    db = MagicMock()
    client = MagicMock()
    client.create_check_run.return_value = {"id": 42}
    snapshot = _snapshot()

    with patch("app.checks.service.get_settings", return_value=Settings()):
        start_check_run(client, _repository(), snapshot, db)

    assert snapshot.github_check_run_id == 42
    db.commit.assert_called_once()
