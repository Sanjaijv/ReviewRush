import json

from app.analysis.normalize import normalize_result, normalize_skipped
from app.analysis.runner import RunnerResult
from app.analysis.stages import StageSpec


def _stage(name: str = "tests", category: str = "test", required: bool = True) -> StageSpec:
    return StageSpec(name=name, category=category, required=required, image="img", command="cmd")


def _result(**overrides) -> RunnerResult:
    defaults = dict(
        exit_code=0,
        stdout="",
        stderr="",
        timed_out=False,
        errored=False,
        duration_ms=100,
        stdout_truncated=False,
        stderr_truncated=False,
    )
    defaults.update(overrides)
    return RunnerResult(**defaults)


def test_zero_exit_code_is_passed() -> None:
    normalized = normalize_result(_stage(), _result(exit_code=0))
    assert normalized.conclusion == "passed"
    assert normalized.status == "completed"
    assert normalized.exit_code == 0


def test_nonzero_exit_code_is_failed_with_summary_from_output() -> None:
    normalized = normalize_result(
        _stage(), _result(exit_code=1, stdout="collected 10 items\n2 failed, 8 passed\n")
    )
    assert normalized.conclusion == "failed"
    assert normalized.summary == "2 failed, 8 passed"


def test_timeout_is_distinguishable_from_a_failure() -> None:
    normalized = normalize_result(
        _stage(),
        _result(exit_code=None, timed_out=True, error_message="check timed out after 600s"),
    )
    assert normalized.conclusion == "timed_out"
    assert normalized.conclusion != "failed"
    assert normalized.status == "completed"
    assert normalized.exit_code is None


def test_infra_error_is_distinguishable_from_a_failure() -> None:
    normalized = normalize_result(
        _stage(),
        _result(exit_code=None, errored=True, error_message="sandbox container failed to start"),
    )
    assert normalized.conclusion == "errored"
    assert normalized.conclusion != "failed"
    assert normalized.status == "error"


def test_required_flag_is_carried_through() -> None:
    normalized = normalize_result(_stage(required=False), _result(exit_code=1))
    assert normalized.required is False


def test_semgrep_findings_produce_annotations_and_force_failed_conclusion() -> None:
    payload = {
        "results": [
            {
                "path": "src/auth.py",
                "start": {"line": 10},
                "end": {"line": 12},
                "extra": {"severity": "ERROR", "message": "SQL injection risk"},
            }
        ]
    }
    normalized = normalize_result(
        _stage(name="semgrep", category="security"),
        _result(exit_code=0, stdout=json.dumps(payload)),
    )
    assert normalized.conclusion == "failed"
    assert len(normalized.annotations) == 1
    assert normalized.annotations[0]["file"] == "src/auth.py"
    assert normalized.annotations[0]["line"] == 10
    assert normalized.annotations[0]["severity"] == "error"
    assert "1 semgrep finding" in normalized.summary


def test_semgrep_no_findings_passes() -> None:
    normalized = normalize_result(
        _stage(name="semgrep", category="security"),
        _result(exit_code=0, stdout=json.dumps({"results": []})),
    )
    assert normalized.conclusion == "passed"
    assert normalized.annotations == []


def test_semgrep_unparseable_output_does_not_raise() -> None:
    normalized = normalize_result(
        _stage(name="semgrep", category="security"),
        _result(exit_code=1, stdout="not json"),
    )
    assert normalized.conclusion == "failed"
    assert "no parseable JSON" in normalized.summary


def test_gitleaks_findings_produce_annotations_and_force_failed_conclusion() -> None:
    payload = [
        {
            "File": "config/settings.py",
            "StartLine": 3,
            "EndLine": 3,
            "RuleID": "generic-api-key",
            "Description": "Generic API Key",
        }
    ]
    normalized = normalize_result(
        _stage(name="gitleaks", category="secret"),
        _result(exit_code=0, stdout=json.dumps(payload)),
    )
    assert normalized.conclusion == "failed"
    assert normalized.annotations[0]["severity"] == "critical"
    assert "1 secret(s) detected" in normalized.summary


def test_gitleaks_empty_output_passes() -> None:
    normalized = normalize_result(
        _stage(name="gitleaks", category="secret"), _result(exit_code=0, stdout="")
    )
    assert normalized.conclusion == "passed"
    assert normalized.annotations == []


def test_normalize_skipped_carries_reason_as_summary() -> None:
    stage = StageSpec(
        name="dependency_audit",
        category="dependency",
        required=False,
        skip_reason="no recognized dependency manifest found",
    )
    normalized = normalize_skipped(stage)
    assert normalized.conclusion == "skipped"
    assert normalized.summary == "no recognized dependency manifest found"
    assert normalized.exit_code is None


def test_log_excerpt_capped_size_flag_is_carried() -> None:
    normalized = normalize_result(
        _stage(), _result(exit_code=1, stdout="x" * 10, stdout_truncated=True)
    )
    assert normalized.log_truncated is True
