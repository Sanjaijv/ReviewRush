from app.models import AIFinding, AIReview, PolicyDecision, ToolRun

_DECISION_CONCLUSION = {
    "APPROVE": "success",
    "HUMAN_REVIEW": "action_required",
    "BLOCK": "failure",
}

_DECISION_NEXT_ACTION = {
    "APPROVE": "No action needed - this change meets the auto-merge policy.",
    "HUMAN_REVIEW": "A human reviewer must approve this change before it can merge.",
    "BLOCK": "This change cannot merge until the blocking issue(s) below are resolved.",
}

_OUTDATED_PREFIX = (
    "> ⚠️ **Outdated** - this finding is no longer present as of the latest push.\n\n"
)


def check_conclusion(decision: str) -> str:
    """Fail closed: an unrecognized decision value is treated as blocking."""
    return _DECISION_CONCLUSION.get(decision, "failure")


def check_title(decision: PolicyDecision) -> str:
    return f"{decision.decision} · risk {decision.risk}"


def _tool_run_lines(tool_runs: list[ToolRun]) -> list[str]:
    if not tool_runs:
        return ["- No deterministic checks recorded."]
    icons = {"passed": "✅", "failed": "❌", "errored": "⚠️", "timed_out": "⏱️"}
    return [
        f"- {icons.get(t.conclusion, '❓')} `{t.check_name}` — {t.conclusion}"
        + (" (required)" if t.required else "")
        for t in tool_runs
    ]


def _finding_lines(findings: list[AIFinding]) -> list[str]:
    if not findings:
        return ["- No AI findings."]
    severity_icons = {"critical": "🔴", "high": "🟠", "medium": "🟡", "low": "⚪"}
    return [
        f"- {severity_icons.get(f.severity, '❓')} **{f.severity}/{f.category}** "
        f"`{f.file}:{f.start_line}` — {f.title}"
        for f in findings
    ]


def render_summary_markdown(
    *,
    decision: PolicyDecision,
    ai_review: AIReview | None,
    tool_runs: list[ToolRun],
    findings: list[AIFinding],
    inline_posted_findings: set[int],
    head_sha: str,
) -> str:
    """Render the single PR summary comment body: check results, risk,
    important findings, and next action, per the Phase 8 spec.
    """
    lines = ["## ReviewRush review", ""]
    lines.append(f"**Decision:** `{decision.decision}` · **Risk:** `{decision.risk}`")
    if ai_review is not None and ai_review.summary:
        lines.append("")
        lines.append(ai_review.summary)
    lines.append("")
    lines.append("### Checks")
    lines.extend(_tool_run_lines(tool_runs))
    lines.append("")
    lines.append("### Findings")
    lines.extend(_finding_lines(findings))
    without_inline = [f for f in findings if f.id not in inline_posted_findings]
    if without_inline:
        lines.append("")
        lines.append(
            "_Findings above the inline-comment threshold, or on lines this review "
            "couldn't attach an inline comment to, are listed here only._"
        )
    lines.append("")
    lines.append("### Reasons")
    lines.extend(f"- {reason}" for reason in decision.reasons)
    lines.append("")
    next_action = _DECISION_NEXT_ACTION.get(decision.decision, "Review manually.")
    lines.append(f"**Next action:** {next_action}")
    lines.append("")
    lines.append(f"_Reviewed commit: `{head_sha}`_")
    return "\n".join(lines)


def render_inline_comment_body(finding: AIFinding) -> str:
    lines = [f"**{finding.severity}/{finding.category}: {finding.title}**", ""]
    lines.append(finding.evidence)
    if finding.recommendation:
        lines.append("")
        lines.append(f"**Recommendation:** {finding.recommendation}")
    return "\n".join(lines)


def mark_outdated(body: str) -> str:
    if body.startswith(_OUTDATED_PREFIX):
        return body
    return _OUTDATED_PREFIX + body
