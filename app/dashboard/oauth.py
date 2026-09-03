import secrets
from dataclasses import dataclass
from urllib.parse import urlencode

import httpx

from app.config import Settings

GITHUB_AUTHORIZE_URL = "https://github.com/login/oauth/authorize"
GITHUB_TOKEN_URL = "https://github.com/login/oauth/access_token"
GITHUB_API_BASE_URL = "https://api.github.com"

STATE_COOKIE_NAME = "rr_oauth_state"


@dataclass(frozen=True)
class GitHubUser:
    id: int
    login: str
    avatar_url: str


def new_state() -> str:
    return secrets.token_urlsafe(32)


def build_authorize_url(settings: Settings, *, redirect_uri: str, state: str) -> str:
    if not settings.github_oauth_client_id:
        raise RuntimeError("GITHUB_OAUTH_CLIENT_ID is not configured")
    params = {
        "client_id": settings.github_oauth_client_id,
        "redirect_uri": redirect_uri,
        "state": state,
    }
    return f"{GITHUB_AUTHORIZE_URL}?{urlencode(params)}"


def exchange_code_for_token(settings: Settings, *, code: str, redirect_uri: str) -> str:
    """Exchange a one-time OAuth code for a user access token.

    This is a *user* access token (the GitHub App's user-to-server flow),
    never persisted and never logged - it is used immediately to look up the
    user's identity and accessible installations, then discarded.
    """
    if not settings.github_oauth_client_id or not settings.github_oauth_client_secret:
        raise RuntimeError("GitHub OAuth client credentials are not configured")

    response = httpx.post(
        GITHUB_TOKEN_URL,
        headers={"Accept": "application/json"},
        data={
            "client_id": settings.github_oauth_client_id,
            "client_secret": settings.github_oauth_client_secret,
            "code": code,
            "redirect_uri": redirect_uri,
        },
        timeout=10.0,
    )
    response.raise_for_status()
    body = response.json()
    token = body.get("access_token")
    if not token:
        raise RuntimeError(f"GitHub OAuth token exchange failed: {body.get('error', 'unknown')}")
    return str(token)


def fetch_authenticated_user(user_token: str) -> GitHubUser:
    response = httpx.get(
        f"{GITHUB_API_BASE_URL}/user",
        headers={"Authorization": f"Bearer {user_token}", "Accept": "application/vnd.github+json"},
        timeout=10.0,
    )
    response.raise_for_status()
    body = response.json()
    return GitHubUser(id=body["id"], login=body["login"], avatar_url=body.get("avatar_url", ""))


def fetch_accessible_installation_ids(user_token: str) -> list[int]:
    """List the GitHub App installation ids this user is authorized to
    administer, per GitHub's own access model - never derived from our own
    database, so a user can't gain dashboard access to an installation just
    because our Installation table happens to contain it.
    """
    installation_ids: list[int] = []
    url: str | None = f"{GITHUB_API_BASE_URL}/user/installations"
    params: dict[str, int] = {"per_page": 100}
    with httpx.Client(
        headers={"Authorization": f"Bearer {user_token}", "Accept": "application/vnd.github+json"},
        timeout=10.0,
    ) as client:
        while url:
            response = client.get(url, params=params)
            response.raise_for_status()
            body = response.json()
            installation_ids.extend(
                item["id"] for item in body.get("installations", [])
            )
            url = response.links.get("next", {}).get("url")
            params = {}
    return installation_ids
