from unittest.mock import MagicMock, patch

from app.config import Settings
from app.models import (
    AIFinding,
    AIReview,
    ChangedFile,
    DiffSnapshot,
    PolicyDecision,
    RepositoryConfigVersion,
    ToolRun,
)
from app.policy.service import run_policy_decision_for_snapshot


def _added(db: MagicMock, cls: type) -> object:
    """The last db.add()-ed instance of `cls` - policy decisions now also
    write an AuditEvent alongside the PolicyDecision, so a plain
    `db.add.call_args` no longer reliably picks out the PolicyDecision."""
    matches = [c.args[0] for c in db.add.call_args_list if isinstance(c.args[0], cls)]
    assert matches, f"no {cls.__name__} was added"
    return matches[-1]


class _FakeInstallation:
    github_installation_id = 1


class _FakeRepository:
    def __init__(self) -> None:
        self.id = 1
        self.owner = "acme"
        self.name = "widgets"
        self.full_name = "acme/widgets"
        self.installation = _FakeInstallation()


def _diff_snapshot(changed_files=None) -> DiffSnapshot:
    snapshot = DiffSnapshot(
        id=1,
        repository_id=1,
        head_sha="sha1",
        base_sha="mainsha",
        commits=[],
        total_changed_lines=10,
    )
    snapshot.changed_files = changed_files or [
        ChangedFile(new_path="src/app.py", old_path="src/app.py", status="modified")
    ]
    return snapshot


def _db(*, existing=None, tool_runs=None, ai_review=None) -> MagicMock:
    db = MagicMock()

    def query_side_effect(model):
        q = MagicMock()
        if model is PolicyDecision:
            q.filter_by.return_value.one_or_none.return_value = existing
        elif model is ToolRun:
            q.filter_by.return_value.all.return_value = tool_runs or []
        elif model is AIReview:
            q.filter_by.return_value.one_or_none.return_value = ai_review
        elif model is RepositoryConfigVersion:
            # No dashboard config override in these tests - falls back to
            # fetching .reviewrush.yml from GitHub, same as before Phase 12.
            q.filter_by.return_value.order_by.return_value.first.return_value = None
        return q

    db.query.side_effect = query_side_effect
    return db


def _run(db, config_yaml=None, settings=None):
    settings = settings or Settings()
    with (
        patch("app.policy.service.get_settings", return_value=settings),
        patch("app.policy.service.get_installation_access_token", return_value="tok"),
        patch("app.policy.service.GitHubClient") as github_client_cls,
    ):
        instance = MagicMock()
        instance.get_file_contents.return_value = config_yaml
        instance.__enter__.return_value = instance
        github_client_cls.return_value = instance
        return run_policy_decision_for_snapshot(db, _FakeRepository(), _diff_snapshot())


def test_existing_decision_is_reused_without_recomputing() -> None:
    existing = PolicyDecision(id=9, repository_id=1, diff_snapshot_id=1, decision="APPROVE")
    db = _db(existing=existing)

    result = _run(db)

    assert result is existing
    db.add.assert_not_called()


def test_no_ai_review_and_no_tool_runs_resolves_to_human_review() -> None:
    db = _db()

    _run(db)

    persisted: PolicyDecision = _added(db, PolicyDecision)
    assert persisted.decision == "HUMAN_REVIEW"
    assert persisted.policy_version == "1"
    assert persisted.reasons


def test_completed_ai_review_with_passing_checks_approves() -> None:
    ai_review = AIReview(
        id=1, repository_id=1, diff_snapshot_id=1, status="completed", risk="low", confidence=0.95
    )
    ai_review.findings = []
    tool_runs = [
        ToolRun(
            id=1, repository_id=1, diff_snapshot_id=1, check_name="tests", category="test",
            conclusion="passed", required=True,
        )
    ]
    db = _db(tool_runs=tool_runs, ai_review=ai_review)

    _run(db)

    persisted: PolicyDecision = _added(db, PolicyDecision)
    assert persisted.decision == "APPROVE"


def test_org_floor_confidence_cannot_be_weakened_by_repo_config() -> None:
    ai_review = AIReview(
        id=1, repository_id=1, diff_snapshot_id=1, status="completed", risk="low", confidence=0.80
    )
    ai_review.findings = []
    db = _db(ai_review=ai_review)
    settings = Settings(policy_org_min_ai_confidence=0.90)
    repo_yaml = "version: 1\nreview:\n  minimum_ai_confidence: 0.5\n"

    _run(db, config_yaml=repo_yaml, settings=settings)

    persisted: PolicyDecision = _added(db, PolicyDecision)
    # repo config tried to lower the confidence floor to 0.5; the org floor
    # (0.90) must still apply, so a 0.80-confidence review is not approved.
    assert persisted.decision == "HUMAN_REVIEW"


def test_org_floor_protected_paths_apply_even_when_repo_omits_them() -> None:
    changed_files = [
        ChangedFile(new_path=".github/workflows/ci.yml", old_path=None, status="modified")
    ]
    snapshot = _diff_snapshot(changed_files=changed_files)
    ai_review = AIReview(
        id=1, repository_id=1, diff_snapshot_id=1, status="completed", risk="low", confidence=0.95
    )
    ai_review.findings = []
    db = _db(ai_review=ai_review)
    settings = Settings()

    with (
        patch("app.policy.service.get_settings", return_value=settings),
        patch("app.policy.service.get_installation_access_token", return_value="tok"),
        patch("app.policy.service.GitHubClient") as github_client_cls,
    ):
        instance = MagicMock()
        instance.get_file_contents.return_value = None  # no .reviewrush.yml at all
        instance.__enter__.return_value = instance
        github_client_cls.return_value = instance
        run_policy_decision_for_snapshot(db, _FakeRepository(), snapshot)

    persisted: PolicyDecision = _added(db, PolicyDecision)
    assert persisted.decision == "HUMAN_REVIEW"
    assert persisted.evidence["protected_paths_matched"]


def test_critical_security_ai_finding_blocks() -> None:
    ai_review = AIReview(
        id=1, repository_id=1, diff_snapshot_id=1, status="completed", risk="low", confidence=0.95
    )
    ai_review.findings = [
        AIFinding(
            id=1, ai_review_id=1, repository_id=1, file="src/app.py", start_line=1, end_line=1,
            severity="critical", category="security", title="t", evidence="e",
        )
    ]
    db = _db(ai_review=ai_review)

    _run(db)

    persisted: PolicyDecision = _added(db, PolicyDecision)
    assert persisted.decision == "BLOCK"
    assert persisted.risk == "CRITICAL"
