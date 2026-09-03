import pytest
from pydantic import ValidationError

from app.ai.schema import AIReviewIssue, AIReviewOutput


def _valid_issue(**overrides) -> dict:
    base = dict(
        file="src/app.py",
        start_line=10,
        end_line=10,
        severity="high",
        category="security",
        title="Missing ownership check",
        evidence="The handler never compares the requester to the resource owner.",
        recommendation="Require ownership or an admin role.",
    )
    base.update(overrides)
    return base


def test_valid_output_passes() -> None:
    output = AIReviewOutput(
        summary="Looks mostly fine.",
        risk="low",
        confidence=0.93,
        decision="approve",
        issues=[_valid_issue()],
    )
    assert output.issues[0].severity == "high"


def test_context_refs_defaults_to_empty_list() -> None:
    issue = AIReviewIssue(**_valid_issue())
    assert issue.context_refs == []


def test_context_refs_accepts_ids() -> None:
    issue = AIReviewIssue(**_valid_issue(context_refs=["ctx-1", "ctx-2"]))
    assert issue.context_refs == ["ctx-1", "ctx-2"]


def test_invalid_severity_enum_rejected() -> None:
    with pytest.raises(ValidationError):
        AIReviewIssue(**_valid_issue(severity="extreme"))


def test_invalid_category_enum_rejected() -> None:
    with pytest.raises(ValidationError):
        AIReviewIssue(**_valid_issue(category="vibes"))


def test_missing_evidence_rejected() -> None:
    with pytest.raises(ValidationError):
        AIReviewIssue(**_valid_issue(evidence=""))


def test_end_line_before_start_line_rejected() -> None:
    with pytest.raises(ValidationError):
        AIReviewIssue(**_valid_issue(start_line=20, end_line=10))


def test_unknown_extra_field_rejected() -> None:
    with pytest.raises(ValidationError):
        AIReviewOutput(
            summary="x",
            risk="low",
            confidence=0.5,
            decision="approve",
            issues=[],
            merge=True,
        )


def test_decision_has_no_merge_value() -> None:
    with pytest.raises(ValidationError):
        AIReviewOutput(
            summary="x", risk="low", confidence=0.5, decision="merge", issues=[]
        )


def test_confidence_out_of_range_rejected() -> None:
    with pytest.raises(ValidationError):
        AIReviewOutput(summary="x", risk="low", confidence=1.5, decision="approve", issues=[])
