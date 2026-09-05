from app.checks.rendering import (
    check_conclusion,
    manual_fix_was_just_checked,
    mark_manual_fix_applied,
    mark_manual_fix_failed,
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


def test_render_inline_comment_body_offers_manual_fix_checkbox_when_requested() -> None:
    finding = AIFinding(
        file="src/app.py", start_line=1, end_line=1, severity="high", category="security",
        title="SQL injection", evidence="...",
    )
    body = render_inline_comment_body(finding, offer_manual_fix=True)
    assert "- [ ] Apply this fix" in body


def test_render_inline_comment_body_omits_checkbox_by_default() -> None:
    finding = AIFinding(
        file="src/app.py", start_line=1, end_line=1, severity="high", category="security",
        title="SQL injection", evidence="...",
    )
    body = render_inline_comment_body(finding)
    assert "Apply this fix" not in body


def test_manual_fix_was_just_checked_detects_transition() -> None:
    old_body = "some text\n\n- [ ] Apply this fix — details"
    new_body = "some text\n\n- [x] Apply this fix — details"
    assert manual_fix_was_just_checked(old_body, new_body) is True


def test_manual_fix_was_just_checked_ignores_unrelated_edits() -> None:
    old_body = "some text\n\n- [ ] Apply this fix — details"
    new_body = "different text\n\n- [ ] Apply this fix — details"
    assert manual_fix_was_just_checked(old_body, new_body) is False


def test_manual_fix_was_just_checked_ignores_already_checked() -> None:
    # Both bodies already checked - e.g. a duplicate webhook delivery for
    # the same edit must never re-trigger a second attempt.
    old_body = "- [x] Apply this fix — details"
    new_body = "- [x] Apply this fix — details, edited"
    assert manual_fix_was_just_checked(old_body, new_body) is False


def test_mark_manual_fix_applied_replaces_checked_box() -> None:
    body = "some text\n\n---\n- [x] Apply this fix — ReviewRush will..."
    result = mark_manual_fix_applied(body, commit_sha="abc123def456")
    assert "- [x] Applied" in result
    assert "abc123de" in result
    assert "Apply this fix — ReviewRush" not in result


def test_mark_manual_fix_failed_replaces_checked_box() -> None:
    body = "some text\n\n---\n- [x] Apply this fix — ReviewRush will..."
    result = mark_manual_fix_failed(body, reason="model call failed")
    assert "Fix attempt failed: model call failed" in result
    assert "- [x]" in result


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
