"""Compares a candidate model's benchmark `EvalRun` against a baseline
`EvalRun`, enforcing the Phase 16 acceptance criterion that a fine-tuned
model "does not materially worsen security recall or false-positive rate."

This is a guardrail layered on top of - not a replacement for - the
unchanged Phase 15 `app.evaluation.promotion.promote_configuration` floor:
a candidate must still independently clear
`eval_promotion_min_precision`/`eval_promotion_min_recall` on its own
metrics, and now also must not regress materially versus the baseline it is
meant to replace.
"""

from dataclasses import dataclass
from typing import Any

from sqlalchemy.orm import Session

from app.config import Settings
from app.models import EvalRun


class EvalRunNotFound(Exception):
    pass


@dataclass(frozen=True)
class ComparisonResult:
    candidate_run_id: int
    baseline_run_id: int
    candidate_metrics: dict[str, Any]
    baseline_metrics: dict[str, Any]
    recall_delta: float | None
    false_positive_rate_delta: float | None
    passes_regression_guardrail: bool
    reasons: list[str]


def compare_to_baseline(
    db: Session, *, candidate_run_id: int, baseline_run_id: int, settings: Settings
) -> ComparisonResult:
    candidate = db.get(EvalRun, candidate_run_id)
    baseline = db.get(EvalRun, baseline_run_id)
    if candidate is None:
        raise EvalRunNotFound(candidate_run_id)
    if baseline is None:
        raise EvalRunNotFound(baseline_run_id)

    candidate_recall = candidate.metrics.get("recall")
    baseline_recall = baseline.metrics.get("recall")
    candidate_fp_rate = candidate.metrics.get("false_positive_rate")
    baseline_fp_rate = baseline.metrics.get("false_positive_rate")

    reasons: list[str] = []
    recall_delta = None
    if candidate_recall is not None and baseline_recall is not None:
        recall_delta = candidate_recall - baseline_recall
        if recall_delta < -settings.finetune_max_recall_regression:
            reasons.append(
                f"recall regressed by {-recall_delta:.3f}, "
                f"exceeding the allowed {settings.finetune_max_recall_regression:.3f}"
            )
    else:
        reasons.append("recall missing on candidate or baseline run")

    fp_rate_delta = None
    if candidate_fp_rate is not None and baseline_fp_rate is not None:
        fp_rate_delta = candidate_fp_rate - baseline_fp_rate
        allowed_increase = settings.finetune_max_false_positive_rate_increase
        if fp_rate_delta > allowed_increase and fp_rate_delta > 0:
            reasons.append(
                f"false-positive rate increased by {fp_rate_delta:.3f}, "
                f"exceeding the allowed {allowed_increase:.3f}"
            )
    else:
        reasons.append("false_positive_rate missing on candidate or baseline run")

    return ComparisonResult(
        candidate_run_id=candidate_run_id,
        baseline_run_id=baseline_run_id,
        candidate_metrics=candidate.metrics,
        baseline_metrics=baseline.metrics,
        recall_delta=recall_delta,
        false_positive_rate_delta=fp_rate_delta,
        passes_regression_guardrail=not reasons,
        reasons=reasons,
    )
