from unittest.mock import MagicMock

import pytest

from app.evaluation.promotion import (
    BenchmarkThresholdNotMet,
    EvalRunNotFound,
    get_active_promotion,
    promote_configuration,
)
from app.models import EvalRun, ModelPromotion


def _run(**overrides) -> EvalRun:
    defaults = dict(
        id=1, run_type="benchmark", provider="ollama", model="qwen2.5-coder:7b",
        prompt_version="1", policy_version="1", status="completed",
        metrics={"precision": 0.9, "recall": 0.9},
    )
    defaults.update(overrides)
    return EvalRun(**defaults)


def test_promote_configuration_raises_when_run_not_found() -> None:
    db = MagicMock()
    db.get.return_value = None

    with pytest.raises(EvalRunNotFound):
        promote_configuration(db, eval_run_id=1, actor_user_id=1, actor_login="octocat")

    db.add.assert_not_called()


def test_promote_configuration_raises_when_run_not_completed() -> None:
    db = MagicMock()
    db.get.return_value = _run(status="error")

    with pytest.raises(BenchmarkThresholdNotMet):
        promote_configuration(db, eval_run_id=1, actor_user_id=1, actor_login="octocat")

    db.add.assert_not_called()


def test_promote_configuration_raises_when_precision_below_minimum() -> None:
    db = MagicMock()
    db.get.return_value = _run(metrics={"precision": 0.1, "recall": 0.9})

    with pytest.raises(BenchmarkThresholdNotMet):
        promote_configuration(db, eval_run_id=1, actor_user_id=1, actor_login="octocat")

    db.add.assert_not_called()


def test_promote_configuration_raises_when_recall_below_minimum() -> None:
    db = MagicMock()
    db.get.return_value = _run(metrics={"precision": 0.9, "recall": 0.1})

    with pytest.raises(BenchmarkThresholdNotMet):
        promote_configuration(db, eval_run_id=1, actor_user_id=1, actor_login="octocat")

    db.add.assert_not_called()


def test_promote_configuration_raises_when_metrics_missing() -> None:
    db = MagicMock()
    db.get.return_value = _run(metrics={})

    with pytest.raises(BenchmarkThresholdNotMet):
        promote_configuration(db, eval_run_id=1, actor_user_id=1, actor_login="octocat")


def test_promote_configuration_succeeds_when_thresholds_met() -> None:
    db = MagicMock()
    run = _run()
    db.get.return_value = run

    promotion = promote_configuration(
        db, eval_run_id=1, actor_user_id=1, actor_login="octocat", notes="looks good"
    )

    added = [c.args[0] for c in db.add.call_args_list if isinstance(c.args[0], ModelPromotion)]
    assert added == [promotion]
    assert promotion.eval_run_id == run.id
    assert promotion.provider == run.provider
    assert promotion.prompt_version == run.prompt_version
    db.commit.assert_called_once()


def test_get_active_promotion_returns_latest() -> None:
    db = MagicMock()
    latest = ModelPromotion(
        id=2, eval_run_id=1, provider="ollama", model="m",
        prompt_version="1", policy_version="1", actor_user_id=1, actor_login="a",
    )
    db.query.return_value.order_by.return_value.first.return_value = latest

    assert get_active_promotion(db) is latest


def test_get_active_promotion_returns_none_when_nothing_promoted() -> None:
    db = MagicMock()
    db.query.return_value.order_by.return_value.first.return_value = None

    assert get_active_promotion(db) is None
