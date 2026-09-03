from app.checks.rendering import (
    check_conclusion,
    mark_outdated,
    render_inline_comment_body,
    render_summary_markdown,
)
from app.models import AIFinding, AIReview, PolicyDecision, ToolRun


def test_check_conclusion_maps_known_decisions() -> None:
    assert check_conclusion("APPROVE") == "success"
    assert check_conclusion("HUMAN_REVIEW") == "action_required"
    assert check_conclusion("BLOCK") == "failure"


def test_check_conclusion_fails_closed_for_unknown_decision() -> None:
    assert check_conclusion("SOMETHING_ELSE") == "failure"


def test_render_inline_comment_body_includes_recommendation() -> None:
    finding = AIFinding(
        file="src/app.py",
        start_line=1,
        end_line=1,
        severity="high",
        category="security",
        title="Missing check",
        evidence="No ownership check.",
        recommendation="Add one.",
    )
    body = render_inline_comment_body(finding)
    assert "Missing check" in body
    assert "No ownership check." in body
    assert "Add one." in body


def test_render_inline_comment_body_omits_empty_recommendation() -> None:
    finding = AIFinding(
        file="src/app.py",
        start_line=1,
        end_line=1,
        severity="low",
        category="maintainability",
        title="Nit",
        evidence="Minor thing.",
        recommendation="",
    )
    body = render_inline_comment_body(finding)
    assert "Recommendation" not in body


def test_mark_outdated_is_idempotent() -> None:
    once = mark_outdated("original body")
    twice = mark_outdated(once)
    assert once == twice
    assert "Outdated" in once
    assert "original body" in once


def test_render_summary_markdown_includes_decision_risk_and_next_action() -> None:
    decision = PolicyDecision(
        policy_version="1",
        decision="HUMAN_REVIEW",
        risk="MEDIUM",
        reasons=["protected path(s) changed: src/auth/login.py"],
        evidence={},
    )
    ai_review = AIReview(status="completed", summary="Looks mostly fine.")
    tool_runs = [ToolRun(check_name="tests", category="tests", conclusion="passed", required=True)]
    finding = AIFinding(
        id=1,
        file="src/auth/login.py",
        start_line=5,
        end_line=5,
        severity="high",
        category="security",
        title="Missing ownership check",
        evidence="...",
    )

    body = render_summary_markdown(
        decision=decision,
        ai_review=ai_review,
        tool_runs=tool_runs,
        findings=[finding],
        inline_posted_findings=set(),
        head_sha="abc123",
    )

    assert "HUMAN_REVIEW" in body
    assert "MEDIUM" in body
    assert "protected path(s) changed" in body
    assert "Missing ownership check" in body
    assert "human reviewer must approve" in body
    assert "abc123" in body
