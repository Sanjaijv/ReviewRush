from unittest.mock import MagicMock, patch

from app.ai.schema import AIReviewIssue, AIReviewOutput
from app.ai.service import ReviewerOutcome
from app.config import Settings
from app.finetune.shadow import run_shadow_eval
from app.models import AIFinding, AIReview, DiffSnapshot, Repository


def _settings(**overrides) -> Settings:
    defaults = dict(
        finetune_shadow_eval_enabled=True,
        finetune_shadow_candidate_provider="ollama",
        finetune_shadow_candidate_model="reviewrush-finetune-1",
    )
    defaults.update(overrides)
    return Settings(**defaults)


def _ai_review(**overrides) -> AIReview:
    defaults = dict(
        id=1, repository_id=1, diff_snapshot_id=1, status="completed",
        decision="comment", risk="medium", confidence=0.8,
    )
    defaults.update(overrides)
    review = AIReview(**defaults)
    review.findings = []
    return review


def test_returns_none_when_disabled() -> None:
    db = MagicMock()
    settings = _settings(finetune_shadow_eval_enabled=False)
    result = run_shadow_eval(db, ai_review_id=1, settings=settings)
    assert result is None
    db.add.assert_not_called()


def test_returns_none_when_no_candidate_model_configured() -> None:
    db = MagicMock()
    settings = _settings(finetune_shadow_candidate_model="")
    result = run_shadow_eval(db, ai_review_id=1, settings=settings)
    assert result is None
    db.add.assert_not_called()


def test_returns_none_when_ai_review_missing() -> None:
    db = MagicMock()
    db.get.return_value = None
    result = run_shadow_eval(db, ai_review_id=1, settings=_settings())
    assert result is None


def test_returns_none_when_ai_review_not_completed() -> None:
    db = MagicMock()
    db.get.return_value = _ai_review(status="error")
    result = run_shadow_eval(db, ai_review_id=1, settings=_settings())
    assert result is None


def test_records_completed_comparison() -> None:
    ai_review = _ai_review()
    ai_review.findings = [
        AIFinding(
            id=1, ai_review_id=1, repository_id=1, file="a.py", start_line=1, end_line=1,
            severity="medium", category="correctness", title="t", evidence="e",
        )
    ]
    diff_snapshot = DiffSnapshot(id=1, repository_id=1, head_sha="abc")
    diff_snapshot.changed_files = []
    repository = Repository(id=1, full_name="octo/repo")

    db = MagicMock()
    db.get.side_effect = lambda model, id_: {
        AIReview: ai_review, DiffSnapshot: diff_snapshot, Repository: repository,
    }[model]
    db.query.return_value.filter_by.return_value.all.return_value = []

    candidate_output = AIReviewOutput(
        summary="looks fine", risk="low", confidence=0.6, decision="approve",
        issues=[
            AIReviewIssue(
                file="a.py", start_line=1, end_line=1, severity="low",
                category="correctness", title="t", evidence="e",
            )
        ],
    )
    outcome = ReviewerOutcome(
        status="completed", output=candidate_output, prompt_tokens=1, completion_tokens=1,
        latency_ms=1, attempt_count=1, error_message=None,
    )

    with (
        patch("app.finetune.shadow.build_repository_context_for_snapshot", return_value=None),
        patch("app.finetune.shadow.build_review_model", return_value=MagicMock()),
        patch("app.finetune.shadow.run_reviewer_pass", return_value=outcome),
    ):
        result = run_shadow_eval(db, ai_review_id=1, settings=_settings())

    assert result is not None
    assert result.status == "completed"
    assert result.live_issue_count == 1
    assert result.candidate_issue_count == 1
    assert result.comparison["decision_diff"] is True
    db.add.assert_called_once_with(result)
    db.commit.assert_called_once()


def test_records_error_when_candidate_model_call_fails() -> None:
    ai_review = _ai_review()
    diff_snapshot = DiffSnapshot(id=1, repository_id=1, head_sha="abc")
    diff_snapshot.changed_files = []
    repository = Repository(id=1, full_name="octo/repo")

    db = MagicMock()
    db.get.side_effect = lambda model, id_: {
        AIReview: ai_review, DiffSnapshot: diff_snapshot, Repository: repository,
    }[model]
    db.query.return_value.filter_by.return_value.all.return_value = []

    outcome = ReviewerOutcome(
        status="error", output=None, prompt_tokens=0, completion_tokens=0, latency_ms=0,
        attempt_count=1, error_message="model unreachable",
    )

    with (
        patch("app.finetune.shadow.build_repository_context_for_snapshot", return_value=None),
        patch("app.finetune.shadow.build_review_model", return_value=MagicMock()),
        patch("app.finetune.shadow.run_reviewer_pass", return_value=outcome),
    ):
        result = run_shadow_eval(db, ai_review_id=1, settings=_settings())

    assert result.status == "error"
    assert result.error_message == "model unreachable"


def test_records_error_when_unexpected_exception_raised() -> None:
    ai_review = _ai_review()
    db = MagicMock()
    db.get.side_effect = lambda model, id_: ai_review if model is AIReview else MagicMock()

    with patch(
        "app.finetune.shadow.build_repository_context_for_snapshot",
        side_effect=RuntimeError("boom"),
    ):
        result = run_shadow_eval(db, ai_review_id=1, settings=_settings())

    assert result.status == "error"
    assert "boom" in result.error_message
    db.add.assert_called_once()
