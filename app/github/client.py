import base64

import httpx

from app.config import get_settings


class GitHubClient:
    """Thin wrapper over the GitHub REST endpoints branch monitoring and PR
    automation need, authenticated with a short-lived installation token.

    Never logs the token. Raises httpx.HTTPStatusError on non-2xx responses;
    callers decide which statuses are expected (404 == "not found", not an error).
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

    def get_ref_sha(self, owner: str, repo: str, branch: str) -> str | None:
        """Return the current head SHA of a branch, or None if it doesn't exist."""
        response = self._client.get(f"/repos/{owner}/{repo}/git/ref/heads/{branch}")
        if response.status_code == 404:
            return None
        response.raise_for_status()
        return response.json()["object"]["sha"]

    def get_file_contents(self, owner: str, repo: str, path: str, ref: str) -> str | None:
        """Return decoded file content at a ref, or None if the file doesn't exist."""
        response = self._client.get(
            f"/repos/{owner}/{repo}/contents/{path}", params={"ref": ref}
        )
        if response.status_code == 404:
            return None
        response.raise_for_status()
        body = response.json()
        if isinstance(body, list) or body.get("type") != "file":
            return None
        return base64.b64decode(body["content"]).decode("utf-8", errors="replace")

    def compare_commits(self, owner: str, repo: str, base: str, head: str) -> dict:
        """Return the GitHub merge-base comparison of base...head: commits,
        the merge_base_commit, and per-file entries with status/patch/rename info.
        """
        response = self._client.get(f"/repos/{owner}/{repo}/compare/{base}...{head}")
        response.raise_for_status()
        return response.json()

    def list_open_pull_requests(
        self, owner: str, repo: str, head: str, base: str
    ) -> list[dict]:
        response = self._client.get(
            f"/repos/{owner}/{repo}/pulls",
            params={"state": "open", "head": f"{owner}:{head}", "base": base},
        )
        response.raise_for_status()
        return response.json()

    def create_pull_request(
        self, owner: str, repo: str, title: str, body: str, head: str, base: str
    ) -> dict:
        response = self._client.post(
            f"/repos/{owner}/{repo}/pulls",
            json={"title": title, "body": body, "head": head, "base": base},
        )
        response.raise_for_status()
        return response.json()

    def update_pull_request(
        self, owner: str, repo: str, number: int, title: str | None = None, body: str | None = None
    ) -> dict:
        payload: dict[str, str] = {}
        if title is not None:
            payload["title"] = title
        if body is not None:
            payload["body"] = body
        response = self._client.patch(
            f"/repos/{owner}/{repo}/pulls/{number}", json=payload
        )
        response.raise_for_status()
        return response.json()
