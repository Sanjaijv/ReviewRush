from unittest.mock import MagicMock

import pytest

from app.config import Settings
from app.finetune.comparison import EvalRunNotFound, compare_to_baseline
from app.models import EvalRun


def _settings(**overrides) -> Settings:
    defaults = dict(
        finetune_max_recall_regression=0.05, finetune_max_false_positive_rate_increase=0.5
    )
    defaults.update(overrides)
    return Settings(**defaults)


def _run(run_id: int, metrics: dict) -> EvalRun:
    return EvalRun(
        id=run_id, run_type="benchmark", provider="ollama", model="m",
        prompt_version="1", policy_version="1", status="completed", metrics=metrics,
    )


def test_compare_raises_when_candidate_missing() -> None:
    db = MagicMock()
    db.get.side_effect = lambda model, id_: None if id_ == 1 else _run(2, {})
    with pytest.raises(EvalRunNotFound):
        compare_to_baseline(db, candidate_run_id=1, baseline_run_id=2, settings=_settings())


def test_compare_raises_when_baseline_missing() -> None:
    db = MagicMock()
    db.get.side_effect = lambda model, id_: _run(1, {}) if id_ == 1 else None
    with pytest.raises(EvalRunNotFound):
        compare_to_baseline(db, candidate_run_id=1, baseline_run_id=2, settings=_settings())


def test_compare_passes_when_metrics_improve_or_match() -> None:
    db = MagicMock()
    candidate = _run(1, {"recall": 0.95, "false_positive_rate": 0.1})
    baseline = _run(2, {"recall": 0.9, "false_positive_rate": 0.1})
    db.get.side_effect = lambda model, id_: candidate if id_ == 1 else baseline

    result = compare_to_baseline(db, candidate_run_id=1, baseline_run_id=2, settings=_settings())

    assert result.passes_regression_guardrail is True
    assert result.reasons == []
    assert result.recall_delta == pytest.approx(0.05)


def test_compare_fails_on_recall_regression_beyond_threshold() -> None:
    db = MagicMock()
    candidate = _run(1, {"recall": 0.5, "false_positive_rate": 0.1})
    baseline = _run(2, {"recall": 0.9, "false_positive_rate": 0.1})
    db.get.side_effect = lambda model, id_: candidate if id_ == 1 else baseline

    result = compare_to_baseline(
        db, candidate_run_id=1, baseline_run_id=2,
        settings=_settings(finetune_max_recall_regression=0.05),
    )

    assert result.passes_regression_guardrail is False
    assert any("recall regressed" in r for r in result.reasons)


def test_compare_fails_on_false_positive_rate_increase_beyond_threshold() -> None:
    db = MagicMock()
    candidate = _run(1, {"recall": 0.9, "false_positive_rate": 5.0})
    baseline = _run(2, {"recall": 0.9, "false_positive_rate": 0.1})
    db.get.side_effect = lambda model, id_: candidate if id_ == 1 else baseline

    result = compare_to_baseline(
        db, candidate_run_id=1, baseline_run_id=2,
        settings=_settings(finetune_max_false_positive_rate_increase=0.5),
    )

    assert result.passes_regression_guardrail is False
    assert any("false-positive rate increased" in r for r in result.reasons)


def test_compare_flags_missing_metrics() -> None:
    db = MagicMock()
    candidate = _run(1, {})
    baseline = _run(2, {"recall": 0.9, "false_positive_rate": 0.1})
    db.get.side_effect = lambda model, id_: candidate if id_ == 1 else baseline

    result = compare_to_baseline(db, candidate_run_id=1, baseline_run_id=2, settings=_settings())

    assert result.passes_regression_guardrail is False
    assert any("recall missing" in r for r in result.reasons)
