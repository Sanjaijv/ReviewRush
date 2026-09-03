from unittest.mock import MagicMock, patch

from app.ai.model import ModelResponse
from app.config import Settings
from app.models import AIFinding, AIReview, ChangedFile, DiffSnapshot, SpecializedReview, ToolRun
from app.reviewers.service import run_specialized_reviews_for_snapshot

_PATCH = "@@ -1,3 +1,4 @@\n context1\n-removed1\n+added1\n+added2\n context2"


class _FakeInstallation:
    github_installation_id = 1


class _FakeRepository:
    def __init__(self) -> None:
        self.id = 1
        self.owner = "acme"
        self.name = "widgets"
        self.full_name = "acme/widgets"
        self.installation = _FakeInstallation()


class _FakeModel:
    def __init__(self, responses: list[ModelResponse]) -> None:
        self._responses = list(responses)
        self.calls: list[dict] = []

    def generate(self, *, system, messages):
        self.calls.append({"system": system, "messages": messages})
        return self._responses.pop(0)


def _response(content) -> ModelResponse:
    return ModelResponse(
        content=content, raw_text=str(content), prompt_tokens=10, completion_tokens=5,
        latency_ms=1,
    )


def _specialized_output(
    category: str, decision: str = "approve", risk: str = "low", **issue_overrides
) -> dict:
    issue = dict(
        file="src/app.py", start_line=2, end_line=2, severity="medium", category=category,
        title=f"{category} finding", evidence="evidence", recommendation="",
    )
    issue.update(issue_overrides)
    return {
        "summary": f"{category} summary", "risk": risk, "confidence": 0.9,
        "decision": decision, "issues": [issue],
    }


def _diff_snapshot() -> DiffSnapshot:
    snapshot = DiffSnapshot(id=1, repository_id=1, head_sha="sha1", base_sha="mainsha", commits=[])
    snapshot.changed_files = [
        ChangedFile(
            new_path="src/app.py", old_path="src/app.py", status="modified",
            additions=40, deletions=10, patch=_PATCH,
        )
    ]
    return snapshot


def _ai_review() -> AIReview:
    review = AIReview(
        id=5, repository_id=1, diff_snapshot_id=1, status="completed", decision="approve",
        risk="low", confidence=0.95, summary="general summary",
    )
    review.findings = [
        AIFinding(
            id=1, repository_id=1, ai_review_id=5, file="src/app.py", start_line=2, end_line=2,
            severity="medium", category="correctness", title="Off by one issue",
            evidence="general evidence", recommendation="", context_refs=[],
            contributing_reviewers=["general"],
        )
    ]
    return review


def _db(existing_specialized: SpecializedReview | None = None) -> MagicMock:
    db = MagicMock()

    def query_side_effect(model):
        m = MagicMock()
        if model is SpecializedReview:
            m.filter_by.return_value.first.return_value = existing_specialized
        elif model is ToolRun:
            m.filter_by.return_value.all.return_value = []
        return m

    db.query.side_effect = query_side_effect
    return db


def _settings(**overrides) -> Settings:
    base = dict(ai_specialized_reviewers_enabled=True)
    base.update(overrides)
    return Settings(**base)


def _run(db, settings, model, ai_review):
    with (
        patch("app.reviewers.service.get_settings", return_value=settings),
        patch("app.reviewers.service.get_installation_access_token", return_value="tok"),
        patch("app.reviewers.service.GitHubClient") as github_client_cls,
        patch("app.reviewers.service.build_review_model", return_value=model),
    ):
        instance = MagicMock()
        instance.get_file_contents.return_value = None
        instance.__enter__.return_value = instance
        github_client_cls.return_value = instance
        return run_specialized_reviews_for_snapshot(
            db, _FakeRepository(), _diff_snapshot(), ai_review
        )


def test_disabled_flag_is_a_noop() -> None:
    db = _db()
    ai_review = _ai_review()
    model = _FakeModel([])

    result = _run(db, _settings(ai_specialized_reviewers_enabled=False), model, ai_review)

    assert result is ai_review
    assert model.calls == []
    db.commit.assert_not_called()


def test_general_review_not_completed_is_a_noop() -> None:
    db = _db()
    ai_review = _ai_review()
    ai_review.status = "invalid_output"
    model = _FakeModel([])

    _run(db, _settings(), model, ai_review)

    assert model.calls == []


def test_already_ran_is_idempotent() -> None:
    db = _db(existing_specialized=SpecializedReview(id=1, ai_review_id=5, repository_id=1))
    ai_review = _ai_review()
    model = _FakeModel([])

    _run(db, _settings(), model, ai_review)

    assert model.calls == []


def test_specialist_escalates_decision_and_risk_and_lowers_confidence_on_disagreement() -> None:
    db = _db()
    ai_review = _ai_review()
    # selected for a large single-file code change: security, logic_correctness,
    # performance_concurrency, test_quality (architecture needs >=5 files).
    model = _FakeModel([
        _response(_specialized_output(
            "security", decision="request_changes", risk="critical", severity="critical",
        )),
        _response(_specialized_output("correctness")),
        _response(_specialized_output("performance")),
        _response(_specialized_output("missing_tests")),
    ])

    result = _run(db, _settings(), model, ai_review)

    assert len(model.calls) == 4
    assert result.decision == "request_changes"
    assert result.risk == "critical"
    assert result.confidence < 0.95  # disagreement penalty applied
    db.commit.assert_called_once()

    specialized_rows = [
        call.args[0] for call in db.add.call_args_list
        if isinstance(call.args[0], SpecializedReview)
    ]
    assert {row.reviewer for row in specialized_rows} == {
        "security", "logic_correctness", "performance_concurrency", "test_quality",
    }
    assert all(row.status == "completed" for row in specialized_rows)


def test_specialist_finding_at_same_location_merges_into_existing_finding() -> None:
    db = _db()
    ai_review = _ai_review()
    model = _FakeModel([
        _response(_specialized_output("security")),
        _response(_specialized_output(
            "correctness", start_line=2, end_line=2, severity="high", title="Off by one bug",
        )),
        _response(_specialized_output("performance")),
        _response(_specialized_output("missing_tests")),
    ])

    _run(db, _settings(), model, ai_review)

    # the logic_correctness reviewer's finding at the same file/line as the
    # existing general finding must merge in, not create a duplicate row.
    existing_finding = ai_review.findings[0]
    assert existing_finding.severity == "high"
    assert "general" in existing_finding.contributing_reviewers
    assert "logic_correctness" in existing_finding.contributing_reviewers

    new_finding_rows = [
        call.args[0] for call in db.add.call_args_list
        if isinstance(call.args[0], AIFinding) and call.args[0] is not existing_finding
    ]
    # security, performance, and missing_tests findings are all genuinely new
    assert len(new_finding_rows) == 3


def test_no_reviewer_selected_is_a_noop() -> None:
    db = _db()
    ai_review = _ai_review()
    diff_snapshot = DiffSnapshot(id=1, repository_id=1, head_sha="sha1", base_sha="mainsha")
    diff_snapshot.changed_files = [
        ChangedFile(new_path="README.md", old_path="README.md", status="modified", patch="doc")
    ]
    model = _FakeModel([])

    with (
        patch("app.reviewers.service.get_settings", return_value=_settings()),
    ):
        result = run_specialized_reviews_for_snapshot(
            db, _FakeRepository(), diff_snapshot, ai_review
        )

    assert result is ai_review
    assert model.calls == []
