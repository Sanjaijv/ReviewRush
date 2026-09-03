import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy.exc import IntegrityError

from app.ai.model import ModelResponse, ReviewModel, build_review_model
from app.ai.prompt import ReviewPrompt, build_repair_messages, build_review_prompt
from app.ai.schema import AIReviewOutput
from app.ai.validation import validate_review_output
from app.config import get_settings
from app.context.service import build_repository_context_for_snapshot
from app.github.auth import get_installation_access_token
from app.github.client import GitHubClient
from app.models import AIFinding, AIReview, ChangedFile, DiffSnapshot, Repository, ToolRun
from app.observability.metrics import (
    model_call_failures_total,
    quota_rejections_total,
    review_stage_duration_seconds,
)
from app.repo_config import parse_repo_config
from app.tenancy.plans import resolve_limits
from app.tenancy.provisioning import get_or_create_organization

logger = logging.getLogger(__name__)

REPO_CONFIG_PATH = ".reviewrush.yml"
_MAX_REPAIR_ATTEMPTS = 1


@dataclass
class ReviewerOutcome:
    """Result of running one reviewer (general or specialized, Phase 14)
    through the shared call/validate/repair loop, before persistence.
    """

    status: str  # "completed" | "invalid_output" | "error"
    output: AIReviewOutput | None
    prompt_tokens: int
    completion_tokens: int
    latency_ms: int
    attempt_count: int
    error_message: str | None


def _quota_exceeded(db: Any, repository: Repository) -> str | None:
    """Phase 13 cost/quota limiting, extended in Phase 17 with a per-
    organization plan limit. Returns the scope that was exceeded
    ("repository", "installation", or "organization"), or None if within
    all configured quotas.

    Counts completed-or-attempted AIReview rows in the trailing 24 hours -
    every status counts (not just "completed"), since a failed/invalid
    model call still cost tokens and API quota, and a quota is meant to cap
    that spend regardless of whether the call succeeded.
    """
    settings = get_settings()
    if not settings.quota_enabled:
        return None

    since = datetime.now(UTC) - timedelta(days=1)
    repository_count = (
        db.query(AIReview)
        .filter(AIReview.repository_id == repository.id, AIReview.created_at >= since)
        .count()
    )
    if repository_count >= settings.quota_max_ai_reviews_per_repository_per_day:
        return "repository"

    installation_repository_ids = [r.id for r in repository.installation.repositories]
    installation_count = (
        db.query(AIReview)
        .filter(
            AIReview.repository_id.in_(installation_repository_ids), AIReview.created_at >= since
        )
        .count()
    )
    if installation_count >= settings.quota_max_ai_reviews_per_installation_per_day:
        return "installation"

    # Phase 17 per-organization plan limit, layered on top of the existing
    # repository/installation quotas above rather than replacing them - an
    # organization can only ever be *more* restricted than its plan by
    # tightening these settings, never less restricted than the global
    # quota by raising its plan. Like the checks above, exceeding this only
    # skips the AI model call (status="quota_exceeded" below), which the
    # Phase 7 policy engine already treats as HUMAN_REVIEW - it never
    # disables `analysis_semgrep_required`/`analysis_gitleaks_required` or
    # any other mandatory safety check, and it can never widen auto-merge
    # eligibility.
    organization = get_or_create_organization(db, repository.installation)
    limits = resolve_limits(organization)
    if limits.max_ai_reviews_per_day is not None:
        organization_repository_ids = [r.id for r in organization.installation.repositories]
        organization_count = (
            db.query(AIReview)
            .filter(
                AIReview.repository_id.in_(organization_repository_ids),
                AIReview.created_at >= since,
            )
            .count()
        )
        if organization_count >= limits.max_ai_reviews_per_day:
            return "organization"

    return None


def _existing_ai_review(db: Any, diff_snapshot_id: int) -> AIReview | None:
    return db.query(AIReview).filter_by(diff_snapshot_id=diff_snapshot_id).one_or_none()


def _persist(
    db: Any,
    repository: Repository,
    diff_snapshot: DiffSnapshot,
    *,
    status: str,
    output: AIReviewOutput | None,
    provider: str,
    model_name: str,
    prompt_tokens: int,
    completion_tokens: int,
    latency_ms: int,
    attempt_count: int,
    error_message: str | None,
) -> AIReview:
    review = AIReview(
        repository_id=repository.id,
        diff_snapshot_id=diff_snapshot.id,
        status=status,
        decision=output.decision if output else None,
        risk=output.risk if output else None,
        confidence=output.confidence if output else None,
        summary=output.summary if output else "",
        provider=provider,
        model=model_name,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        latency_ms=latency_ms,
        attempt_count=attempt_count,
        error_message=error_message,
    )
    if output:
        review.findings = [
            AIFinding(
                repository_id=repository.id,
                file=issue.file,
                start_line=issue.start_line,
                end_line=issue.end_line,
                severity=issue.severity,
                category=issue.category,
                title=issue.title,
                evidence=issue.evidence,
                recommendation=issue.recommendation,
                context_refs=issue.context_refs,
                contributing_reviewers=["general"],
            )
            for issue in output.issues
        ]

    review_stage_duration_seconds.labels(stage="ai_review", outcome=status).observe(
        latency_ms / 1000
    )
    if status != "completed":
        model_call_failures_total.labels(provider=provider, status=status).inc()

    db.add(review)
    try:
        db.commit()
    except IntegrityError:
        # Another worker already reviewed this head_sha - AIReview rows are
        # immutable per diff_snapshot, so defer to the existing row.
        db.rollback()
        existing = _existing_ai_review(db, diff_snapshot.id)
        assert existing is not None
        return existing
    return review


def _call_model(model: ReviewModel, system: str, messages: list[dict[str, str]]) -> ModelResponse:
    try:
        return model.generate(system=system, messages=messages)
    except Exception as exc:  # a provider bug must never crash the pipeline
        logger.exception("review model call raised unexpectedly")
        return ModelResponse(
            content=None, raw_text="", prompt_tokens=0, completion_tokens=0, latency_ms=0,
            error=str(exc),
        )


def run_reviewer_pass(
    model: ReviewModel,
    review_prompt: ReviewPrompt,
    changed_files_by_path: dict[str, ChangedFile],
    max_issues: int,
    allowed_categories: set[str] | None = None,
) -> ReviewerOutcome:
    """Call `model` for one reviewer, repairing once on invalid output.

    Shared by the general reviewer (Phase 6) and every specialized reviewer
    (Phase 14) - the only difference between them is the prompt passed in
    and, for a specialist, `allowed_categories` restricting which finding
    categories validation will accept.
    """
    messages: list[dict[str, str]] = [{"role": "user", "content": review_prompt.user}]
    prompt_tokens = 0
    completion_tokens = 0
    latency_ms = 0
    attempt = 0
    last_errors: list[str] = []
    last_response: ModelResponse | None = None

    while attempt <= _MAX_REPAIR_ATTEMPTS:
        attempt += 1
        response = _call_model(model, review_prompt.system, messages)
        last_response = response
        prompt_tokens += response.prompt_tokens
        completion_tokens += response.completion_tokens
        latency_ms += response.latency_ms

        if response.error is not None:
            last_errors = [response.error]
        else:
            output, errors = validate_review_output(
                response.content, review_prompt.valid_file_paths, changed_files_by_path,
                max_issues, review_prompt.valid_context_ids, allowed_categories,
            )
            if output is not None:
                return ReviewerOutcome(
                    status="completed", output=output,
                    prompt_tokens=prompt_tokens, completion_tokens=completion_tokens,
                    latency_ms=latency_ms, attempt_count=attempt, error_message=None,
                )
            last_errors = errors

        if attempt <= _MAX_REPAIR_ATTEMPTS:
            messages = build_repair_messages(
                review_prompt.user, last_response.raw_text, last_errors
            )

    status = "error" if last_response is not None and last_response.error else "invalid_output"
    return ReviewerOutcome(
        status=status, output=None,
        prompt_tokens=prompt_tokens, completion_tokens=completion_tokens,
        latency_ms=latency_ms, attempt_count=attempt,
        error_message="; ".join(last_errors) if last_errors else None,
    )


def run_ai_review_for_snapshot(
    db: Any, repository: Repository, diff_snapshot: DiffSnapshot
) -> AIReview | None:
    """Run the single AI reviewer for one immutable diff snapshot.

    Idempotent per diff_snapshot: an existing AIReview row is returned
    unchanged and the model is never called again for the same head_sha.
    Returns None (no row created) when the feature is disabled, mirroring
    `run_analysis_pipeline`'s sandbox-disabled short-circuit.
    """
    settings = get_settings()
    if not settings.ai_review_enabled:
        logger.info(
            "AI review disabled, skipping",
            extra={"repository": repository.full_name, "head_sha": diff_snapshot.head_sha},
        )
        return None

    existing = _existing_ai_review(db, diff_snapshot.id)
    if existing is not None:
        return existing

    exceeded_scope = _quota_exceeded(db, repository)
    if exceeded_scope is not None:
        quota_rejections_total.labels(scope=exceeded_scope).inc()
        logger.warning(
            "AI review quota exceeded, skipping model call",
            extra={
                "repository": repository.full_name,
                "head_sha": diff_snapshot.head_sha,
                "scope": exceeded_scope,
            },
        )
        return _persist(
            db, repository, diff_snapshot,
            status="quota_exceeded", output=None,
            provider=settings.ai_provider, model_name=settings.ai_model,
            prompt_tokens=0, completion_tokens=0, latency_ms=0, attempt_count=0,
            error_message=f"{exceeded_scope} AI review quota exceeded for the trailing 24 hours",
        )

    installation = repository.installation
    token = get_installation_access_token(installation.github_installation_id)

    with GitHubClient(token) as client:
        config_yaml = client.get_file_contents(
            repository.owner, repository.name, REPO_CONFIG_PATH, ref=diff_snapshot.head_sha
        )
        repo_config = parse_repo_config(config_yaml)

    changed_files = list(diff_snapshot.changed_files)
    tool_runs = db.query(ToolRun).filter_by(diff_snapshot_id=diff_snapshot.id).all()
    context_snapshot = build_repository_context_for_snapshot(db, repository, diff_snapshot)

    review_prompt = build_review_prompt(
        repository=repository,
        diff_snapshot=diff_snapshot,
        changed_files=changed_files,
        tool_runs=tool_runs,
        repo_config=repo_config,
        settings=settings,
        context_snapshot=context_snapshot,
    )
    changed_files_by_path = {
        (f.new_path or f.old_path or ""): f for f in changed_files
    }

    organization = get_or_create_organization(db, installation)
    effective_provider = organization.ai_provider_override or settings.ai_provider
    effective_model = organization.ai_model_override or settings.ai_model

    model = build_review_model(settings, provider=effective_provider, model_name=effective_model)
    if model is None:
        return _persist(
            db, repository, diff_snapshot,
            status="error", output=None,
            provider=effective_provider, model_name=effective_model,
            prompt_tokens=0, completion_tokens=0, latency_ms=0, attempt_count=0,
            error_message=f"unknown AI provider: {effective_provider}",
        )

    outcome = run_reviewer_pass(model, review_prompt, changed_files_by_path, settings.ai_max_issues)
    return _persist(
        db, repository, diff_snapshot,
        status=outcome.status, output=outcome.output,
        provider=effective_provider, model_name=effective_model,
        prompt_tokens=outcome.prompt_tokens, completion_tokens=outcome.completion_tokens,
        latency_ms=outcome.latency_ms, attempt_count=outcome.attempt_count,
        error_message=outcome.error_message,
    )
