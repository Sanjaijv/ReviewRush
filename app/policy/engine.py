from dataclasses import dataclass, field
from typing import Any

from app.policy.paths import matches_any

POLICY_VERSION = "1"

_RISK_ORDER = ["low", "medium", "high", "critical"]
_RISK_RANK = {name: rank for rank, name in enumerate(_RISK_ORDER)}


def _risk_rank(risk: str | None) -> int:
    """Unknown/invalid risk values fail closed to the worst rank (critical)."""
    if risk is None:
        return _RISK_RANK["low"]
    return _RISK_RANK.get(risk.lower(), _RISK_RANK["critical"])


@dataclass(frozen=True)
class ToolCheckResult:
    """One observed deterministic-check outcome, from a ToolRun row."""

    check_name: str
    required: bool
    conclusion: str  # "passed" / "failed" / "errored" / "timed_out"


@dataclass(frozen=True)
class AIFindingSummary:
    severity: str
    category: str


@dataclass(frozen=True)
class PolicyInput:
    """Everything the policy engine needs, already merged/resolved by the
    caller: protected paths are the union of repo config and the org floor,
    `min_ai_confidence` is the max of repo config and the org floor, and
    `max_auto_merge_risk` is the min of repo config and the org floor - the
    engine itself never re-reads repo config or Settings, so it stays pure
    and trivially testable.
    """

    configured_required_checks: list[str]
    tool_results: list[ToolCheckResult]

    ai_status: str | None
    ai_risk: str | None
    ai_confidence: float | None
    ai_findings: list[AIFindingSummary] = field(default_factory=list)

    changed_paths: list[str] = field(default_factory=list)
    total_changed_lines: int = 0

    protected_path_patterns: list[str] = field(default_factory=list)
    dependency_manifest_patterns: list[str] = field(default_factory=list)

    min_ai_confidence: float = 0.90
    max_auto_merge_risk: str = "low"
    max_auto_mergeable_changed_lines: int = 500
    # Roadmap: "Never auto-merge changes involving protected paths unless a
    # repository administrator explicitly enables that behavior." True (the
    # default) keeps today's behavior - any protected-path match forces
    # HUMAN_REVIEW. An admin can set this False in .reviewrush.yml to lift
    # that force-route; the risk-rank bump to HIGH below still applies
    # unconditionally, so it stays blocked unless max_auto_merge_risk is
    # also raised - this field only removes the automatic human hand-off.
    require_human_for_protected_paths: bool = True


@dataclass(frozen=True)
class PolicyResult:
    policy_version: str
    decision: str  # "APPROVE" / "HUMAN_REVIEW" / "BLOCK"
    risk: str  # "LOW" / "MEDIUM" / "HIGH" / "CRITICAL"
    reasons: list[str]
    evidence: dict[str, Any]


def evaluate_policy(inp: PolicyInput) -> PolicyResult:
    """Convert deterministic and AI evidence into an auditable decision.

    Deterministic, side-effect-free, and depends only on `inp`: the same
    input always produces the same output, which is what makes a
    PolicyDecision row reproducible from its stored evidence. Rules are
    evaluated in order and the first one that resolves the decision wins,
    matching the roadmap's fail-closed pseudocode (required checks, then
    critical security findings, then protected paths, then AI
    availability/confidence, then overall risk).
    """
    reasons: list[str] = []
    tool_by_name = {t.check_name: t for t in inp.tool_results}

    matched_protected = [
        (path, pattern)
        for path in inp.changed_paths
        if (pattern := matches_any(path, inp.protected_path_patterns)) is not None
    ]
    dependency_changed = [
        path
        for path in inp.changed_paths
        if matches_any(path, inp.dependency_manifest_patterns) is not None
    ]
    size_exceeded = inp.total_changed_lines > inp.max_auto_mergeable_changed_lines

    risk_rank = _risk_rank(inp.ai_risk)
    if any(f.severity == "critical" for f in inp.ai_findings):
        risk_rank = max(risk_rank, _risk_rank("critical"))
    elif any(f.severity == "high" for f in inp.ai_findings):
        risk_rank = max(risk_rank, _risk_rank("high"))
    if matched_protected:
        risk_rank = max(risk_rank, _risk_rank("high"))
    if size_exceeded or dependency_changed:
        risk_rank = max(risk_rank, _risk_rank("medium"))

    evidence: dict[str, Any] = {
        "tool_results": [
            {"check": t.check_name, "required": t.required, "conclusion": t.conclusion}
            for t in inp.tool_results
        ],
        "ai_status": inp.ai_status,
        "ai_risk": inp.ai_risk,
        "ai_confidence": inp.ai_confidence,
        "ai_findings": [{"severity": f.severity, "category": f.category} for f in inp.ai_findings],
        "protected_paths_matched": [{"path": p, "pattern": pat} for p, pat in matched_protected],
        "require_human_for_protected_paths": inp.require_human_for_protected_paths,
        "dependency_files_changed": dependency_changed,
        "total_changed_lines": inp.total_changed_lines,
        "min_ai_confidence": inp.min_ai_confidence,
        "max_auto_merge_risk": inp.max_auto_merge_risk,
        "computed_risk": _RISK_ORDER[risk_rank].upper(),
    }

    def result(decision: str, risk_override: str | None = None) -> PolicyResult:
        risk = risk_override or _RISK_ORDER[risk_rank].upper()
        return PolicyResult(
            policy_version=POLICY_VERSION,
            decision=decision,
            risk=risk,
            reasons=list(reasons),
            evidence=evidence,
        )

    failed_required = [
        t
        for t in inp.tool_results
        if t.required and t.conclusion in ("failed", "errored", "timed_out")
    ]
    if failed_required:
        for t in failed_required:
            reasons.append(f"required check '{t.check_name}' {t.conclusion}")
        return result("BLOCK", risk_override="CRITICAL")

    missing_required = [
        name for name in inp.configured_required_checks if name not in tool_by_name
    ]
    if missing_required:
        reasons.append(f"required check(s) missing a result: {', '.join(missing_required)}")
        return result("HUMAN_REVIEW")

    critical_security = [
        f for f in inp.ai_findings if f.severity == "critical" and f.category == "security"
    ]
    if critical_security:
        reasons.append(f"{len(critical_security)} critical security finding(s)")
        return result("BLOCK", risk_override="CRITICAL")

    if matched_protected and inp.require_human_for_protected_paths:
        changed = ", ".join(p for p, _ in matched_protected)
        reasons.append(f"protected path(s) changed: {changed}")
        return result("HUMAN_REVIEW")

    if inp.ai_status != "completed":
        reasons.append(f"ai review unavailable (status={inp.ai_status or 'missing'})")
        return result("HUMAN_REVIEW")

    if inp.ai_confidence is None or inp.ai_confidence < inp.min_ai_confidence:
        reasons.append(
            f"ai confidence {inp.ai_confidence} below minimum {inp.min_ai_confidence}"
        )
        return result("HUMAN_REVIEW")

    if size_exceeded:
        reasons.append(
            f"change size {inp.total_changed_lines} exceeds threshold "
            f"{inp.max_auto_mergeable_changed_lines}"
        )
    if dependency_changed:
        reasons.append(f"dependency manifest(s) changed: {', '.join(dependency_changed)}")

    if risk_rank > _risk_rank(inp.max_auto_merge_risk):
        reasons.append(
            f"risk {_RISK_ORDER[risk_rank]} exceeds maximum auto-mergeable risk "
            f"{inp.max_auto_merge_risk}"
        )
        return result("HUMAN_REVIEW")

    reasons.append("required checks passed, no protected paths, risk within threshold")
    return result("APPROVE")
