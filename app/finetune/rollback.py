"""Immediate rollback of the active promoted model configuration (Phase 16
acceptance criterion: "rollback to the previous model is immediate").

`ModelPromotion` rows are additive and immutable (see
`app.evaluation.promotion`), and `get_active_promotion` always reads the
most recently created row. Rollback therefore does not delete or mutate
anything - it re-promotes the configuration from the second-most-recent
`ModelPromotion` as a brand new latest row, so `get_active_promotion`
reflects the rollback immediately and the full promotion history (including
the row being rolled back from) stays intact for audit.
"""

from sqlalchemy.orm import Session

from app.models import ModelPromotion


class NoPromotionToRollBackTo(Exception):
    pass


def rollback_active_promotion(
    db: Session, *, actor_user_id: int, actor_login: str, notes: str = ""
) -> ModelPromotion:
    promotions = (
        db.query(ModelPromotion).order_by(ModelPromotion.created_at.desc()).limit(2).all()
    )
    if len(promotions) < 2:
        raise NoPromotionToRollBackTo(
            "no prior promotion exists to roll back to - the active promotion "
            "is the only one on record"
        )

    _current, previous = promotions
    rollback_row = ModelPromotion(
        eval_run_id=previous.eval_run_id,
        provider=previous.provider,
        model=previous.model,
        prompt_version=previous.prompt_version,
        policy_version=previous.policy_version,
        notes=notes or f"rollback to promotion {previous.id}",
        actor_user_id=actor_user_id,
        actor_login=actor_login,
    )
    db.add(rollback_row)
    db.commit()
    db.refresh(rollback_row)
    return rollback_row
