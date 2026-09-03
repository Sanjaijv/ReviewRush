import time
from typing import Any

import jwt

from app.config import Settings

SESSION_COOKIE_NAME = "rr_session"
_ALGORITHM = "HS256"


class InvalidSession(Exception):
    pass


def create_session_token(
    settings: Settings,
    *,
    github_user_id: int,
    login: str,
    avatar_url: str,
    installation_ids: list[int],
    organization_roles: dict[int, str] | None = None,
) -> str:
    """Sign a short-lived dashboard session.

    Deliberately stateless (no server-side session table): the set of
    installations/organizations the user may act on is captured at login
    time and expires with the token, rather than being cached indefinitely -
    a user whose GitHub access changes gets re-checked the next time they
    log in, at most `dashboard_session_ttl_seconds` later. `organization_roles`
    (Phase 17) maps organization id -> role ("owner"/"admin"/"member"),
    resolved from `app.tenancy.membership.sync_membership` at login time.
    """
    if not settings.dashboard_session_secret:
        raise RuntimeError("DASHBOARD_SESSION_SECRET is not configured")

    now = int(time.time())
    payload = {
        # PyJWT requires "sub" to be a string if present; verify_session_token
        # casts it back to int.
        "sub": str(github_user_id),
        "login": login,
        "avatar_url": avatar_url,
        "installation_ids": installation_ids,
        "organization_roles": {str(k): v for k, v in (organization_roles or {}).items()},
        "iat": now,
        "exp": now + settings.dashboard_session_ttl_seconds,
    }
    return jwt.encode(payload, settings.dashboard_session_secret, algorithm=_ALGORITHM)


def verify_session_token(settings: Settings, token: str) -> dict[str, Any]:
    if not settings.dashboard_session_secret:
        raise InvalidSession("dashboard session signing is not configured")
    try:
        return jwt.decode(token, settings.dashboard_session_secret, algorithms=[_ALGORITHM])
    except jwt.PyJWTError as exc:
        raise InvalidSession(str(exc)) from exc
