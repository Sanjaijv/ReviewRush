import logging
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.orm import Session

from app.ai.model import build_review_model
from app.ai.prompt import PROMPT_VERSION, build_review_prompt
from app.ai.service import run_reviewer_pass
from app.config import Settings, get_settings
from app.evaluation.benchmark import CATEGORY_PROMPT_INJECTION
from app.evaluation.metrics import ActualFinding, ExpectedFinding, aggregate_metrics, score_case
from app.models import BenchmarkCase, EvalDatasetItem, EvalRun
from app.policy import POLICY_VERSION
from app.repo_config import RepoConfig

logger = logging.getLogger(__name__)


@dataclass
class _FakeChangedFile:
    new_path: str
    old_path: str | None
    status: str = "modified"
    additions: int = 1
    deletions: int = 1
    patch: str = ""
    excluded_from_ai: bool = False
    is_binary: bool = False
    is_submodule: bool = False
    is_generated: bool = False
    patch_truncated: bool = False


@dataclass
class _FakeDiffSnapshot:
    commits: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class _FakeRepository:
    full_name: str


class EvalTargetNotFound(Exception):
    pass


@dataclass
class _EvaluationOutcome:
    actual: list[ActualFinding]
    prompt_tokens: int
    completion_tokens: int
    latency_ms: int
    error: str | None
    # None unless `category == CATEGORY_PROMPT_INJECTION` and the model call
    # completed - whether the reviewer still surfaced its verdict correctly
    # despite the injected instruction, per Section 7's requirement to treat
    # repository content as untrusted input.
    injection_resisted: bool | None = None


def _evaluate_one(
    *,
    file_path: str,
    diff_text: str,
    expected: list[ExpectedFinding],
    category: str,
    settings: Settings,
    provider: str | None = None,
    model_name: str | None = None,
) -> _EvaluationOutcome:
    """Call a ReviewModel over one synthetic diff and return the findings it
    produced plus token/latency accounting. Uses the same `run_reviewer_pass`
    call/validate/repair loop the live pipeline uses (Phase 6/14), so a
    benchmark result reflects the exact validation rules a real review is
    held to - not a looser standalone check.

    `provider`/`model_name` default to the process-wide `settings.ai_provider`
    /`settings.ai_model` (the existing Phase 15 behavior). Passing them
    lets Phase 16 comparative evaluation score a candidate fine-tuned model
    on the same frozen benchmark/dataset without mutating global settings.
    """
    repository = _FakeRepository(full_name="benchmark/synthetic")
    diff_snapshot = _FakeDiffSnapshot(commits=[])
    changed_file = _FakeChangedFile(new_path=file_path, old_path=file_path, patch=diff_text)

    review_prompt = build_review_prompt(
        repository=repository,  # type: ignore[arg-type]
        diff_snapshot=diff_snapshot,  # type: ignore[arg-type]
        changed_files=[changed_file],  # type: ignore[list-item]
        tool_runs=[],
        repo_config=RepoConfig(),
        settings=settings,
    )
    changed_files_by_path = {file_path: changed_file}

    eval_settings = settings
    if provider is not None or model_name is not None:
        eval_settings = settings.model_copy(
            update={
                "ai_provider": provider or settings.ai_provider,
                "ai_model": model_name or settings.ai_model,
            }
        )

    model = build_review_model(eval_settings)
    if model is None:
        return _EvaluationOutcome(
            actual=[], prompt_tokens=0, completion_tokens=0, latency_ms=0,
            error=f"unknown AI provider: {eval_settings.ai_provider}",
        )

    outcome = run_reviewer_pass(
        model,
        review_prompt,
        changed_files_by_path,  # type: ignore[arg-type]
        settings.ai_max_issues,
    )
    if outcome.status != "completed" or outcome.output is None:
        return _EvaluationOutcome(
            actual=[],
            prompt_tokens=outcome.prompt_tokens,
            completion_tokens=outcome.completion_tokens,
            latency_ms=outcome.latency_ms,
            error=outcome.error_message or f"reviewer status={outcome.status}",
        )

    actual = [
        ActualFinding(category=issue.category, severity=issue.severity, start_line=issue.start_line)
        for issue in outcome.output.issues
    ]
    injection_resisted = (
        outcome.output.decision != "approve" if category == CATEGORY_PROMPT_INJECTION else None
    )

    return _EvaluationOutcome(
        actual=actual,
        prompt_tokens=outcome.prompt_tokens,
        completion_tokens=outcome.completion_tokens,
        latency_ms=outcome.latency_ms,
        error=None,
        injection_resisted=injection_resisted,
    )


def run_benchmark_eval(
    db: Session,
    *,
    actor_user_id: int | None = None,
    actor_login: str | None = None,
    provider: str | None = None,
    model_name: str | None = None,
) -> EvalRun:
    """Run the fixed benchmark (Phase 15) against a provider/model and
    persist one immutable EvalRun. Defaults to the currently configured AI
    provider/model; passing `provider`/`model_name` scores a different
    candidate (e.g. a Phase 16 fine-tuned model) on the same frozen
    benchmark without changing global settings.
    `app.evaluation.benchmark.load_fixed_benchmark_cases` must have been run
    at least once first - an empty/missing benchmark table is not silently
    treated as a pass.
    """
    settings = get_settings()
    cases = db.query(BenchmarkCase).filter_by(is_active=True).all()
    if not cases:
        raise EvalTargetNotFound("no active benchmark cases loaded")

    results = []
    for case in cases:
        expected = [ExpectedFinding.from_dict(d) for d in case.expected_findings]
        outcome = _evaluate_one(
            file_path=case.file_path,
            diff_text=case.diff_text,
            expected=expected,
            category=case.category,
            settings=settings,
            provider=provider,
            model_name=model_name,
        )
        result = score_case(
            case.slug,
            expected,
            outcome.actual,
            latency_ms=outcome.latency_ms,
            prompt_tokens=outcome.prompt_tokens,
            completion_tokens=outcome.completion_tokens,
            injection_resisted=outcome.injection_resisted,
        )
        result.error = outcome.error
        results.append(result)

    metrics = aggregate_metrics(results)
    metrics["per_case"] = {
        r.slug: {
            "true_positives": r.true_positives,
            "false_positives": r.false_positives,
            "false_negatives": r.false_negatives,
            "error": r.error,
        }
        for r in results
    }

    run = EvalRun(
        run_type="benchmark",
        dataset_version_id=None,
        provider=provider or settings.ai_provider,
        model=model_name or settings.ai_model,
        prompt_version=PROMPT_VERSION,
        policy_version=POLICY_VERSION,
        status="completed",
        case_count=len(results),
        metrics=metrics,
        actor_user_id=actor_user_id,
        actor_login=actor_login,
    )
    db.add(run)
    db.commit()
    db.refresh(run)
    return run


def run_dataset_eval(
    db: Session,
    dataset_version_id: int,
    *,
    actor_user_id: int | None = None,
    actor_login: str | None = None,
    provider: str | None = None,
    model_name: str | None = None,
) -> EvalRun:
    """Run an EvalDatasetVersion's items (Phase 15) against a provider/model,
    persisting one immutable EvalRun. Defaults to the currently configured
    provider/model; see `run_benchmark_eval` for the override use case.
    """
    settings = get_settings()
    items = db.query(EvalDatasetItem).filter_by(dataset_version_id=dataset_version_id).all()
    if not items:
        raise EvalTargetNotFound(f"eval dataset version {dataset_version_id} has no items")

    results = []
    for item in items:
        expected = [ExpectedFinding.from_dict(d) for d in item.expected_findings]
        outcome = _evaluate_one(
            file_path="dataset_item.diff",
            diff_text=item.diff_text,
            expected=expected,
            category=item.category,
            settings=settings,
            provider=provider,
            model_name=model_name,
        )
        result = score_case(
            str(item.id),
            expected,
            outcome.actual,
            latency_ms=outcome.latency_ms,
            prompt_tokens=outcome.prompt_tokens,
            completion_tokens=outcome.completion_tokens,
            injection_resisted=outcome.injection_resisted,
        )
        result.error = outcome.error
        results.append(result)

    metrics = aggregate_metrics(results)
    run = EvalRun(
        run_type="dataset",
        dataset_version_id=dataset_version_id,
        provider=provider or settings.ai_provider,
        model=model_name or settings.ai_model,
        prompt_version=PROMPT_VERSION,
        policy_version=POLICY_VERSION,
        status="completed",
        case_count=len(results),
        metrics=metrics,
        actor_user_id=actor_user_id,
        actor_login=actor_login,
    )
    db.add(run)
    db.commit()
    db.refresh(run)
    return run
