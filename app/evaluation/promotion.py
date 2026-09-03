from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import EvalRun, ModelPromotion


class EvalRunNotFound(Exception):
    pass


class BenchmarkThresholdNotMet(Exception):
    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


def promote_configuration(
    db: Session,
    *,
    eval_run_id: int,
    actor_user_id: int,
    actor_login: str,
    notes: str = "",
) -> ModelPromotion:
    """Mark one provider/model/prompt/policy combination as approved for
    production use.

    This is the only function that may create a ModelPromotion row, and it
    always requires a completed EvalRun whose `precision`/`recall` meet the
    configured minimum thresholds - the concrete enforcement behind the
    Phase 15 acceptance criterion "model or prompt changes cannot be
    promoted without benchmark results". Never insert a ModelPromotion row
    directly from anywhere else; always go through this function.
    """
    settings = get_settings()
    run = db.get(EvalRun, eval_run_id)
    if run is None:
        raise EvalRunNotFound(eval_run_id)
    if run.status != "completed":
        raise BenchmarkThresholdNotMet(
            f"eval run {eval_run_id} did not complete (status={run.status})"
        )

    precision = run.metrics.get("precision")
    recall = run.metrics.get("recall")
    if precision is None or precision < settings.eval_promotion_min_precision:
        raise BenchmarkThresholdNotMet(
            f"precision {precision} below minimum {settings.eval_promotion_min_precision}"
        )
    if recall is None or recall < settings.eval_promotion_min_recall:
        raise BenchmarkThresholdNotMet(
            f"recall {recall} below minimum {settings.eval_promotion_min_recall}"
        )

    promotion = ModelPromotion(
        eval_run_id=run.id,
        provider=run.provider,
        model=run.model,
        prompt_version=run.prompt_version,
        policy_version=run.policy_version,
        notes=notes,
        actor_user_id=actor_user_id,
        actor_login=actor_login,
    )
    db.add(promotion)
    db.commit()
    db.refresh(promotion)
    return promotion


def get_active_promotion(db: Session) -> ModelPromotion | None:
    """The most recently promoted configuration - purely informational.
    Nothing in the live review pipeline consults this yet; wiring an
    enforcement gate into `app.ai.service` is a follow-up beyond this
    phase's scope, not a silent gap in it.
    """
    return db.query(ModelPromotion).order_by(ModelPromotion.created_at.desc()).first()
