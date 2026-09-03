from unittest.mock import MagicMock

import pytest

from app.finetune.rollback import NoPromotionToRollBackTo, rollback_active_promotion
from app.models import ModelPromotion


def _promotion(**overrides) -> ModelPromotion:
    defaults = dict(
        id=1, eval_run_id=1, provider="ollama", model="qwen2.5-coder:7b",
        prompt_version="1", policy_version="1", actor_user_id=1, actor_login="a",
    )
    defaults.update(overrides)
    return ModelPromotion(**defaults)


def test_rollback_raises_when_no_prior_promotion() -> None:
    db = MagicMock()
    db.query.return_value.order_by.return_value.limit.return_value.all.return_value = [
        _promotion(id=1)
    ]
    with pytest.raises(NoPromotionToRollBackTo):
        rollback_active_promotion(db, actor_user_id=1, actor_login="a")
    db.add.assert_not_called()


def test_rollback_raises_when_no_promotion_at_all() -> None:
    db = MagicMock()
    db.query.return_value.order_by.return_value.limit.return_value.all.return_value = []
    with pytest.raises(NoPromotionToRollBackTo):
        rollback_active_promotion(db, actor_user_id=1, actor_login="a")


def test_rollback_repromotes_previous_configuration() -> None:
    db = MagicMock()
    current = _promotion(id=2, eval_run_id=2, model="reviewrush-finetune-9")
    previous = _promotion(id=1, eval_run_id=1, model="qwen2.5-coder:7b")
    db.query.return_value.order_by.return_value.limit.return_value.all.return_value = [
        current, previous,
    ]

    rollback_row = rollback_active_promotion(
        db, actor_user_id=1, actor_login="a", notes="reverting bad candidate"
    )

    assert rollback_row.eval_run_id == previous.eval_run_id
    assert rollback_row.model == previous.model
    assert rollback_row.notes == "reverting bad candidate"
    db.add.assert_called_once_with(rollback_row)
    db.commit.assert_called_once()
