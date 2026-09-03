import hashlib

from app.models import AIFinding

SUMMARY_FINGERPRINT = "summary"

_SEVERITY_RANK: dict[str, int] = {"critical": 0, "high": 1, "medium": 2, "low": 3}


def finding_fingerprint(finding: AIFinding) -> str:
    """Stable identity for a finding's *content*, not its row id.

    Deliberately excludes `ai_review_id`/`diff_snapshot_id`: the same
    underlying issue reported again in a later head_sha's AIReview must
    fingerprint identically so it's recognized as "already posted" instead
    of spawning a duplicate comment.
    """
    raw = "\x1f".join(
        [
            finding.category,
            finding.file,
            str(finding.start_line),
            str(finding.end_line),
            finding.title,
        ]
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]


def severity_rank(severity: str) -> int:
    """Unknown severities fail closed to the worst (most visible) rank."""
    return _SEVERITY_RANK.get(severity.lower(), 0)


def meets_inline_threshold(severity: str, min_severity: str) -> bool:
    return severity_rank(severity) <= severity_rank(min_severity)
