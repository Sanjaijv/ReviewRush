import logging
import shutil
import tarfile
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from app.config import get_settings
from app.github.client import GitHubClient
from app.models import Repository

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Workspace:
    """A prepared, read-only-intended checkout of one commit's repo tree.

    `run_subdir` is the directory name under the shared analysis volume - it's
    what sandbox containers reference (via the volume mount), while `host_path`
    is the same directory as seen by the worker process itself.
    """

    run_subdir: str
    host_path: Path


class WorkspaceTooLargeError(Exception):
    pass


def _safe_extract(tar_path: Path, dest: Path) -> None:
    """Extract a GitHub tarball, stripping its single top-level directory and
    guarding against path traversal in member names.

    GitHub tarballs contain untrusted PR content, so every member path is
    validated to resolve inside `dest` before extraction - a member like
    `../../etc/passwd` must never be allowed to escape the workspace.
    """
    with tarfile.open(tar_path, mode="r:gz") as tar:
        members = tar.getmembers()
        for member in members:
            parts = Path(member.name).parts
            if len(parts) <= 1:
                continue
            relative = Path(*parts[1:])
            target = (dest / relative).resolve()
            if not str(target).startswith(str(dest.resolve()) + "/") and target != dest.resolve():
                raise ValueError(f"unsafe tarball member path: {member.name}")
            member.name = str(relative)
            if member.isdir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            if member.issym() or member.islnk():
                logger.warning("skipping symlink/hardlink tarball member: %s", member.name)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            extracted = tar.extractfile(member)
            if extracted is None:
                continue
            with open(target, "wb") as fh:
                shutil.copyfileobj(extracted, fh)


def prepare_workspace(client: GitHubClient, repository: Repository, head_sha: str) -> Workspace:
    """Download and extract the repo tree at `head_sha` into a fresh
    directory under the shared analysis volume.

    Callers must clean up with `cleanup_workspace` once every check has run.
    """
    settings = get_settings()
    run_subdir = uuid.uuid4().hex
    root = Path(settings.analysis_workdir)
    host_path = root / run_subdir
    host_path.mkdir(parents=True, exist_ok=True)

    tar_path = root / f"{run_subdir}.tar.gz"
    try:
        client.download_tarball(
            repository.owner,
            repository.name,
            head_sha,
            tar_path,
            max_bytes=settings.analysis_max_repo_bytes,
        )
        _safe_extract(tar_path, host_path)
    except Exception:
        shutil.rmtree(host_path, ignore_errors=True)
        raise
    finally:
        tar_path.unlink(missing_ok=True)

    return Workspace(run_subdir=run_subdir, host_path=host_path)


def cleanup_workspace(workspace: Workspace) -> None:
    shutil.rmtree(workspace.host_path, ignore_errors=True)


@contextmanager
def workspace_for(
    client: GitHubClient, repository: Repository, head_sha: str
) -> Iterator[Workspace]:
    workspace = prepare_workspace(client, repository, head_sha)
    try:
        yield workspace
    finally:
        cleanup_workspace(workspace)
