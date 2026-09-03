import base64
import logging
from pathlib import Path

import httpx
from tenacity import (
    retry,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential_jitter,
)

from app.config import get_settings
from app.observability.metrics import observe_github_rate_limit

logger = logging.getLogger(__name__)

# Retried only for transient conditions: connection/timeout errors, 429
# (rate limited / secondary rate limit), and 5xx. Every other status
# (401/403/404/422/...) is a caller-meaningful outcome, not a glitch, and
# must never be silently retried.
_RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}


def _is_retryable(exc: BaseException) -> bool:
    if isinstance(exc, httpx.TransportError):
        return True
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code in _RETRYABLE_STATUS_CODES
    return False


class GitHubClient:
    """Thin wrapper over the GitHub REST endpoints branch monitoring and PR
    automation need, authenticated with a short-lived installation token.

    Never logs the token. Raises httpx.HTTPStatusError on non-2xx responses;
    callers decide which statuses are expected (404 == "not found", not an error).

    Every request is retried with exponential backoff and jitter, but only
    for transient failures (network errors, 429, 5xx) - a 4xx that isn't a
    rate limit is a real, non-transient outcome and is raised immediately.
    """

    def __init__(self, installation_token: str):
        settings = get_settings()
        self._client = httpx.Client(
            base_url=settings.github_api_base_url,
            headers={
                "Authorization": f"Bearer {installation_token}",
                "Accept": "application/vnd.github+json",
            },
            timeout=15.0,
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "GitHubClient":
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def _do_request(self, method: str, url: str, **kwargs: object) -> httpx.Response:
        # Dispatches to the matching httpx.Client convenience method
        # (.get/.post/.patch/.put) rather than the generic .request() so a
        # caller mocking `client._client` sees the same call shape this
        # class has always made.
        send = getattr(self._client, method.lower())
        response = send(url, **kwargs)
        observe_github_rate_limit(response.headers)
        if response.status_code in _RETRYABLE_STATUS_CODES:
            logger.warning(
                "github request received a transient status",
                extra={"status_code": response.status_code, "url": url, "method": method},
            )
            response.raise_for_status()
        return response

    @retry(
        retry=retry_if_exception(_is_retryable),
        wait=wait_exponential_jitter(initial=0.5, max=20),
        stop=stop_after_attempt(5),
        reraise=True,
    )
    def _request_idempotent(self, method: str, url: str, **kwargs: object) -> httpx.Response:
        """Issue a GET/PATCH/PUT/DELETE, retried (with backoff+jitter) only
        while the response keeps coming back with a transient status.
        Restricted to methods GitHub treats idempotently: replaying one
        after a lost response can never create a second resource, unlike a
        create-type POST.
        """
        return self._do_request(method, url, **kwargs)

    def _request_create(self, method: str, url: str, **kwargs: object) -> httpx.Response:
        """Issue a create-type POST once, with no client-level retry: if the
        request succeeded server-side but the response was lost, blindly
        retrying here could create a second PR/comment/check-run. A
        transient failure instead propagates to the Celery task-level
        retry, which re-runs the whole (already idempotent, check-before-
        create) operation rather than replaying this bare POST.
        """
        return self._do_request(method, url, **kwargs)

    def _get(self, url: str, **kwargs: object) -> httpx.Response:
        response = self._request_idempotent("GET", url, **kwargs)
        if response.status_code != 404:
            response.raise_for_status()
        return response

    def _write(self, method: str, url: str, **kwargs: object) -> httpx.Response:
        response = self._request_idempotent(method, url, **kwargs)
        response.raise_for_status()
        return response

    def _create(self, method: str, url: str, **kwargs: object) -> httpx.Response:
        response = self._request_create(method, url, **kwargs)
        response.raise_for_status()
        return response

    def get_ref_sha(self, owner: str, repo: str, branch: str) -> str | None:
        """Return the current head SHA of a branch, or None if it doesn't exist."""
        response = self._get(f"/repos/{owner}/{repo}/git/ref/heads/{branch}")
        if response.status_code == 404:
            return None
        return response.json()["object"]["sha"]

    def get_file_contents(self, owner: str, repo: str, path: str, ref: str) -> str | None:
        """Return decoded file content at a ref, or None if the file doesn't exist."""
        response = self._get(f"/repos/{owner}/{repo}/contents/{path}", params={"ref": ref})
        if response.status_code == 404:
            return None
        body = response.json()
        if isinstance(body, list) or body.get("type") != "file":
            return None
        return base64.b64decode(body["content"]).decode("utf-8", errors="replace")

    def compare_commits(self, owner: str, repo: str, base: str, head: str) -> dict:
        """Return the GitHub merge-base comparison of base...head: commits,
        the merge_base_commit, and per-file entries with status/patch/rename info.
        """
        response = self._write("GET", f"/repos/{owner}/{repo}/compare/{base}...{head}")
        return response.json()

    def list_open_pull_requests(
        self, owner: str, repo: str, head: str, base: str
    ) -> list[dict]:
        response = self._write(
            "GET",
            f"/repos/{owner}/{repo}/pulls",
            params={"state": "open", "head": f"{owner}:{head}", "base": base},
        )
        return response.json()

    def create_pull_request(
        self, owner: str, repo: str, title: str, body: str, head: str, base: str
    ) -> dict:
        response = self._create(
            "POST",
            f"/repos/{owner}/{repo}/pulls",
            json={"title": title, "body": body, "head": head, "base": base},
        )
        return response.json()

    def download_tarball(
        self, owner: str, repo: str, ref: str, dest_path: Path, max_bytes: int
    ) -> None:
        """Stream the repository tarball at `ref` to `dest_path`.

        Enforces `max_bytes` while streaming so an unexpectedly large archive
        can't exhaust local disk before being rejected - PR-controlled repo
        content must never be trusted to be a reasonable size.
        """
        with self._client.stream(
            "GET",
            f"/repos/{owner}/{repo}/tarball/{ref}",
            follow_redirects=True,
            timeout=120.0,
        ) as response:
            response.raise_for_status()
            written = 0
            with open(dest_path, "wb") as fh:
                for chunk in response.iter_bytes():
                    written += len(chunk)
                    if written > max_bytes:
                        raise ValueError(
                            f"tarball for {owner}/{repo}@{ref} exceeds max_bytes={max_bytes}"
                        )
                    fh.write(chunk)

    def update_pull_request(
        self, owner: str, repo: str, number: int, title: str | None = None, body: str | None = None
    ) -> dict:
        payload: dict[str, str] = {}
        if title is not None:
            payload["title"] = title
        if body is not None:
            payload["body"] = body
        response = self._write("PATCH", f"/repos/{owner}/{repo}/pulls/{number}", json=payload)
        return response.json()

    def create_check_run(
        self,
        owner: str,
        repo: str,
        name: str,
        head_sha: str,
        *,
        conclusion: str | None = None,
        title: str | None = None,
        summary: str | None = None,
    ) -> dict:
        """Create a Check Run for `head_sha`: in-progress by default, or
        already completed if `conclusion` is given (used when Phase 8 needs
        to create-and-complete a run in one call, e.g. because the
        in-progress run from review start was never created).

        Checks attach to a commit, not a PR, so this works even before a PR
        exists (or when one never will, e.g. a direct push with no diff).
        """
        payload: dict[str, object] = {"name": name, "head_sha": head_sha}
        if conclusion is None:
            payload["status"] = "in_progress"
        else:
            payload["status"] = "completed"
            payload["conclusion"] = conclusion
            payload["output"] = {"title": title or name, "summary": summary or ""}
        response = self._create("POST", f"/repos/{owner}/{repo}/check-runs", json=payload)
        return response.json()

    def update_check_run(
        self,
        owner: str,
        repo: str,
        check_run_id: int,
        *,
        conclusion: str,
        title: str,
        summary: str,
        text: str | None = None,
    ) -> dict:
        output: dict[str, str] = {"title": title, "summary": summary}
        if text is not None:
            output["text"] = text
        response = self._write(
            "PATCH",
            f"/repos/{owner}/{repo}/check-runs/{check_run_id}",
            json={"status": "completed", "conclusion": conclusion, "output": output},
        )
        return response.json()

    def create_issue_comment(self, owner: str, repo: str, issue_number: int, body: str) -> dict:
        """Post a new top-level PR comment. `issue_number` is the PR number -
        GitHub represents PR conversations through the Issues API.
        """
        response = self._create(
            "POST", f"/repos/{owner}/{repo}/issues/{issue_number}/comments", json={"body": body}
        )
        return response.json()

    def update_issue_comment(self, owner: str, repo: str, comment_id: int, body: str) -> dict:
        response = self._write(
            "PATCH", f"/repos/{owner}/{repo}/issues/comments/{comment_id}", json={"body": body}
        )
        return response.json()

    def create_review_comment(
        self,
        owner: str,
        repo: str,
        pull_number: int,
        *,
        commit_id: str,
        path: str,
        position: int,
        body: str,
    ) -> dict:
        """Post an inline PR review comment anchored to a diff `position`
        (offset into the file's patch text, from `app.diffs.patch`).
        """
        response = self._create(
            "POST",
            f"/repos/{owner}/{repo}/pulls/{pull_number}/comments",
            json={"commit_id": commit_id, "path": path, "position": position, "body": body},
        )
        return response.json()

    def update_review_comment(self, owner: str, repo: str, comment_id: int, body: str) -> dict:
        response = self._write(
            "PATCH", f"/repos/{owner}/{repo}/pulls/comments/{comment_id}", json={"body": body}
        )
        return response.json()

    def get_pull_request(self, owner: str, repo: str, number: int) -> dict:
        """Re-fetch live PR state (head sha, mergeable, mergeable_state, merged,
        draft, state) - Phase 9 must never decide auto-merge from a locally
        cached PullRequest row.
        """
        response = self._write("GET", f"/repos/{owner}/{repo}/pulls/{number}")
        return response.json()

    def list_check_runs_for_ref(self, owner: str, repo: str, ref: str) -> dict:
        response = self._write(
            "GET", f"/repos/{owner}/{repo}/commits/{ref}/check-runs", params={"per_page": 100}
        )
        return response.json()

    def list_reviews(self, owner: str, repo: str, number: int) -> list[dict]:
        response = self._write(
            "GET", f"/repos/{owner}/{repo}/pulls/{number}/reviews", params={"per_page": 100}
        )
        return response.json()

    def merge_pull_request(
        self,
        owner: str,
        repo: str,
        number: int,
        *,
        sha: str,
        merge_method: str = "squash",
    ) -> dict:
        """Merge a pull request. `sha` is GitHub's own optimistic-concurrency
        guard: the request is rejected if the PR's current head no longer
        matches it, which backstops our own stale-commit check. PUT is safe
        to retry here: GitHub rejects a second merge of an already-merged PR
        (405) rather than merging it twice.
        """
        response = self._write(
            "PUT",
            f"/repos/{owner}/{repo}/pulls/{number}/merge",
            json={"sha": sha, "merge_method": merge_method},
        )
        return response.json()
