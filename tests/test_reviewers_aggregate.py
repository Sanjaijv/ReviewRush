from app.ai.schema import AIReviewIssue
from app.reviewers.aggregate import ReviewerVerdict, aggregate_verdicts, merge_findings


def _issue(**overrides) -> AIReviewIssue:
    base = dict(
        file="src/app.py",
        start_line=10,
        end_line=10,
        severity="medium",
        category="correctness",
        title="Off by one error in loop bound",
        evidence="evidence",
        recommendation="",
    )
    base.update(overrides)
    return AIReviewIssue(**base)


def test_aggregate_verdicts_takes_worst_decision_and_risk_and_min_confidence() -> None:
    verdicts = [
        ReviewerVerdict(reviewer="general", decision="approve", risk="low", confidence=0.95),
        ReviewerVerdict(
            reviewer="security", decision="request_changes", risk="high", confidence=0.80
        ),
    ]
    result = aggregate_verdicts(verdicts, disagreement_confidence_penalty=0.15)

    assert result.decision == "request_changes"
    assert result.risk == "high"
    # disagreement penalty applies on top of the min confidence
    assert result.confidence == 0.80 - 0.15
    assert result.disagreement is True


def test_aggregate_verdicts_no_disagreement_no_penalty() -> None:
    verdicts = [
        ReviewerVerdict(reviewer="general", decision="approve", risk="low", confidence=0.95),
        ReviewerVerdict(reviewer="security", decision="approve", risk="low", confidence=0.85),
    ]
    result = aggregate_verdicts(verdicts, disagreement_confidence_penalty=0.15)

    assert result.decision == "approve"
    assert result.confidence == 0.85
    assert result.disagreement is False


def test_aggregate_verdicts_confidence_penalty_never_goes_below_zero() -> None:
    verdicts = [
        ReviewerVerdict(reviewer="general", decision="approve", risk="low", confidence=0.05),
        ReviewerVerdict(
            reviewer="security", decision="request_changes", risk="critical", confidence=0.05
        ),
    ]
    result = aggregate_verdicts(verdicts, disagreement_confidence_penalty=0.5)
    assert result.confidence == 0.0


def test_aggregate_verdicts_requires_at_least_one_verdict() -> None:
    try:
        aggregate_verdicts([], disagreement_confidence_penalty=0.15)
        raised = False
    except ValueError:
        raised = True
    assert raised


def test_merge_findings_collapses_overlapping_same_category() -> None:
    general_issue = _issue(title="Loop bound may be off by one", severity="medium")
    specialist_issue = _issue(title="Off-by-one bound", severity="high")

    merged = merge_findings(
        [("general", [general_issue]), ("logic_correctness", [specialist_issue])]
    )

    assert len(merged) == 1
    assert merged[0].issue.severity == "high"  # max severity wins
    assert set(merged[0].contributing_reviewers) == {"general", "logic_correctness"}


def test_merge_findings_keeps_distinct_findings_separate_even_at_same_location() -> None:
    a = _issue(start_line=10, end_line=10, category="correctness", title="Off by one error")
    b = _issue(start_line=10, end_line=10, category="security", title="SQL injection risk")

    merged = merge_findings([("general", [a]), ("security", [b])])

    assert len(merged) == 2


def test_merge_findings_different_file_never_collapses() -> None:
    a = _issue(file="src/app.py")
    b = _issue(file="src/other.py")

    merged = merge_findings([("general", [a]), ("security", [b])])

    assert len(merged) == 2


def test_merge_findings_non_overlapping_lines_never_collapse() -> None:
    a = _issue(start_line=10, end_line=10)
    b = _issue(start_line=50, end_line=50)

    merged = merge_findings([("general", [a]), ("security", [b])])

    assert len(merged) == 2
