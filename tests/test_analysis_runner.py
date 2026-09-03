import subprocess
from unittest.mock import patch

from app.analysis.runner import DockerCliSandboxRunner, RunnerLimits, _sanitize_and_cap


def _limits(**overrides) -> RunnerLimits:
    defaults = dict(
        timeout_seconds=30,
        memory_mb=512,
        cpu_limit=1.0,
        pids_limit=128,
        max_output_bytes=64_000,
        network_enabled=False,
    )
    defaults.update(overrides)
    return RunnerLimits(**defaults)


def _runner() -> DockerCliSandboxRunner:
    return DockerCliSandboxRunner(docker_binary="docker", volume_name="reviewrush_analysis_ws")


def test_build_args_applies_isolation_flags() -> None:
    runner = _runner()
    args = runner._build_args(
        image="python:3.12-slim",
        command="pytest",
        run_subdir="abc123",
        limits=_limits(),
        env=None,
        container_name="reviewrush-check-test",
    )
    assert "--network" in args and args[args.index("--network") + 1] == "none"
    assert "--memory" in args and args[args.index("--memory") + 1] == "512m"
    assert "--cpus" in args and args[args.index("--cpus") + 1] == "1.0"
    assert "--pids-limit" in args and args[args.index("--pids-limit") + 1] == "128"
    assert "--read-only" in args
    assert "--cap-drop" in args and args[args.index("--cap-drop") + 1] == "ALL"
    security_opt = args[args.index("--security-opt") + 1]
    assert "--security-opt" in args and security_opt == "no-new-privileges"
    assert "--user" in args and args[args.index("--user") + 1] == "65534:65534"
    assert "-v" in args
    volume_arg = args[args.index("-v") + 1]
    assert volume_arg == "reviewrush_analysis_ws:/workspace-root:ro"
    assert "python:3.12-slim" in args


def test_build_args_network_enabled_uses_bridge() -> None:
    runner = _runner()
    args = runner._build_args(
        image="img",
        command="cmd",
        run_subdir="x",
        limits=_limits(network_enabled=True),
        env=None,
        container_name="n",
    )
    assert args[args.index("--network") + 1] == "bridge"


def test_run_success_maps_exit_code_and_output() -> None:
    runner = _runner()
    completed = subprocess.CompletedProcess(args=[], returncode=0, stdout=b"ok\n", stderr=b"")
    with patch("app.analysis.runner.subprocess.run", return_value=completed) as run_mock:
        result = runner.run(image="img", command="echo ok", run_subdir="x", limits=_limits())
    run_mock.assert_called_once()
    assert result.exit_code == 0
    assert result.stdout == "ok\n"
    assert result.timed_out is False
    assert result.errored is False


def test_run_nonzero_exit_code_is_not_treated_as_infra_error() -> None:
    runner = _runner()
    completed = subprocess.CompletedProcess(args=[], returncode=1, stdout=b"", stderr=b"boom")
    with patch("app.analysis.runner.subprocess.run", return_value=completed):
        result = runner.run(image="img", command="false", run_subdir="x", limits=_limits())
    assert result.exit_code == 1
    assert result.errored is False


def test_run_docker_infra_error_exit_code_125_is_errored() -> None:
    runner = _runner()
    completed = subprocess.CompletedProcess(
        args=[], returncode=125, stdout=b"", stderr=b"Cannot connect to the Docker daemon"
    )
    with patch("app.analysis.runner.subprocess.run", return_value=completed):
        result = runner.run(image="img", command="true", run_subdir="x", limits=_limits())
    assert result.errored is True
    assert result.exit_code is None
    assert result.timed_out is False


def test_run_timeout_kills_container_and_marks_timed_out() -> None:
    runner = _runner()
    timeout_exc = subprocess.TimeoutExpired(
        cmd=["docker"], timeout=1, output=b"partial", stderr=b""
    )

    def side_effect(*args, **kwargs):
        raise timeout_exc

    with patch("app.analysis.runner.subprocess.run", side_effect=side_effect) as run_mock:
        with patch.object(runner, "_kill_container") as kill_mock:
            result = runner.run(
                image="img", command="sleep 999", run_subdir="x", limits=_limits(timeout_seconds=1)
            )
    assert run_mock.call_count == 1
    kill_mock.assert_called_once()
    assert result.timed_out is True
    assert result.errored is False
    assert result.exit_code is None


def test_run_missing_docker_binary_is_errored_not_raised() -> None:
    runner = _runner()
    with patch("app.analysis.runner.subprocess.run", side_effect=FileNotFoundError("no docker")):
        result = runner.run(image="img", command="true", run_subdir="x", limits=_limits())
    assert result.errored is True
    assert result.timed_out is False
    assert "no docker" in (result.error_message or "")


def test_sanitize_and_cap_strips_ansi_and_truncates() -> None:
    raw = b"\x1b[31mred text\x1b[0m" + b"y" * 100
    text, truncated = _sanitize_and_cap(raw, max_bytes=20)
    assert "\x1b" not in text
    assert truncated is True
    assert len(text.encode("utf-8")) <= 20


def test_sanitize_and_cap_handles_invalid_utf8_without_raising() -> None:
    raw = b"\xff\xfe garbage"
    text, truncated = _sanitize_and_cap(raw, max_bytes=1000)
    assert isinstance(text, str)
    assert truncated is False
