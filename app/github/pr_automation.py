import logging
import re
from typing import Any

import httpx

from app.github.client import GitHubClient
from app.models import PullRequest, Repository
from app.repo_config import RepoConfig

logger = logging.getLogger(__name__)

AUTOMATED_SECTION_START = "<!-- reviewrush:automated:start -->"
AUTOMATED_SECTION_END = "<!-- reviewrush:automated:end -->"

_MAX_COMMITS_LISTED = 20


def resolve_branches(repository: Repository, repo_config: RepoConfig) -> tuple[str, str]:
    """Resolve source/target branches: .reviewrush.yml overrides repository
    settings, which override the hard default of foundations -> main.
    """
    source = repo_config.branches.source or repository.source_branch or "foundations"
    target = repo_config.branches.target or repository.target_branch or "main"
    return source, target


def _short_sha(sha: str) -> str:
    return sha[:7]


def _first_line(message: str) -> str:
    return message.strip().splitlines()[0] if message.strip() else "(no message)"


def build_title(commits: list[dict], head_branch: str, target_branch: str) -> str:
    if len(commits) == 1:
        summary = _first_line(commits[0].get("message", ""))
        return summary[:72]
    if commits:
        return f"{len(commits)} commits from {head_branch}"
    return f"Sync {head_branch} into {target_branch}"


def render_automated_section(
    commits: list[dict], head_sha: str, head_branch: str, base_branch: str
) -> str:
    lines = [
        AUTOMATED_SECTION_START,
        f"This pull request is automatically kept in sync with `{head_branch}`.",
        "",
    ]
    if commits:
        lines.append("**Latest commits**")
        for commit in commits[-_MAX_COMMITS_LISTED:]:
            sha = _short_sha(commit.get("id", ""))
            summary = _first_line(commit.get("message", ""))
            author = (commit.get("author") or {}).get("username") or (
                commit.get("author") or {}
            ).get("name", "unknown")
            lines.append(f"- `{sha}` {summary} (@{author})")
        lines.append("")
    lines.append(f"_Head: `{head_sha}` • Base: `{base_branch}`_")
    lines.append(AUTOMATED_SECTION_END)
    return "\n".join(lines)


def merge_pr_body(existing_body: str | None, automated_section: str) -> str:
    """Replace the automated section in place if present; otherwise append it,
    preserving any human-authored text.
    """
    existing_body = existing_body or ""
    pattern = re.compile(
        re.escape(AUTOMATED_SECTION_START) + r".*?" + re.escape(AUTOMATED_SECTION_END),
        re.DOTALL,
    )
    if pattern.search(existing_body):
        return pattern.sub(automated_section, existing_body)
    if existing_body.strip():
        return existing_body.rstrip() + "\n\n" + automated_section
    return automated_section


def _upsert_local_pull_request(
    db: Any,
    repository: Repository,
    pr_payload: dict,
    head_branch: str,
    base_branch: str,
    head_sha: str,
) -> None:
    number = pr_payload["number"]
    record = (
        db.query(PullRequest)
        .filter_by(repository_id=repository.id, github_pr_number=number)
        .one_or_none()
    )
    base_sha = (pr_payload.get("base") or {}).get("sha")
    if record is None:
        record = PullRequest(
            repository_id=repository.id,
            github_pr_number=number,
            head_branch=head_branch,
            base_branch=base_branch,
            head_sha=head_sha,
            base_sha=base_sha,
            state=pr_payload.get("state", "open"),
        )
        db.add(record)
    else:
        record.head_sha = head_sha
        record.base_sha = base_sha
        record.state = pr_payload.get("state", "open")
    db.commit()


def sync_pull_request_for_push(
    db: Any,
    client: GitHubClient,
    repository: Repository,
    source_branch: str,
    target_branch: str,
    head_sha: str,
    commits: list[dict],
) -> None:
    """Create or update the source -> target PR for one push, unless a newer
    push has already superseded this head SHA (debounce).
    """
    owner, name = repository.owner, repository.name

    live_sha = client.get_ref_sha(owner, name, source_branch)
    if live_sha != head_sha:
        logger.info(
            "push superseded by a newer commit, skipping",
            extra={"repository": repository.full_name, "branch": source_branch},
        )
        return

    open_prs = client.list_open_pull_requests(owner, name, head=source_branch, base=target_branch)
    automated_section = render_automated_section(commits, head_sha, source_branch, target_branch)

    if open_prs:
        pr_payload = open_prs[0]
        new_body = merge_pr_body(pr_payload.get("body"), automated_section)
        updated = client.update_pull_request(owner, name, pr_payload["number"], body=new_body)
        _upsert_local_pull_request(db, repository, updated, source_branch, target_branch, head_sha)
        logger.info(
            "updated existing pull request",
            extra={"repository": repository.full_name, "pr_number": pr_payload["number"]},
        )
        return

    title = build_title(commits, source_branch, target_branch)
    try:
        created = client.create_pull_request(
            owner, name, title=title, body=automated_section, head=source_branch, base=target_branch
        )
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 422:
            logger.info(
                "no diff to open a pull request for, skipping",
                extra={"repository": repository.full_name, "branch": source_branch},
            )
            return
        raise

    _upsert_local_pull_request(db, repository, created, source_branch, target_branch, head_sha)
    logger.info(
        "created pull request",
        extra={"repository": repository.full_name, "pr_number": created["number"]},
    )
