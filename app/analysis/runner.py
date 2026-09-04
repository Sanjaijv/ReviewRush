import logging
import re
import subprocess
import time
import uuid
from dataclasses import dataclass
from typing import Protocol

logger = logging.getLogger(__name__)

_ANSI_ESCAPE_RE = re.compile(rb"\x1b\[[0-9;]*[a-zA-Z]")

# `docker run` returns 125 when the *daemon* failed to create/start the
# container (bad image, daemon unreachable, invalid flags, ...). Any other
# exit code is the exited process's own status, per Docker CLI semantics.
_DOCKER_INFRA_ERROR_EXIT_CODE = 125


@dataclass(frozen=True)
class RunnerLimits:
    """Resource and time bounds applied to one sandboxed command."""

    timeout_seconds: int
    memory_mb: int
    cpu_limit: float
    pids_limit: int
    max_output_bytes: int
    network_enabled: bool = False


@dataclass(frozen=True)
class RunnerResult:
    """Normalized outcome of one sandboxed command run.

    `timed_out` and `errored` are mutually exclusive with a plain non-zero
    `exit_code` failure: a caller must check them before interpreting
    `exit_code`, since a timeout or infra error may leave `exit_code` unset.
    """

    exit_code: int | None
    stdout: str
    stderr: str
    timed_out: bool
    errored: bool
    duration_ms: int
    stdout_truncated: bool
    stderr_truncated: bool
    error_message: str | None = None


class SandboxRunner(Protocol):
    def run(
        self,
        *,
        image: str,
        command: str,
        run_subdir: str,
        limits: RunnerLimits,
        env: dict[str, str] | None = None,
    ) -> RunnerResult:
        """Execute `command` (a POSIX shell command) inside an isolated
        container, seeded with a writable copy of the read-only input tree
        found at `run_subdir` within the shared analysis volume.
        """
        ...


def _sanitize_and_cap(raw: bytes, max_bytes: int) -> tuple[str, bool]:
    """Strip ANSI escape sequences and cap to `max_bytes`, returning
    (text, truncated). Decoding never raises: invalid UTF-8 is replaced.
    """
    stripped = _ANSI_ESCAPE_RE.sub(b"", raw)
    truncated = len(stripped) > max_bytes
    if truncated:
        stripped = stripped[:max_bytes]
    text = stripped.decode("utf-8", errors="replace")
    return text, truncated


class DockerCliSandboxRunner:
    """Runs one command per call in an ephemeral, isolated Docker container
    launched via the `docker` CLI.

    Security posture (see Phase 5 of the roadmap): the container gets no
    network by default, no credentials, a read-only view of the input tree,
    a size-bounded writable tmpfs scratch space, dropped Linux capabilities,
    an unprivileged UID, and hard memory/CPU/PID/time limits. PR code must
    never be able to reach production credentials or the internal network
    through this path.
    """

    def __init__(
        self,
        *,
        docker_binary: str,
        volume_name: str,
        container_workspace_root: str = "/workspace-root",
        container_scratch_dir: str = "/work",
    ) -> None:
        self._docker_binary = docker_binary
        self._volume_name = volume_name
        self._container_workspace_root = container_workspace_root
        self._container_scratch_dir = container_scratch_dir

    def _build_args(
        self,
        *,
        image: str,
        command: str,
        run_subdir: str,
        limits: RunnerLimits,
        env: dict[str, str] | None,
        container_name: str,
    ) -> list[str]:
        input_dir = f"{self._container_workspace_root}/{run_subdir}"
        scratch = self._container_scratch_dir
        inner_script = (
            f"mkdir -p {scratch} && "
            f"cp -a {input_dir}/. {scratch}/ 2>/dev/null; "
            f"cd {scratch} && ( {command} )"
        )

        args = [
            self._docker_binary,
            "run",
            "--rm",
            "--name",
            container_name,
            "--network",
            "bridge" if limits.network_enabled else "none",
            "--memory",
            f"{limits.memory_mb}m",
            "--memory-swap",
            f"{limits.memory_mb}m",
            "--cpus",
            str(limits.cpu_limit),
            "--pids-limit",
            str(limits.pids_limit),
            "--read-only",
            "--tmpfs",
            "/tmp:rw,size=256m,mode=1777",
            "--tmpfs",
            f"{scratch}:rw,size=1024m,mode=1777",
            "--cap-drop",
            "ALL",
            "--security-opt",
            "no-new-privileges",
            "--user",
            "65534:65534",
            "-e",
            "HOME=/tmp",
            "-e",
            "TMPDIR=/tmp",
            "-v",
            f"{self._volume_name}:{self._container_workspace_root}:ro",
            "-w",
            scratch,
        ]
        for key, value in (env or {}).items():
            args.extend(["-e", f"{key}={value}"])
        # Explicit --entrypoint override: some tool images (e.g.
        # zricethezav/gitleaks) set ENTRYPOINT to the tool binary itself, so
        # appending "sh -c <script>" as CMD without this would run
        # "<binary> sh -c <script>" - the tool trying (and failing) to parse
        # "sh" as its own subcommand, rather than actually invoking a shell.
        args.extend(["--entrypoint", "sh", image, "-c", inner_script])
        return args

    def run(
        self,
        *,
        image: str,
        command: str,
        run_subdir: str,
        limits: RunnerLimits,
        env: dict[str, str] | None = None,
    ) -> RunnerResult:
        container_name = f"reviewrush-check-{uuid.uuid4().hex[:20]}"
        args = self._build_args(
            image=image,
            command=command,
            run_subdir=run_subdir,
            limits=limits,
            env=env,
            container_name=container_name,
        )

        started = time.monotonic()
        try:
            completed = subprocess.run(
                args,
                capture_output=True,
                timeout=limits.timeout_seconds,
            )
        except subprocess.TimeoutExpired as exc:
            self._kill_container(container_name)
            duration_ms = int((time.monotonic() - started) * 1000)
            stdout, stdout_truncated = _sanitize_and_cap(
                exc.stdout or b"", limits.max_output_bytes
            )
            stderr, stderr_truncated = _sanitize_and_cap(
                exc.stderr or b"", limits.max_output_bytes
            )
            return RunnerResult(
                exit_code=None,
                stdout=stdout,
                stderr=stderr,
                timed_out=True,
                errored=False,
                duration_ms=duration_ms,
                stdout_truncated=stdout_truncated,
                stderr_truncated=stderr_truncated,
                error_message=f"check timed out after {limits.timeout_seconds}s",
            )
        except FileNotFoundError as exc:
            duration_ms = int((time.monotonic() - started) * 1000)
            logger.error("docker binary not found: %s", exc)
            return RunnerResult(
                exit_code=None,
                stdout="",
                stderr="",
                timed_out=False,
                errored=True,
                duration_ms=duration_ms,
                stdout_truncated=False,
                stderr_truncated=False,
                error_message=f"docker executable not found: {exc}",
            )

        duration_ms = int((time.monotonic() - started) * 1000)
        stdout, stdout_truncated = _sanitize_and_cap(completed.stdout, limits.max_output_bytes)
        stderr, stderr_truncated = _sanitize_and_cap(completed.stderr, limits.max_output_bytes)

        if completed.returncode == _DOCKER_INFRA_ERROR_EXIT_CODE:
            logger.error(
                "sandbox container failed to start", extra={"stderr": stderr[:2000]}
            )
            return RunnerResult(
                exit_code=None,
                stdout=stdout,
                stderr=stderr,
                timed_out=False,
                errored=True,
                duration_ms=duration_ms,
                stdout_truncated=stdout_truncated,
                stderr_truncated=stderr_truncated,
                error_message="sandbox container failed to start",
            )

        return RunnerResult(
            exit_code=completed.returncode,
            stdout=stdout,
            stderr=stderr,
            timed_out=False,
            errored=False,
            duration_ms=duration_ms,
            stdout_truncated=stdout_truncated,
            stderr_truncated=stderr_truncated,
        )

    def _kill_container(self, container_name: str) -> None:
        try:
            subprocess.run(
                [self._docker_binary, "kill", container_name],
                capture_output=True,
                timeout=15,
            )
        except Exception:
            logger.warning("failed to kill timed-out sandbox container %s", container_name)
