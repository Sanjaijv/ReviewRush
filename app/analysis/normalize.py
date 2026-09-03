import json
import logging
from dataclasses import dataclass, field
from typing import Any

from app.analysis.runner import RunnerResult
from app.analysis.stages import StageSpec

logger = logging.getLogger(__name__)

_MAX_ANNOTATIONS = 200
_MAX_SUMMARY_CHARS = 2000


@dataclass(frozen=True)
class NormalizedResult:
    """The tool-agnostic result of one check, matching the Phase 5 schema."""

    check: str
    category: str
    status: str
    conclusion: str
    required: bool
    exit_code: int | None
    duration_ms: int
    summary: str
    annotations: list[dict[str, Any]] = field(default_factory=list)
    log_excerpt: str | None = None
    log_truncated: bool = False


def _generic_summary(result: RunnerResult) -> str:
    for stream in (result.stdout, result.stderr):
        for line in reversed(stream.strip().splitlines()):
            if line.strip():
                return line.strip()[:_MAX_SUMMARY_CHARS]
    return f"exited with code {result.exit_code}"


def _parse_semgrep(stdout: str) -> tuple[str, list[dict[str, Any]]]:
    try:
        payload = json.loads(stdout)
    except (json.JSONDecodeError, ValueError):
        return "semgrep produced no parseable JSON output", []

    results = payload.get("results") or []
    annotations: list[dict[str, Any]] = []
    severity_counts: dict[str, int] = {}
    for entry in results[:_MAX_ANNOTATIONS]:
        extra = entry.get("extra") or {}
        severity = str(extra.get("severity", "unknown")).lower()
        severity_counts[severity] = severity_counts.get(severity, 0) + 1
        annotations.append(
            {
                "file": entry.get("path"),
                "line": (entry.get("start") or {}).get("line"),
                "end_line": (entry.get("end") or {}).get("line"),
                "severity": severity,
                "message": str(extra.get("message", ""))[:1000],
            }
        )
    breakdown = ", ".join(f"{count} {sev}" for sev, count in sorted(severity_counts.items()))
    summary = f"{len(results)} semgrep finding(s)" + (f" ({breakdown})" if breakdown else "")
    return summary, annotations


def _parse_gitleaks(stdout: str) -> tuple[str, list[dict[str, Any]]]:
    stripped = stdout.strip()
    if not stripped:
        return "no secrets detected", []
    try:
        leaks = json.loads(stripped)
    except (json.JSONDecodeError, ValueError):
        return "gitleaks produced no parseable JSON output", []
    if not isinstance(leaks, list):
        return "gitleaks produced no parseable JSON output", []

    annotations = [
        {
            "file": leak.get("File"),
            "line": leak.get("StartLine"),
            "end_line": leak.get("EndLine"),
            "severity": "critical",
            "message": f"{leak.get('RuleID', 'secret')}: {leak.get('Description', '')}"[:1000],
        }
        for leak in leaks[:_MAX_ANNOTATIONS]
    ]
    summary = f"{len(leaks)} secret(s) detected" if leaks else "no secrets detected"
    return summary, annotations


_TOOL_PARSERS = {
    "semgrep": _parse_semgrep,
    "gitleaks": _parse_gitleaks,
}


def normalize_skipped(stage: StageSpec) -> NormalizedResult:
    return NormalizedResult(
        check=stage.name,
        category=stage.category,
        status="completed",
        conclusion="skipped",
        required=stage.required,
        exit_code=None,
        duration_ms=0,
        summary=stage.skip_reason or "skipped",
        annotations=[],
    )


def normalize_result(stage: StageSpec, result: RunnerResult) -> NormalizedResult:
    """Convert one tool's raw RunnerResult into the standard schema.

    Timeouts and infra errors are surfaced as their own `conclusion` values
    distinct from `failed`, so a later policy engine can't mistake "the
    sandbox couldn't run this" for "the code failed this check".
    """
    log_excerpt = (result.stdout + ("\n" + result.stderr if result.stderr else "")).strip() or None
    log_truncated = result.stdout_truncated or result.stderr_truncated

    if result.errored:
        return NormalizedResult(
            check=stage.name,
            category=stage.category,
            status="error",
            conclusion="errored",
            required=stage.required,
            exit_code=result.exit_code,
            duration_ms=result.duration_ms,
            summary=result.error_message or "sandbox execution failed",
            annotations=[],
            log_excerpt=log_excerpt,
            log_truncated=log_truncated,
        )

    if result.timed_out:
        return NormalizedResult(
            check=stage.name,
            category=stage.category,
            status="completed",
            conclusion="timed_out",
            required=stage.required,
            exit_code=None,
            duration_ms=result.duration_ms,
            summary=result.error_message or "check timed out",
            annotations=[],
            log_excerpt=log_excerpt,
            log_truncated=log_truncated,
        )

    conclusion = "passed" if result.exit_code == 0 else "failed"
    parser = _TOOL_PARSERS.get(stage.name)
    if parser is not None:
        summary, annotations = parser(result.stdout)
        if conclusion == "passed" and annotations:
            # a tool can exit 0 while still reporting findings depending on
            # its own exit-code convention; findings always mean "failed".
            conclusion = "failed"
    else:
        summary = _generic_summary(result)
        annotations = []

    return NormalizedResult(
        check=stage.name,
        category=stage.category,
        status="completed",
        conclusion=conclusion,
        required=stage.required,
        exit_code=result.exit_code,
        duration_ms=result.duration_ms,
        summary=summary,
        annotations=annotations,
        log_excerpt=log_excerpt,
        log_truncated=log_truncated,
    )
