from typing import Any

from app.models import Organization, OrganizationMember

_ELEVATED_ROLES = {"owner", "admin"}


def sync_membership(
    db: Any,
    organization: Organization,
    *,
    github_user_id: int,
    login: str,
) -> OrganizationMember:
    """Upsert one user's membership row for an Organization, called on every
    dashboard login for every organization the user's GitHub installation
    access resolves to.

    Role heuristic (Phase 17 scope decision - no live GitHub org-role API
    call): the installer of a personal-account (`account_type="User"`)
    installation is `"owner"`; anyone else GitHub reports as having access
    to an organization-account installation is inserted as `"member"`, the
    least-privileged role, on first login. An existing `"owner"`/`"admin"`
    row is never downgraded by this sync - promotion/demotion beyond
    `"member"` only happens through an explicit admin action, never as a
    side effect of someone logging in.
    """
    member = (
        db.query(OrganizationMember)
        .filter_by(organization_id=organization.id, github_user_id=github_user_id)
        .one_or_none()
    )
    if member is not None:
        if member.login != login:
            member.login = login
            db.commit()
        return member

    is_personal_installer = organization.installation.account_type == "User"
    role = "owner" if is_personal_installer else "member"

    member = OrganizationMember(
        organization_id=organization.id,
        github_user_id=github_user_id,
        login=login,
        role=role,
    )
    db.add(member)
    db.commit()
    db.refresh(member)
    return member


def is_elevated(role: str) -> bool:
    return role in _ELEVATED_ROLES
