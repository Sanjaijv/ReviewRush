from dataclasses import dataclass
from pathlib import Path

from app.analysis.runner import RunnerLimits
from app.config import Settings
from app.repo_config import RepoConfig

_CATEGORY_BY_CHECK_NAME = {
    "test": "test",
    "tests": "test",
    "lint": "lint",
    "format": "format",
    "formatting": "format",
    "typecheck": "typecheck",
    "type": "typecheck",
    "types": "typecheck",
    "secrets": "secret",
    "security": "security",
}


@dataclass(frozen=True)
class StageSpec:
    """One deterministic check to run, or to record as skipped without
    running anything (e.g. no applicable ecosystem manifest, or the stage's
    network requirement isn't enabled).
    """

    name: str
    category: str
    required: bool
    image: str = ""
    command: str = ""
    limits: RunnerLimits | None = None
    skip_reason: str | None = None


def _category_for(check_name: str) -> str:
    return _CATEGORY_BY_CHECK_NAME.get(check_name.lower(), "custom")


def build_custom_stages(repo_config: RepoConfig, settings: Settings) -> list[StageSpec]:
    """Stages the repository defined itself under `.reviewrush.yml: checks`."""
    stages = []
    for name, check in repo_config.checks.items():
        stages.append(
            StageSpec(
                name=name,
                category=_category_for(name),
                required=check.required,
                image=check.image or settings.analysis_default_image,
                command=check.command,
                limits=RunnerLimits(
                    timeout_seconds=check.timeout_seconds or settings.analysis_timeout_seconds,
                    memory_mb=settings.analysis_memory_limit_mb,
                    cpu_limit=settings.analysis_cpu_limit,
                    pids_limit=settings.analysis_pids_limit,
                    max_output_bytes=settings.analysis_max_log_bytes,
                    network_enabled=False,
                ),
            )
        )
    return stages


def _semgrep_stage(settings: Settings) -> StageSpec:
    report_path = "/work/.semgrep-report.json"
    # `--config=auto` fetches its ruleset from the Semgrep registry over the
    # network (only relevant when analysis_semgrep_network_enabled=true - see
    # that setting's docstring for the isolation tradeoff this implies), and
    # a transient DNS/connection hiccup fetching it is not meaningfully
    # different from the transient GitHub API failures app/github/client.py
    # already retries - a few quick attempts here avoids treating one flaky
    # resolver blip as a hard BLOCK.
    scan_once = (
        f"semgrep scan --config=auto --json --output={report_path} "
        f"--error --disable-version-check /work"
    )
    command = (
        f"code=1; "
        f"for attempt in 1 2 3; do "
        f"{scan_once} && code=0 && break; code=$?; sleep 2; "
        f"done; "
        f"cat {report_path} 2>/dev/null; exit $code"
    )
    return StageSpec(
        name="semgrep",
        category="security",
        required=settings.analysis_semgrep_required,
        image=settings.analysis_semgrep_image,
        command=command,
        limits=RunnerLimits(
            timeout_seconds=settings.analysis_timeout_seconds,
            memory_mb=settings.analysis_memory_limit_mb,
            cpu_limit=settings.analysis_cpu_limit,
            pids_limit=settings.analysis_pids_limit,
            max_output_bytes=settings.analysis_max_log_bytes,
            network_enabled=settings.analysis_semgrep_network_enabled,
        ),
    )


def _gitleaks_stage(settings: Settings) -> StageSpec:
    report_path = "/work/.gitleaks-report.json"
    command = (
        f"gitleaks detect --source=/work --no-git --report-format=json "
        f"--report-path={report_path} --exit-code=2; "
        f"code=$?; cat {report_path} 2>/dev/null; "
        f"if [ \"$code\" = \"2\" ]; then exit 1; fi; exit $code"
    )
    return StageSpec(
        name="gitleaks",
        category="secret",
        required=settings.analysis_gitleaks_required,
        image=settings.analysis_gitleaks_image,
        command=command,
        limits=RunnerLimits(
            timeout_seconds=settings.analysis_timeout_seconds,
            memory_mb=settings.analysis_memory_limit_mb,
            cpu_limit=settings.analysis_cpu_limit,
            pids_limit=settings.analysis_pids_limit,
            max_output_bytes=settings.analysis_max_log_bytes,
            network_enabled=False,
        ),
    )


def _detect_dependency_ecosystem(workspace_host_path: Path) -> str | None:
    if (workspace_host_path / "requirements.txt").exists() or (
        workspace_host_path / "pyproject.toml"
    ).exists():
        return "python"
    if (workspace_host_path / "package.json").exists():
        return "node"
    return None


def _dependency_scan_stage(settings: Settings, workspace_host_path: Path) -> StageSpec:
    if not settings.analysis_dependency_scan_network_enabled:
        return StageSpec(
            name="dependency_audit",
            category="dependency",
            required=settings.analysis_dependency_scan_required,
            skip_reason=(
                "dependency scanning requires network access to query an advisory "
                "database, which is disabled by default (ANALYSIS_DEPENDENCY_SCAN_NETWORK_ENABLED)"
            ),
        )

    ecosystem = _detect_dependency_ecosystem(workspace_host_path)
    if ecosystem is None:
        return StageSpec(
            name="dependency_audit",
            category="dependency",
            required=settings.analysis_dependency_scan_required,
            skip_reason="no recognized dependency manifest found (requirements.txt, "
            "pyproject.toml, package.json)",
        )

    limits = RunnerLimits(
        timeout_seconds=settings.analysis_timeout_seconds,
        memory_mb=settings.analysis_memory_limit_mb,
        cpu_limit=settings.analysis_cpu_limit,
        pids_limit=settings.analysis_pids_limit,
        max_output_bytes=settings.analysis_max_log_bytes,
        network_enabled=True,
    )
    if ecosystem == "python":
        return StageSpec(
            name="dependency_audit",
            category="dependency",
            required=settings.analysis_dependency_scan_required,
            image=settings.analysis_dependency_scan_python_image,
            # pip-audit exits 1 to signal "vulnerabilities found", the same
            # as a real execution failure - unlike most of this module's
            # commands, there is deliberately no `|| <fallback>` here: an
            # `||` would treat a legitimate scoped finding on
            # requirements.txt the same as "the command didn't run" and
            # silently substitute a whole-environment scan (including
            # pip-audit's own dependencies) instead of reporting the
            # repository's actual declared dependencies.
            command=(
                "export PATH=\"$HOME/.local/bin:$PATH\"; "
                "pip install --quiet --no-input pip-audit && "
                "pip-audit --format=json -r requirements.txt"
            ),
            limits=limits,
        )
    return StageSpec(
        name="dependency_audit",
        category="dependency",
        required=settings.analysis_dependency_scan_required,
        image=settings.analysis_dependency_scan_node_image,
        command="npm audit --json || true",
        limits=limits,
    )


def build_builtin_stages(settings: Settings, workspace_host_path: Path) -> list[StageSpec]:
    stages = []
    if settings.analysis_semgrep_enabled:
        stages.append(_semgrep_stage(settings))
    if settings.analysis_gitleaks_enabled:
        stages.append(_gitleaks_stage(settings))
    if settings.analysis_dependency_scan_enabled:
        stages.append(_dependency_scan_stage(settings, workspace_host_path))
    return stages


def build_all_stages(
    repo_config: RepoConfig, settings: Settings, workspace_host_path: Path
) -> list[StageSpec]:
    custom_names = set(repo_config.checks.keys())
    builtin = [
        stage
        for stage in build_builtin_stages(settings, workspace_host_path)
        if stage.name not in custom_names
    ]
    return build_custom_stages(repo_config, settings) + builtin
