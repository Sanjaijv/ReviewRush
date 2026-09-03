from dataclasses import replace

from app.policy.engine import (
    POLICY_VERSION,
    AIFindingSummary,
    PolicyInput,
    ToolCheckResult,
    evaluate_policy,
)


def _baseline() -> PolicyInput:
    """All-passing input: should approve."""
    return PolicyInput(
        configured_required_checks=["tests", "lint"],
        tool_results=[
            ToolCheckResult(check_name="tests", required=True, conclusion="passed"),
            ToolCheckResult(check_name="lint", required=True, conclusion="passed"),
        ],
        ai_status="completed",
        ai_risk="low",
        ai_confidence=0.95,
        ai_findings=[],
        changed_paths=["src/app.py"],
        total_changed_lines=20,
        protected_path_patterns=["src/auth/**", "migrations/**"],
        dependency_manifest_patterns=["package.json", "requirements*.txt"],
        min_ai_confidence=0.90,
        max_auto_merge_risk="low",
        max_auto_mergeable_changed_lines=500,
    )


def test_baseline_is_approved() -> None:
    result = evaluate_policy(_baseline())
    assert result.decision == "APPROVE"
    assert result.risk == "LOW"
    assert result.policy_version == POLICY_VERSION
    assert result.reasons


def test_required_check_failure_blocks() -> None:
    inp = replace(
        _baseline(),
        tool_results=[
            ToolCheckResult(check_name="tests", required=True, conclusion="failed"),
            ToolCheckResult(check_name="lint", required=True, conclusion="passed"),
        ],
    )
    result = evaluate_policy(inp)
    assert result.decision == "BLOCK"
    assert result.risk == "CRITICAL"
    assert any("tests" in reason for reason in result.reasons)


def test_required_check_timed_out_blocks_distinctly_from_failed() -> None:
    inp = replace(
        _baseline(),
        tool_results=[
            ToolCheckResult(check_name="tests", required=True, conclusion="timed_out"),
            ToolCheckResult(check_name="lint", required=True, conclusion="passed"),
        ],
    )
    result = evaluate_policy(inp)
    assert result.decision == "BLOCK"
    assert any("timed_out" in reason for reason in result.reasons)


def test_failed_optional_check_does_not_block() -> None:
    inp = replace(
        _baseline(),
        configured_required_checks=["tests"],
        tool_results=[
            ToolCheckResult(check_name="tests", required=True, conclusion="passed"),
            ToolCheckResult(check_name="lint", required=False, conclusion="failed"),
        ],
    )
    result = evaluate_policy(inp)
    assert result.decision == "APPROVE"


def test_missing_required_check_result_forces_human_review() -> None:
    inp = replace(
        _baseline(),
        configured_required_checks=["tests", "lint", "typecheck"],
    )
    result = evaluate_policy(inp)
    assert result.decision == "HUMAN_REVIEW"
    assert any("typecheck" in reason for reason in result.reasons)


def test_critical_security_finding_blocks() -> None:
    inp = replace(
        _baseline(),
        ai_findings=[AIFindingSummary(severity="critical", category="security")],
    )
    result = evaluate_policy(inp)
    assert result.decision == "BLOCK"
    assert result.risk == "CRITICAL"


def test_critical_non_security_finding_does_not_block_but_escalates_risk() -> None:
    inp = replace(
        _baseline(),
        ai_findings=[AIFindingSummary(severity="critical", category="correctness")],
    )
    result = evaluate_policy(inp)
    assert result.decision == "HUMAN_REVIEW"
    assert result.risk == "CRITICAL"


def test_protected_path_forces_human_review() -> None:
    inp = replace(_baseline(), changed_paths=["src/auth/login.py"])
    result = evaluate_policy(inp)
    assert result.decision == "HUMAN_REVIEW"
    assert any("protected path" in reason for reason in result.reasons)
    assert result.risk == "HIGH"


def test_protected_path_with_override_still_blocks_via_risk_ceiling() -> None:
    """An administrator can lift the automatic human hand-off, but the risk
    is still escalated to HIGH, so it stays HUMAN_REVIEW unless
    max_auto_merge_risk is also raised to allow HIGH."""
    inp = replace(
        _baseline(),
        changed_paths=["src/auth/login.py"],
        require_human_for_protected_paths=False,
    )
    result = evaluate_policy(inp)
    assert result.decision == "HUMAN_REVIEW"
    assert not any("protected path" in reason for reason in result.reasons)
    assert result.risk == "HIGH"


def test_protected_path_with_override_and_raised_ceiling_approves() -> None:
    inp = replace(
        _baseline(),
        changed_paths=["src/auth/login.py"],
        require_human_for_protected_paths=False,
        max_auto_merge_risk="high",
    )
    result = evaluate_policy(inp)
    assert result.decision == "APPROVE"
    assert result.risk == "HIGH"


def test_ai_unavailable_forces_human_review() -> None:
    inp = replace(_baseline(), ai_status="error", ai_risk=None, ai_confidence=None)
    result = evaluate_policy(inp)
    assert result.decision == "HUMAN_REVIEW"
    assert any("unavailable" in reason for reason in result.reasons)


def test_missing_ai_review_forces_human_review() -> None:
    inp = replace(_baseline(), ai_status=None, ai_risk=None, ai_confidence=None)
    result = evaluate_policy(inp)
    assert result.decision == "HUMAN_REVIEW"


def test_low_confidence_forces_human_review() -> None:
    inp = replace(_baseline(), ai_confidence=0.5)
    result = evaluate_policy(inp)
    assert result.decision == "HUMAN_REVIEW"
    assert any("confidence" in reason for reason in result.reasons)


def test_ai_risk_above_maximum_forces_human_review() -> None:
    inp = replace(_baseline(), ai_risk="medium")
    result = evaluate_policy(inp)
    assert result.decision == "HUMAN_REVIEW"
    assert result.risk == "MEDIUM"


def test_ai_risk_within_a_higher_configured_maximum_approves() -> None:
    inp = replace(_baseline(), ai_risk="medium", max_auto_merge_risk="medium")
    result = evaluate_policy(inp)
    assert result.decision == "APPROVE"
    assert result.risk == "MEDIUM"


def test_oversized_change_escalates_risk_and_requires_human_review() -> None:
    inp = replace(_baseline(), total_changed_lines=5000)
    result = evaluate_policy(inp)
    assert result.decision == "HUMAN_REVIEW"
    assert result.risk == "MEDIUM"
    assert any("change size" in reason for reason in result.reasons)


def test_dependency_manifest_change_escalates_risk_and_requires_human_review() -> None:
    inp = replace(_baseline(), changed_paths=["package.json"])
    result = evaluate_policy(inp)
    assert result.decision == "HUMAN_REVIEW"
    assert result.risk == "MEDIUM"
    assert any("dependency manifest" in reason for reason in result.reasons)


def test_evidence_captures_inputs_used() -> None:
    result = evaluate_policy(_baseline())
    assert result.evidence["ai_status"] == "completed"
    assert result.evidence["ai_risk"] == "low"
    assert result.evidence["total_changed_lines"] == 20
    assert result.evidence["computed_risk"] == "LOW"


def test_same_input_always_produces_same_decision() -> None:
    inp = _baseline()
    first = evaluate_policy(inp)
    second = evaluate_policy(inp)
    assert first == second
