import time

import httpx
import jwt

from app.config import get_settings


def create_app_jwt() -> str:
    """Build a short-lived (10 minute) JWT authenticating as the GitHub App itself.

    Used only to exchange for a per-installation access token — never sent to
    repository code or logged.
    """
    settings = get_settings()
    if not settings.github_app_id or not settings.github_private_key:
        raise RuntimeError("GitHub App credentials are not configured")

    now = int(time.time())
    payload = {
        "iat": now - 60,
        "exp": now + (10 * 60),
        "iss": settings.github_app_id,
    }
    return jwt.encode(payload, settings.github_private_key, algorithm="RS256")


def get_installation_access_token(github_installation_id: int) -> str:
    """Exchange the App JWT for a short-lived installation access token.

    Called lazily, only when a task actually needs to call the GitHub API on
    behalf of an installation — never persisted, never logged.
    """
    settings = get_settings()
    app_jwt = create_app_jwt()

    response = httpx.post(
        f"{settings.github_api_base_url}/app/installations/{github_installation_id}/access_tokens",
        headers={
            "Authorization": f"Bearer {app_jwt}",
            "Accept": "application/vnd.github+json",
        },
        timeout=10.0,
    )
    response.raise_for_status()
    return response.json()["token"]
