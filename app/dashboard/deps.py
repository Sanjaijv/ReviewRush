from dataclasses import dataclass, field
from typing import Any

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.dashboard.session import SESSION_COOKIE_NAME, InvalidSession, verify_session_token
from app.db import get_db
from app.models import Organization, Repository
from app.tenancy.membership import is_elevated
from app.tenancy.rate_limit import check_dashboard_rate_limit


@dataclass(frozen=True)
class DashboardUser:
    github_user_id: int
    login: str
    avatar_url: str
    installation_ids: frozenset[int]
    # organization_id -> role ("owner" | "admin" | "member"), Phase 17.
    organization_roles: dict[int, str] = field(default_factory=dict)


def get_current_user(
    request: Request, settings: Settings = Depends(get_settings)
) -> DashboardUser:
    token = request.cookies.get(SESSION_COOKIE_NAME)
    if not token:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "not authenticated")
    try:
        payload = verify_session_token(settings, token)
    except InvalidSession as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "session expired or invalid") from exc

    return DashboardUser(
        github_user_id=int(payload["sub"]),
        login=str(payload["login"]),
        avatar_url=str(payload.get("avatar_url", "")),
        installation_ids=frozenset(int(i) for i in payload.get("installation_ids", [])),
        organization_roles={
            int(k): str(v) for k, v in payload.get("organization_roles", {}).items()
        },
    )


def get_authorized_repository(
    repository_id: int,
    user: DashboardUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Repository:
    """Fetch a repository the caller is authorized for, or 404.

    A 404 (not 403) is returned for both "doesn't exist" and "not
    authorized" so an unauthorized caller can't use this endpoint to probe
    which repository ids exist in our database.
    """
    repository: Any = db.get(Repository, repository_id)
    if repository is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "repository not found")
    if repository.installation.github_installation_id not in user.installation_ids:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "repository not found")
    return repository


def require_dashboard_rate_limit(
    user: DashboardUser = Depends(get_current_user), settings: Settings = Depends(get_settings)
) -> None:
    """Abuse-prevention dependency (Phase 17) for mutating dashboard
    endpoints - read-only browsing is left unlimited, matching the
    `tenancy_webhook_rate_limit_per_minute` design of only gating
    state-changing/expensive actions rather than the whole API surface.
    """
    check_dashboard_rate_limit(settings, user.github_user_id)


def get_authorized_organization(
    organization_id: int,
    user: DashboardUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Organization:
    """Fetch an Organization the caller is a member of, or 404.

    Same not-found-vs-forbidden pattern as `get_authorized_repository`: a
    404 is returned whether the organization doesn't exist or the caller
    just isn't a member, so this endpoint can't be used to enumerate
    other tenants' organization ids.
    """
    organization: Any = db.get(Organization, organization_id)
    if organization is None or organization.id not in user.organization_roles:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "organization not found")
    return organization


def require_org_admin(
    organization: Organization = Depends(get_authorized_organization),
    user: DashboardUser = Depends(get_current_user),
) -> Organization:
    """Same as `get_authorized_organization`, but additionally requires the
    caller hold the `"owner"` or `"admin"` role - for destructive/settings
    actions (data export/deletion, plan/provider overrides) that a plain
    member must not be able to trigger.
    """
    role = user.organization_roles.get(organization.id, "member")
    if not is_elevated(role):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "organization admin role required")
    return organization
