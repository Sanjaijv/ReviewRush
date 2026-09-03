import re
from dataclasses import dataclass

from app.ai.schema import AIReviewIssue, Decision

_RISK_ORDER = ["low", "medium", "high", "critical"]
_RISK_RANK = {name: rank for rank, name in enumerate(_RISK_ORDER)}
_DECISION_RANK = {"approve": 0, "comment": 1, "request_changes": 2}
_SEVERITY_RANK = {"critical": 0, "high": 1, "medium": 2, "low": 3}

_WORD_RE = re.compile(r"[a-z0-9]+")

# Two findings on the same file with overlapping line ranges and titles this
# similar are treated as the same underlying issue reported by more than one
# reviewer, per the "duplicate findings collapse into one" acceptance
# criterion. A pure word-overlap heuristic on purpose - deterministic and
# auditable, no extra model call spent on "is this a duplicate?".
_TITLE_SIMILARITY_THRESHOLD = 0.5


@dataclass
class ReviewerVerdict:
    """One reviewer's contribution to consensus: a name plus enough of its
    ReviewerOutcome to aggregate (Phase 14). Only "completed" outcomes
    should be passed in - a failed/invalid specialist contributes nothing
    and must never be able to raise confidence or approve anything.
    """

    reviewer: str
    decision: Decision
    risk: str
    confidence: float


@dataclass
class MergedFinding:
    issue: AIReviewIssue
    contributing_reviewers: list[str]


@dataclass
class AggregatedVerdict:
    decision: Decision
    risk: str
    confidence: float
    disagreement: bool


def _risk_rank(risk: str) -> int:
    return _RISK_RANK.get(risk.lower(), _RISK_RANK["critical"])


def _title_words(title: str) -> set[str]:
    return set(_WORD_RE.findall(title.lower()))


def _titles_similar(a: str, b: str) -> bool:
    words_a, words_b = _title_words(a), _title_words(b)
    if not words_a or not words_b:
        return False
    union = words_a | words_b
    if not union:
        return False
    return len(words_a & words_b) / len(union) >= _TITLE_SIMILARITY_THRESHOLD


def _ranges_overlap(a: AIReviewIssue, b: AIReviewIssue) -> bool:
    return a.start_line <= b.end_line and b.start_line <= a.end_line


def is_duplicate_finding(existing: MergedFinding, candidate: AIReviewIssue) -> bool:
    """True when `candidate` reports the same underlying issue as
    `existing`: same file, overlapping line range, and either the same
    category or a similar title.
    """
    issue = existing.issue
    if issue.file != candidate.file or not _ranges_overlap(issue, candidate):
        return False
    return issue.category == candidate.category or _titles_similar(issue.title, candidate.title)


def merge_finding_into(existing: MergedFinding, candidate: AIReviewIssue, reviewer: str) -> None:
    issue = existing.issue
    if _SEVERITY_RANK.get(candidate.severity, 3) < _SEVERITY_RANK.get(issue.severity, 3):
        issue.severity = candidate.severity
    if candidate.evidence and candidate.evidence not in issue.evidence:
        issue.evidence = f"{issue.evidence}\n\n[{reviewer}] {candidate.evidence}"
    if candidate.recommendation and candidate.recommendation not in issue.recommendation:
        combined = (
            f"{issue.recommendation}\n[{reviewer}] {candidate.recommendation}"
            if issue.recommendation
            else candidate.recommendation
        )
        issue.recommendation = combined
    issue.context_refs = sorted(set(issue.context_refs) | set(candidate.context_refs))
    if reviewer not in existing.contributing_reviewers:
        existing.contributing_reviewers.append(reviewer)


def merge_findings(
    reviewer_issues: list[tuple[str, list[AIReviewIssue]]],
) -> list[MergedFinding]:
    """Collapse findings from multiple reviewer passes into one list,
    deduplicating same-location/same-issue reports (Phase 14) and recording
    which reviewers agreed on each surviving finding.

    `reviewer_issues` is processed in the given order, so callers that want
    the general reviewer's phrasing to "win" on a duplicate should list it
    first - later reviewers can still upgrade severity and add evidence.
    """
    merged: list[MergedFinding] = []
    for reviewer, issues in reviewer_issues:
        for issue in issues:
            duplicate = next((m for m in merged if is_duplicate_finding(m, issue)), None)
            if duplicate is not None:
                merge_finding_into(duplicate, issue, reviewer)
            else:
                merged.append(
                    MergedFinding(
                        issue=issue.model_copy(deep=True), contributing_reviewers=[reviewer]
                    )
                )
    return merged


def aggregate_verdicts(
    verdicts: list[ReviewerVerdict],
    disagreement_confidence_penalty: float,
) -> AggregatedVerdict:
    """Combine every completed reviewer's verdict into one consensus verdict,
    per the Phase 14 acceptance criteria:

    - Decision is the most severe of any reviewer's decision - one reviewer
      finding a real problem is enough to stop "approve" from winning.
    - Risk is the highest of any reviewer's risk.
    - Confidence is the lowest of any reviewer's confidence, reduced further
      when reviewers disagree on the decision - disagreement must raise
      uncertainty and can never produce automatic approval.

    `verdicts` must contain only reviewers whose pass completed - a failed
    or invalid specialist is the caller's responsibility to exclude before
    calling this, since it has no decision/risk/confidence to contribute.
    Finding-level merging is handled separately by `merge_findings`
    (offline/pure) or the incremental `is_duplicate_finding`/
    `merge_finding_into` primitives (used by the service layer, which must
    track database row identity while merging).
    """
    if not verdicts:
        raise ValueError("aggregate_verdicts requires at least one completed reviewer verdict")

    decision_rank = max(_DECISION_RANK[v.decision] for v in verdicts)
    decision = next(d for d, rank in _DECISION_RANK.items() if rank == decision_rank)

    risk_rank = max(_risk_rank(v.risk) for v in verdicts)
    risk = _RISK_ORDER[risk_rank]

    confidence = min(v.confidence for v in verdicts)
    disagreement = len({v.decision for v in verdicts}) > 1
    if disagreement:
        confidence = max(0.0, confidence - disagreement_confidence_penalty)

    return AggregatedVerdict(
        decision=decision,  # type: ignore[arg-type]
        risk=risk,
        confidence=confidence,
        disagreement=disagreement,
    )
