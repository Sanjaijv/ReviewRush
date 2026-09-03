import logging
from typing import Any

from app.analysis.pipeline import run_analysis_pipeline
from app.analysis.runner import DockerCliSandboxRunner
from app.config import get_settings
from app.github.auth import get_installation_access_token
from app.github.client import GitHubClient
from app.models import DiffSnapshot, Repository, ToolRun
from app.repo_config import parse_repo_config

logger = logging.getLogger(__name__)

REPO_CONFIG_PATH = ".reviewrush.yml"


def run_analysis_for_snapshot(
    db: Any, repository: Repository, diff_snapshot: DiffSnapshot
) -> list[ToolRun]:
    """Entry point used by the Celery task: wires up a real GitHub client and
    Docker sandbox runner and runs every deterministic check for one
    already-built, immutable diff snapshot.
    """
    settings = get_settings()
    installation = repository.installation
    token = get_installation_access_token(installation.github_installation_id)

    with GitHubClient(token) as client:
        config_yaml = client.get_file_contents(
            repository.owner, repository.name, REPO_CONFIG_PATH, ref=diff_snapshot.head_sha
        )
        repo_config = parse_repo_config(config_yaml)

        runner = DockerCliSandboxRunner(
            docker_binary=settings.analysis_docker_binary,
            volume_name=settings.analysis_volume_name,
        )

        return run_analysis_pipeline(
            db=db,
            client=client,
            repository=repository,
            diff_snapshot=diff_snapshot,
            repo_config=repo_config,
            runner=runner,
        )
