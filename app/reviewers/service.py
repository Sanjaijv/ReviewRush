import logging
from typing import Any, cast

from app.ai.model import build_review_model
from app.ai.schema import AIReviewIssue, Category, Severity
from app.ai.service import run_reviewer_pass
from app.config import get_settings
from app.context.service import build_repository_context_for_snapshot
from app.github.auth import get_installation_access_token
from app.github.client import GitHubClient
from app.models import AIFinding, AIReview, DiffSnapshot, Repository, SpecializedReview, ToolRun
from app.observability.metrics import (
    model_call_failures_total,
    review_stage_duration_seconds,
    specialized_reviewer_disagreement_total,
    specialized_reviewer_findings_total,
)
from app.repo_config import parse_repo_config
from app.reviewers.aggregate import (
    MergedFinding,
    ReviewerVerdict,
    aggregate_verdicts,
    is_duplicate_finding,
    merge_finding_into,
)
from app.reviewers.definitions import ReviewerDefinition
from app.reviewers.prompt import build_specialized_review_prompt
from app.reviewers.selection import select_reviewers

logger = logging.getLogger(__name__)

REPO_CONFIG_PATH = ".reviewrush.yml"


def _already_ran(db: Any, ai_review_id: int) -> bool:
    return (
        db.query(SpecializedReview).filter_by(ai_review_id=ai_review_id).first() is not None
    )


def _issue_from_finding(finding: AIFinding) -> AIReviewIssue:
    # AIFinding.severity/category are plain str columns (validated only at
    # write time, by the Phase 6 schema); re-validated here by AIReviewIssue
    # itself on construction, so the cast just satisfies the type checker.
    return AIReviewIssue(
        file=finding.file,
        start_line=finding.start_line,
        end_line=finding.end_line,
        severity=cast(Severity, finding.severity),
        category=cast(Category, finding.category),
        title=finding.title,
        evidence=finding.evidence,
        recommendation=finding.recommendation,
        context_refs=list(finding.context_refs or []),
    )


def _apply_merged_issue(finding: AIFinding, merged: MergedFinding) -> None:
    issue = merged.issue
    finding.severity = issue.severity
    finding.evidence = issue.evidence
    finding.recommendation = issue.recommendation
    finding.context_refs = issue.context_refs
    finding.contributing_reviewers = list(merged.contributing_reviewers)


def _persist_specialized_review(
    db: Any, ai_review: AIReview, repository: Repository, reviewer: ReviewerDefinition, outcome: Any
) -> None:
    row = SpecializedReview(
        ai_review_id=ai_review.id,
        repository_id=repository.id,
        reviewer=reviewer.name,
        status=outcome.status,
        decision=outcome.output.decision if outcome.output else None,
        risk=outcome.output.risk if outcome.output else None,
        confidence=outcome.output.confidence if outcome.output else None,
        summary=outcome.output.summary if outcome.output else "",
        prompt_tokens=outcome.prompt_tokens,
        completion_tokens=outcome.completion_tokens,
        latency_ms=outcome.latency_ms,
        attempt_count=outcome.attempt_count,
        error_message=outcome.error_message,
    )
    db.add(row)

    review_stage_duration_seconds.labels(
        stage=f"specialized_review:{reviewer.name}", outcome=outcome.status
    ).observe(outcome.latency_ms / 1000)
    if outcome.status != "completed":
        settings = get_settings()
        model_call_failures_total.labels(provider=settings.ai_provider, status=outcome.status).inc()


def run_specialized_reviews_for_snapshot(
    db: Any, repository: Repository, diff_snapshot: DiffSnapshot, ai_review: AIReview | None
) -> AIReview | None:
    """Run selected specialized reviewers (Phase 14) over one diff snapshot
    and fold their findings/verdict into the existing (general-reviewer)
    AIReview row.

    A pure enrichment step on top of the Phase 6 pipeline: the policy engine
    and GitHub comment renderer keep reading the same single AIReview and
    its AIFinding rows, now possibly updated with specialist input. Runs at
    most once per AIReview (idempotent via the presence of any
    SpecializedReview row for it), and only when the general reviewer
    itself completed - there is nothing trustworthy to aggregate against
    otherwise, and the missing/failed general review already forces
    HUMAN_REVIEW downstream.
    """
    settings = get_settings()
    if not settings.ai_specialized_reviewers_enabled:
        return ai_review
    if ai_review is None or ai_review.status != "completed":
        return ai_review
    if _already_ran(db, ai_review.id):
        return ai_review

    changed_files = list(diff_snapshot.changed_files)
    selected = select_reviewers(changed_files)
    if not selected:
        return ai_review

    installation = repository.installation
    token = get_installation_access_token(installation.github_installation_id)
    with GitHubClient(token) as client:
        config_yaml = client.get_file_contents(
            repository.owner, repository.name, REPO_CONFIG_PATH, ref=diff_snapshot.head_sha
        )
    repo_config = parse_repo_config(config_yaml)

    tool_runs = db.query(ToolRun).filter_by(diff_snapshot_id=diff_snapshot.id).all()
    context_snapshot = build_repository_context_for_snapshot(db, repository, diff_snapshot)
    changed_files_by_path = {(f.new_path or f.old_path or ""): f for f in changed_files}

    model = build_review_model(settings)
    if model is None:
        logger.error(
            "unknown AI provider configured, skipping specialized reviewers",
            extra={"repository": repository.full_name, "head_sha": diff_snapshot.head_sha},
        )
        return ai_review

    existing_findings = list(ai_review.findings)
    merged: list[MergedFinding] = [
        MergedFinding(
            issue=_issue_from_finding(f),
            contributing_reviewers=list(f.contributing_reviewers or ["general"]),
        )
        for f in existing_findings
    ]
    # merged[i] tracks existing_findings[i] for i < len(existing_findings);
    # anything appended afterward is a brand-new finding needing a new row.
    new_finding_rows: list[AIFinding] = []

    verdicts = [
        ReviewerVerdict(
            reviewer="general",
            decision=ai_review.decision,  # type: ignore[arg-type]
            risk=ai_review.risk,  # type: ignore[arg-type]
            confidence=ai_review.confidence,  # type: ignore[arg-type]
        )
    ]

    for reviewer in selected:
        prompt = build_specialized_review_prompt(
            reviewer, repository, diff_snapshot, changed_files, tool_runs, repo_config,
            settings, context_snapshot,
        )
        outcome = run_reviewer_pass(
            model, prompt, changed_files_by_path, settings.ai_max_issues,
            allowed_categories=set(reviewer.categories),
        )
        _persist_specialized_review(db, ai_review, repository, reviewer, outcome)

        if outcome.status != "completed" or outcome.output is None:
            logger.warning(
                "specialized reviewer did not complete, excluded from consensus",
                extra={
                    "repository": repository.full_name,
                    "head_sha": diff_snapshot.head_sha,
                    "reviewer": reviewer.name,
                    "status": outcome.status,
                },
            )
            continue

        verdicts.append(
            ReviewerVerdict(
                reviewer=reviewer.name,
                decision=outcome.output.decision,
                risk=outcome.output.risk,
                confidence=outcome.output.confidence,
            )
        )

        for candidate in outcome.output.issues:
            specialized_reviewer_findings_total.labels(
                reviewer=reviewer.name, category=candidate.category
            ).inc()
            duplicate = next((m for m in merged if is_duplicate_finding(m, candidate)), None)
            if duplicate is not None:
                merge_finding_into(duplicate, candidate, reviewer.name)
            else:
                new_merged = MergedFinding(
                    issue=candidate.model_copy(deep=True), contributing_reviewers=[reviewer.name]
                )
                merged.append(new_merged)
                new_finding_rows.append(
                    AIFinding(
                        repository_id=repository.id,
                        ai_review_id=ai_review.id,
                        file=candidate.file,
                        start_line=candidate.start_line,
                        end_line=candidate.end_line,
                        severity=candidate.severity,
                        category=candidate.category,
                        title=candidate.title,
                        evidence=candidate.evidence,
                        recommendation=candidate.recommendation,
                        context_refs=candidate.context_refs,
                        contributing_reviewers=[reviewer.name],
                    )
                )

    for index, finding in enumerate(existing_findings):
        _apply_merged_issue(finding, merged[index])
    for offset, finding_row in enumerate(new_finding_rows):
        _apply_merged_issue(finding_row, merged[len(existing_findings) + offset])
        db.add(finding_row)

    if len(verdicts) > 1:
        aggregated = aggregate_verdicts(
            verdicts, settings.ai_specialized_disagreement_confidence_penalty
        )
        ai_review.decision = aggregated.decision
        ai_review.risk = aggregated.risk
        ai_review.confidence = aggregated.confidence
        if aggregated.disagreement:
            specialized_reviewer_disagreement_total.inc()

        specialist_summaries = "\n".join(
            f"- [{v.reviewer}] decision={v.decision}, risk={v.risk}, confidence={v.confidence:.2f}"
            for v in verdicts
        )
        ai_review.summary = (
            f"{ai_review.summary}\n\n### Specialized reviewer consensus\n{specialist_summaries}"
        )

    db.commit()
    logger.info(
        "specialized reviews completed",
        extra={
            "repository": repository.full_name,
            "head_sha": diff_snapshot.head_sha,
            "reviewers_run": [r.name for r in selected],
            "decision": ai_review.decision,
            "risk": ai_review.risk,
        },
    )
    return ai_review
