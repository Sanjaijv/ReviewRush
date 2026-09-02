import logging
from typing import Any

from sqlalchemy.exc import IntegrityError

from app.diffs.classification import (
    is_generated_or_vendor,
    looks_binary_by_extension,
    parse_submodule_paths,
)
from app.diffs.limits import DiffLimits, evaluate_limits
from app.github.client import GitHubClient
from app.models import ChangedFile, DiffSnapshot, Repository

logger = logging.getLogger(__name__)

_STATUS_MAP = {
    "added": "added",
    "removed": "removed",
    "modified": "modified",
    "renamed": "renamed",
    "copied": "copied",
    "changed": "modified",
    "unchanged": "modified",
}

GITMODULES_PATH = ".gitmodules"
_MAX_STORED_COMMITS = 100


def _first_line(message: str) -> str:
    stripped = message.strip()
    return stripped.splitlines()[0] if stripped else ""


def _extract_commits(commits_payload: list[dict]) -> list[dict[str, Any]]:
    """Bounded commit metadata (sha, first message line, author) from a
    compare payload's `commits` array, capped so a huge compare range can't
    grow a snapshot row without bound.
    """
    extracted: list[dict[str, Any]] = []
    for entry in commits_payload[:_MAX_STORED_COMMITS]:
        commit = entry.get("commit") or {}
        commit_author = commit.get("author") or {}
        github_author = entry.get("author") or {}
        extracted.append(
            {
                "sha": entry.get("sha"),
                "message": _first_line(commit.get("message") or ""),
                "author_login": github_author.get("login"),
                "author_name": commit_author.get("name"),
                "authored_at": commit_author.get("date"),
            }
        )
    return extracted


def _load_submodule_paths(client: GitHubClient, repository: Repository, head_sha: str) -> set[str]:
    try:
        content = client.get_file_contents(
            repository.owner, repository.name, GITMODULES_PATH, ref=head_sha
        )
    except Exception:
        logger.warning(
            "failed to fetch .gitmodules, proceeding without submodule detection",
            extra={"repository": repository.full_name},
        )
        return set()
    return parse_submodule_paths(content)


def _resolve_paths(status_raw: str, file_payload: dict) -> tuple[str | None, str | None]:
    filename = file_payload.get("filename")
    if status_raw == "added":
        return None, filename
    if status_raw == "removed":
        return filename, None
    if status_raw in ("renamed", "copied"):
        return file_payload.get("previous_filename"), filename
    return filename, filename


def _build_changed_file(
    file_payload: dict,
    submodule_paths: set[str],
    limits: DiffLimits,
    client: GitHubClient | None,
    repository: Repository,
    head_sha: str,
    fetch_truncated_content: bool,
) -> tuple[ChangedFile, int, int, int, bool]:
    status_raw = file_payload.get("status", "modified")
    status = _STATUS_MAP.get(status_raw, "modified")
    old_path, new_path = _resolve_paths(status_raw, file_payload)
    classification_path = new_path or old_path or ""

    additions = int(file_payload.get("additions") or 0)
    deletions = int(file_payload.get("deletions") or 0)
    changes = int(file_payload.get("changes") or (additions + deletions))

    is_submodule = classification_path in submodule_paths
    raw_patch = file_payload.get("patch")
    has_patch = raw_patch is not None and not is_submodule

    is_binary = False
    patch_truncated = False
    content_fetched = False
    stored_patch: str | None = None

    if is_submodule:
        pass
    elif has_patch and raw_patch is not None:
        patch_bytes = len(raw_patch.encode("utf-8"))
        if patch_bytes > limits.max_file_patch_bytes:
            patch_truncated = True
        else:
            stored_patch = raw_patch
    else:
        if looks_binary_by_extension(classification_path):
            is_binary = True
        else:
            patch_truncated = True
            if fetch_truncated_content and client is not None and status != "removed":
                fetched = client.get_file_contents(
                    repository.owner, repository.name, classification_path, ref=head_sha
                )
                if fetched is not None:
                    fetched_bytes = len(fetched.encode("utf-8"))
                    if fetched_bytes <= limits.max_file_patch_bytes:
                        stored_patch = fetched
                        content_fetched = True

    is_generated = is_generated_or_vendor(classification_path, stored_patch)
    excluded_from_ai = is_binary or is_submodule or is_generated or patch_truncated

    changed_file = ChangedFile(
        old_path=old_path,
        new_path=new_path,
        status=status,
        additions=additions,
        deletions=deletions,
        changes=changes,
        is_binary=is_binary,
        is_submodule=is_submodule,
        is_generated=is_generated,
        excluded_from_ai=excluded_from_ai,
        patch=stored_patch,
        patch_truncated=patch_truncated,
        content_fetched=content_fetched,
    )

    stored_bytes = len(stored_patch.encode("utf-8")) if stored_patch else 0
    return changed_file, additions, deletions, stored_bytes, patch_truncated


def build_diff_snapshot(
    db: Any,
    client: GitHubClient,
    repository: Repository,
    base_sha: str,
    head_sha: str,
    limits: DiffLimits | None = None,
    fetch_truncated_content: bool = False,
) -> DiffSnapshot:
    """Build and persist the normalized diff between base_sha and head_sha, or
    return the existing snapshot if one was already stored for this head_sha.

    Snapshots are immutable once stored: a repeated call for the same
    (repository, head_sha) never recomputes or overwrites the existing row,
    so a result already used by a review can't shift under it.
    """
    existing = (
        db.query(DiffSnapshot)
        .filter_by(repository_id=repository.id, head_sha=head_sha)
        .one_or_none()
    )
    if existing is not None:
        return existing

    limits = limits or DiffLimits.from_settings()

    compare = client.compare_commits(repository.owner, repository.name, base_sha, head_sha)
    merge_base_sha = (compare.get("merge_base_commit") or {}).get("sha")
    files_payload = compare.get("files") or []
    commits = _extract_commits(compare.get("commits") or [])

    submodule_paths = _load_submodule_paths(client, repository, head_sha)

    changed_files: list[ChangedFile] = []
    total_additions = 0
    total_deletions = 0
    total_patch_bytes = 0
    any_truncated = False

    for file_payload in files_payload:
        changed_file, additions, deletions, patch_bytes, file_truncated = _build_changed_file(
            file_payload,
            submodule_paths,
            limits,
            client,
            repository,
            head_sha,
            fetch_truncated_content,
        )
        changed_files.append(changed_file)
        total_additions += additions
        total_deletions += deletions
        total_patch_bytes += patch_bytes
        any_truncated = any_truncated or file_truncated

    total_changed_lines = total_additions + total_deletions
    evaluation = evaluate_limits(
        limits,
        file_count=len(changed_files),
        total_changed_lines=total_changed_lines,
        total_patch_bytes=total_patch_bytes,
    )
    if evaluation.oversized:
        logger.warning(
            "diff exceeds configured limits, marking for human review",
            extra={
                "repository": repository.full_name,
                "head_sha": head_sha,
                "reasons": evaluation.reasons,
            },
        )

    snapshot = DiffSnapshot(
        repository_id=repository.id,
        head_sha=head_sha,
        base_sha=base_sha,
        merge_base_sha=merge_base_sha,
        commits=commits,
        status="oversized" if evaluation.oversized else "complete",
        truncated=any_truncated,
        file_count=len(changed_files),
        total_additions=total_additions,
        total_deletions=total_deletions,
        total_changed_lines=total_changed_lines,
        total_patch_bytes=total_patch_bytes,
    )
    snapshot.changed_files = changed_files

    db.add(snapshot)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        return (
            db.query(DiffSnapshot)
            .filter_by(repository_id=repository.id, head_sha=head_sha)
            .one()
        )

    return snapshot
