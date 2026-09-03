from contextlib import contextmanager
from pathlib import Path
from unittest.mock import MagicMock, patch

from app.analysis.pipeline import run_analysis_pipeline
from app.analysis.runner import RunnerResult
from app.config import Settings
from app.models import DiffSnapshot, ToolRun
from app.repo_config import parse_repo_config


class _FakeRepository:
    def __init__(self) -> None:
        self.id = 1
        self.owner = "acme"
        self.name = "widgets"
        self.full_name = "acme/widgets"


class _FakeRunner:
    def __init__(self, result: RunnerResult) -> None:
        self.result = result
        self.calls: list[dict] = []

    def run(self, **kwargs):
        self.calls.append(kwargs)
        return self.result


def _settings(**overrides) -> Settings:
    base = dict(
        analysis_sandbox_enabled=True,
        analysis_semgrep_enabled=False,
        analysis_gitleaks_enabled=False,
        analysis_dependency_scan_enabled=False,
    )
    base.update(overrides)
    return Settings(**base)


def _db_with_no_existing_tool_runs() -> MagicMock:
    db = MagicMock()
    db.query.return_value.filter_by.return_value.all.return_value = []
    return db


def _fake_workspace_for(tmp_path):
    from app.analysis.workspace import Workspace

    @contextmanager
    def _ctx(client, repository, head_sha):
        yield Workspace(run_subdir="run-1", host_path=tmp_path)

    return _ctx


def test_sandbox_disabled_short_circuits_without_workspace(tmp_path: Path) -> None:
    db = _db_with_no_existing_tool_runs()
    snapshot = DiffSnapshot(id=1, repository_id=1, head_sha="sha1", base_sha="mainsha")
    repo_config = parse_repo_config(None)
    runner = _FakeRunner(
        RunnerResult(
            exit_code=0,
            stdout="",
            stderr="",
            timed_out=False,
            errored=False,
            duration_ms=1,
            stdout_truncated=False,
            stderr_truncated=False,
        )
    )

    disabled_settings = _settings(analysis_sandbox_enabled=False)
    with patch("app.analysis.pipeline.get_settings", return_value=disabled_settings):
        with patch("app.analysis.pipeline.workspace_for") as workspace_for_mock:
            results = run_analysis_pipeline(
                db=db,
                client=MagicMock(),
                repository=_FakeRepository(),
                diff_snapshot=snapshot,
                repo_config=repo_config,
                runner=runner,
            )

    assert results == []
    workspace_for_mock.assert_not_called()
    assert runner.calls == []


def test_runs_custom_checks_and_persists_normalized_results(tmp_path: Path) -> None:
    db = _db_with_no_existing_tool_runs()
    snapshot = DiffSnapshot(id=1, repository_id=1, head_sha="sha1", base_sha="mainsha")
    repo_config = parse_repo_config(
        """
version: 1
checks:
  tests:
    command: "pytest"
    required: true
  lint:
    command: "ruff check ."
    required: false
"""
    )
    runner = _FakeRunner(
        RunnerResult(
            exit_code=1,
            stdout="2 failed\n",
            stderr="",
            timed_out=False,
            errored=False,
            duration_ms=42,
            stdout_truncated=False,
            stderr_truncated=False,
        )
    )

    workspace_ctx = _fake_workspace_for(tmp_path)
    with patch("app.analysis.pipeline.get_settings", return_value=_settings()):
        with patch("app.analysis.pipeline.workspace_for", side_effect=workspace_ctx):
            results = run_analysis_pipeline(
                db=db,
                client=MagicMock(),
                repository=_FakeRepository(),
                diff_snapshot=snapshot,
                repo_config=repo_config,
                runner=runner,
            )

    assert len(runner.calls) == 2
    assert {call["run_subdir"] for call in runner.calls} == {"run-1"}
    assert len(results) == 2
    persisted_names = {row.check_name for row in results}
    assert persisted_names == {"tests", "lint"}
    tests_row = next(row for row in results if row.check_name == "tests")
    assert tests_row.conclusion == "failed"
    assert tests_row.required is True
    lint_row = next(row for row in results if row.check_name == "lint")
    assert lint_row.required is False
    assert db.add.call_count == 2
    assert db.commit.call_count == 2


def test_existing_tool_run_is_reused_without_rerunning(tmp_path: Path) -> None:
    db = MagicMock()
    existing_row = ToolRun(
        id=99,
        repository_id=1,
        diff_snapshot_id=1,
        check_name="tests",
        category="test",
        status="completed",
        conclusion="passed",
        required=True,
        exit_code=0,
        duration_ms=10,
        summary="ok",
        annotations=[],
    )
    db.query.return_value.filter_by.return_value.all.return_value = [existing_row]

    snapshot = DiffSnapshot(id=1, repository_id=1, head_sha="sha1", base_sha="mainsha")
    repo_config = parse_repo_config(
        """
version: 1
checks:
  tests:
    command: "pytest"
    required: true
"""
    )
    runner = _FakeRunner(
        RunnerResult(
            exit_code=0,
            stdout="",
            stderr="",
            timed_out=False,
            errored=False,
            duration_ms=1,
            stdout_truncated=False,
            stderr_truncated=False,
        )
    )

    workspace_ctx = _fake_workspace_for(tmp_path)
    with patch("app.analysis.pipeline.get_settings", return_value=_settings()):
        with patch("app.analysis.pipeline.workspace_for", side_effect=workspace_ctx):
            results = run_analysis_pipeline(
                db=db,
                client=MagicMock(),
                repository=_FakeRepository(),
                diff_snapshot=snapshot,
                repo_config=repo_config,
                runner=runner,
            )

    assert results == [existing_row]
    assert runner.calls == []
    db.add.assert_not_called()


def test_dependency_scan_is_skipped_without_network_and_still_persisted(tmp_path: Path) -> None:
    db = _db_with_no_existing_tool_runs()
    snapshot = DiffSnapshot(id=1, repository_id=1, head_sha="sha1", base_sha="mainsha")
    repo_config = parse_repo_config(None)
    runner = _FakeRunner(
        RunnerResult(
            exit_code=0,
            stdout="",
            stderr="",
            timed_out=False,
            errored=False,
            duration_ms=1,
            stdout_truncated=False,
            stderr_truncated=False,
        )
    )

    settings = _settings(analysis_dependency_scan_enabled=True)
    workspace_ctx = _fake_workspace_for(tmp_path)
    with patch("app.analysis.pipeline.get_settings", return_value=settings):
        with patch("app.analysis.pipeline.workspace_for", side_effect=workspace_ctx):
            results = run_analysis_pipeline(
                db=db,
                client=MagicMock(),
                repository=_FakeRepository(),
                diff_snapshot=snapshot,
                repo_config=repo_config,
                runner=runner,
            )

    assert len(results) == 1
    assert results[0].check_name == "dependency_audit"
    assert results[0].conclusion == "skipped"
    assert runner.calls == []
