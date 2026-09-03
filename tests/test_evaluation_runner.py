from unittest.mock import MagicMock, patch

import pytest

from app.ai.model import ModelResponse
from app.ai.prompt import PROMPT_VERSION
from app.evaluation.runner import EvalTargetNotFound, run_benchmark_eval, run_dataset_eval
from app.models import BenchmarkCase, EvalDatasetItem, EvalRun
from app.policy import POLICY_VERSION


class _FakeModel:
    def __init__(self, responses: list[ModelResponse]) -> None:
        self._responses = list(responses)
        self.calls = 0

    def generate(self, *, system, messages):
        self.calls += 1
        return self._responses.pop(0)


def _known_bug_case() -> BenchmarkCase:
    return BenchmarkCase(
        id=1,
        slug="known-bug-off-by-one-pagination",
        category="known_bug",
        description="off by one",
        file_path="src/pagination.py",
        diff_text=(
            "@@ -1,4 +1,4 @@\n"
            " def get_page_items(items, page_size, page_number):\n"
            "     start = page_number * page_size\n"
            "-    end = start + page_size\n"
            "+    end = start + page_size - 1\n"
            "     return items[start:end]"
        ),
        expected_findings=[{"category": "correctness", "severity": "medium", "line": 3}],
        is_active=True,
    )


def _valid_response(correct: bool, file_path: str = "src/pagination.py") -> ModelResponse:
    issues = []
    if correct:
        issues = [
            {
                "file": file_path,
                "start_line": 3,
                "end_line": 3,
                "severity": "medium",
                "category": "correctness",
                "title": "off by one",
                "evidence": "end = start + page_size - 1 excludes the last item",
                "recommendation": "remove the -1",
            }
        ]
    content = {
        "summary": "found an off-by-one" if correct else "looks fine",
        "risk": "medium" if correct else "low",
        "confidence": 0.9,
        "decision": "request_changes" if correct else "approve",
        "issues": issues,
    }
    return ModelResponse(
        content=content, raw_text="{}", prompt_tokens=100, completion_tokens=50, latency_ms=250
    )


def test_run_benchmark_eval_raises_when_no_cases_loaded() -> None:
    db = MagicMock()
    db.query.return_value.filter_by.return_value.all.return_value = []

    with pytest.raises(EvalTargetNotFound):
        run_benchmark_eval(db)


def test_run_benchmark_eval_scores_correct_model_output_as_true_positive() -> None:
    db = MagicMock()
    db.query.return_value.filter_by.return_value.all.return_value = [_known_bug_case()]

    with patch(
        "app.evaluation.runner.build_review_model",
        return_value=_FakeModel([_valid_response(correct=True)]),
    ):
        run = run_benchmark_eval(db, actor_user_id=1, actor_login="octocat")

    assert run.status == "completed"
    assert run.case_count == 1
    assert run.prompt_version == PROMPT_VERSION
    assert run.policy_version == POLICY_VERSION
    assert run.metrics["true_positives"] == 1
    assert run.metrics["false_positives"] == 0
    assert run.metrics["precision"] == 1.0
    assert run.metrics["recall"] == 1.0
    db.add.assert_any_call(run)


def test_run_benchmark_eval_scores_missed_bug_as_false_negative() -> None:
    db = MagicMock()
    db.query.return_value.filter_by.return_value.all.return_value = [_known_bug_case()]

    with patch(
        "app.evaluation.runner.build_review_model",
        return_value=_FakeModel([_valid_response(correct=False)]),
    ):
        run = run_benchmark_eval(db)

    assert run.metrics["true_positives"] == 0
    assert run.metrics["false_negatives"] == 1
    assert run.metrics["recall"] == 0.0


def test_run_benchmark_eval_records_error_when_provider_unknown() -> None:
    db = MagicMock()
    db.query.return_value.filter_by.return_value.all.return_value = [_known_bug_case()]

    with patch("app.evaluation.runner.build_review_model", return_value=None):
        run = run_benchmark_eval(db)

    assert run.metrics["errored_cases"] == 1
    assert run.metrics["case_count"] == 1


def test_run_dataset_eval_raises_when_dataset_has_no_items() -> None:
    db = MagicMock()
    db.query.return_value.filter_by.return_value.all.return_value = []

    with pytest.raises(EvalTargetNotFound):
        run_dataset_eval(db, dataset_version_id=1)


def test_run_dataset_eval_scores_items() -> None:
    db = MagicMock()
    item = EvalDatasetItem(
        id=1, dataset_version_id=1, category="security", repository_ref="repo-abc",
        diff_text=_known_bug_case().diff_text,
        expected_findings=[{"category": "correctness", "severity": "medium", "line": 3}],
    )
    db.query.return_value.filter_by.return_value.all.return_value = [item]

    with patch(
        "app.evaluation.runner.build_review_model",
        return_value=_FakeModel([_valid_response(correct=True, file_path="dataset_item.diff")]),
    ):
        run = run_dataset_eval(db, dataset_version_id=1)

    assert isinstance(run, EvalRun)
    assert run.run_type == "dataset"
    assert run.dataset_version_id == 1
    assert run.metrics["true_positives"] == 1
