import logging
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.dashboard.audit import record_audit_event
from app.dashboard.config_service import (
    InvalidRepoConfig,
    get_active_config_version,
    list_config_versions,
    save_config_version,
)
from app.dashboard.control import RunNotFound, cancel_review, disconnect_repository, rerun_review
from app.dashboard.deps import (
    DashboardUser,
    get_authorized_organization,
    get_authorized_repository,
    get_current_user,
    require_dashboard_rate_limit,
    require_org_admin,
)
from app.dashboard.metrics import compute_repository_metrics
from app.dashboard.oauth import (
    STATE_COOKIE_NAME,
    build_authorize_url,
    exchange_code_for_token,
    fetch_accessible_installation_ids,
    fetch_authenticated_user,
    new_state,
)
from app.dashboard.reliability import (
    TaskFailureNotFound,
    list_task_failures,
    resolve_task_failure,
    summarize_task_failure,
)
from app.dashboard.runs import get_run_detail, list_review_runs, summarize_run
from app.dashboard.session import SESSION_COOKIE_NAME, create_session_token
from app.db import get_db
from app.feedback.service import (
    FeedbackActor,
    FindingNotFound,
    list_escaped_defects,
    list_finding_feedback,
    record_escaped_defect,
    submit_finding_feedback,
)
from app.models import AuditEvent, Installation, Organization, Repository
from app.tenancy.deletion import delete_organization_data
from app.tenancy.export import export_organization_data
from app.tenancy.membership import sync_membership
from app.tenancy.plans import PLAN_DEFAULTS, resolve_limits
from app.tenancy.provisioning import get_or_create_organization

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/dashboard", tags=["dashboard"])

_CALLBACK_PATH = "/api/v1/dashboard/auth/callback"


def _require_dashboard_enabled(settings: Settings) -> None:
    if not settings.dashboard_enabled:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "dashboard is not enabled")


@router.get("/auth/login")
def login(response: Response, settings: Settings = Depends(get_settings)) -> Response:
    _require_dashboard_enabled(settings)
    state = new_state()
    redirect_uri = f"{settings.dashboard_base_url.rstrip('/')}{_CALLBACK_PATH}"
    authorize_url = build_authorize_url(settings, redirect_uri=redirect_uri, state=state)

    redirect = Response(status_code=status.HTTP_302_FOUND, headers={"Location": authorize_url})
    redirect.set_cookie(
        STATE_COOKIE_NAME,
        state,
        max_age=600,
        httponly=True,
        secure=settings.environment != "development",
        samesite="lax",
    )
    return redirect


@router.get("/auth/callback")
def callback(
    request: Request,
    code: str,
    state: str,
    settings: Settings = Depends(get_settings),
) -> Response:
    _require_dashboard_enabled(settings)
    expected_state = request.cookies.get(STATE_COOKIE_NAME)
    if not expected_state or state != expected_state:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "invalid oauth state")

    redirect_uri = f"{settings.dashboard_base_url.rstrip('/')}{_CALLBACK_PATH}"
    try:
        user_token = exchange_code_for_token(settings, code=code, redirect_uri=redirect_uri)
        github_user = fetch_authenticated_user(user_token)
        installation_ids = fetch_accessible_installation_ids(user_token)
    except Exception:
        logger.exception("github oauth callback failed")
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, "github oauth exchange failed") from None

    # Phase 17: resolve/provision the tenant Organization for every
    # installation GitHub says this user can access, and sync their
    # membership role, so the session carries organization roles the same
    # way it already carries raw installation ids.
    organization_roles: dict[int, str] = {}
    if installation_ids:
        db = next(get_db())
        try:
            installations = (
                db.query(Installation)
                .filter(Installation.github_installation_id.in_(installation_ids))
                .all()
            )
            for installation in installations:
                organization = get_or_create_organization(db, installation)
                member = sync_membership(
                    db,
                    organization,
                    github_user_id=github_user.id,
                    login=github_user.login,
                )
                organization_roles[organization.id] = member.role
        finally:
            db.close()

    session_token = create_session_token(
        settings,
        github_user_id=github_user.id,
        login=github_user.login,
        avatar_url=github_user.avatar_url,
        installation_ids=installation_ids,
        organization_roles=organization_roles,
    )

    redirect = Response(
        status_code=status.HTTP_302_FOUND,
        headers={"Location": f"{settings.dashboard_base_url.rstrip('/')}/dashboard/"},
    )
    redirect.delete_cookie(STATE_COOKIE_NAME)
    redirect.set_cookie(
        SESSION_COOKIE_NAME,
        session_token,
        max_age=settings.dashboard_session_ttl_seconds,
        httponly=True,
        secure=settings.environment != "development",
        samesite="lax",
    )
    return redirect


@router.post("/auth/logout")
def logout(response: Response) -> dict[str, str]:
    response.delete_cookie(SESSION_COOKIE_NAME)
    return {"status": "logged out"}


@router.get("/me")
def me(user: DashboardUser = Depends(get_current_user)) -> dict[str, Any]:
    return {
        "github_user_id": user.github_user_id,
        "login": user.login,
        "avatar_url": user.avatar_url,
        "installation_ids": sorted(user.installation_ids),
    }


@router.get("/installations")
def list_installations(
    user: DashboardUser = Depends(get_current_user), db: Session = Depends(get_db)
) -> list[dict[str, Any]]:
    if not user.installation_ids:
        return []
    rows = (
        db.query(Installation)
        .filter(Installation.github_installation_id.in_(user.installation_ids))
        .all()
    )
    return [
        {
            "id": i.id,
            "account_login": i.account_login,
            "account_type": i.account_type,
            "status": i.status,
        }
        for i in rows
    ]


@router.get("/installations/{installation_id}/repositories")
def list_repositories(
    installation_id: int,
    user: DashboardUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[dict[str, Any]]:
    installation: Any = db.get(Installation, installation_id)
    if installation is None or installation.github_installation_id not in user.installation_ids:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "installation not found")
    return [
        {
            "id": r.id,
            "full_name": r.full_name,
            "default_branch": r.default_branch,
            "is_active": r.is_active,
            "disconnected_at": r.disconnected_at.isoformat() if r.disconnected_at else None,
        }
        for r in installation.repositories
    ]


@router.get("/repositories/{repository_id}/runs")
def runs(
    repository_id: int,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    repository: Repository = Depends(get_authorized_repository),
    db: Session = Depends(get_db),
) -> list[dict[str, Any]]:
    snapshots = list_review_runs(db, repository_id, limit=limit, offset=offset)
    return [summarize_run(s) for s in snapshots]


@router.get("/repositories/{repository_id}/runs/{diff_snapshot_id}")
def run_detail(
    repository_id: int,
    diff_snapshot_id: int,
    repository: Repository = Depends(get_authorized_repository),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    detail = get_run_detail(db, repository_id, diff_snapshot_id)
    if detail is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "review run not found")
    return detail


@router.post("/repositories/{repository_id}/runs/{diff_snapshot_id}/rerun")
def rerun(
    repository_id: int,
    diff_snapshot_id: int,
    repository: Repository = Depends(get_authorized_repository),
    user: DashboardUser = Depends(get_current_user),
    db: Session = Depends(get_db),
    _rl: None = Depends(require_dashboard_rate_limit),
) -> dict[str, Any]:
    try:
        snapshot = rerun_review(db, repository, diff_snapshot_id, user)
    except RunNotFound:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "review run not found") from None
    return {"id": snapshot.id, "status": snapshot.status}


@router.post("/repositories/{repository_id}/runs/{diff_snapshot_id}/cancel")
def cancel(
    repository_id: int,
    diff_snapshot_id: int,
    repository: Repository = Depends(get_authorized_repository),
    user: DashboardUser = Depends(get_current_user),
    db: Session = Depends(get_db),
    _rl: None = Depends(require_dashboard_rate_limit),
) -> dict[str, Any]:
    try:
        snapshot = cancel_review(db, repository, diff_snapshot_id, user)
    except RunNotFound:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "review run not found") from None
    return {"id": snapshot.id, "status": snapshot.status}


@router.get("/repositories/{repository_id}/config")
def get_config(
    repository: Repository = Depends(get_authorized_repository),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    active = get_active_config_version(db, repository.id)
    return {
        "source": "dashboard_override" if active is not None else "repository_file",
        "version": active.version if active is not None else None,
        "config": active.config if active is not None else None,
    }


class ConfigUpdateRequest(BaseModel):
    config: dict[str, Any]


@router.put("/repositories/{repository_id}/config")
def put_config(
    body: ConfigUpdateRequest,
    repository: Repository = Depends(get_authorized_repository),
    user: DashboardUser = Depends(get_current_user),
    db: Session = Depends(get_db),
    _rl: None = Depends(require_dashboard_rate_limit),
) -> dict[str, Any]:
    try:
        row = save_config_version(db, repository, body.config, user)
    except InvalidRepoConfig as exc:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            {"message": "invalid repository configuration", "errors": exc.errors},
        ) from None
    return {"version": row.version, "config": row.config}


@router.get("/repositories/{repository_id}/config/versions")
def config_versions(
    repository: Repository = Depends(get_authorized_repository),
    db: Session = Depends(get_db),
) -> list[dict[str, Any]]:
    return [
        {
            "version": v.version,
            "actor_login": v.actor_login,
            "created_at": v.created_at.isoformat(),
            "config": v.config,
        }
        for v in list_config_versions(db, repository.id)
    ]


@router.get("/repositories/{repository_id}/metrics")
def metrics(
    repository: Repository = Depends(get_authorized_repository),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    return compute_repository_metrics(db, repository.id)


@router.get("/repositories/{repository_id}/audit-log")
def audit_log(
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    repository: Repository = Depends(get_authorized_repository),
    db: Session = Depends(get_db),
) -> list[dict[str, Any]]:
    rows = (
        db.query(AuditEvent)
        .filter_by(repository_id=repository.id)
        .order_by(AuditEvent.created_at.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )
    return [
        {
            "id": e.id,
            "actor_type": e.actor_type,
            "actor_login": e.actor_login,
            "action": e.action,
            "target_type": e.target_type,
            "target_id": e.target_id,
            "metadata": e.event_metadata,
            "created_at": e.created_at.isoformat(),
        }
        for e in rows
    ]


@router.get("/repositories/{repository_id}/task-failures")
def task_failures(
    include_resolved: bool = Query(default=False),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    repository: Repository = Depends(get_authorized_repository),
    db: Session = Depends(get_db),
) -> list[dict[str, Any]]:
    rows = list_task_failures(
        db, repository.id, include_resolved=include_resolved, limit=limit, offset=offset
    )
    return [summarize_task_failure(r) for r in rows]


@router.post("/repositories/{repository_id}/task-failures/{task_failure_id}/resolve")
def resolve_task_failure_endpoint(
    task_failure_id: int,
    repository: Repository = Depends(get_authorized_repository),
    user: DashboardUser = Depends(get_current_user),
    db: Session = Depends(get_db),
    _rl: None = Depends(require_dashboard_rate_limit),
) -> dict[str, Any]:
    try:
        failure = resolve_task_failure(db, repository, task_failure_id, user)
    except TaskFailureNotFound:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "task failure not found") from None
    return summarize_task_failure(failure)


class DisconnectRequest(BaseModel):
    retention_days: int | None = None


@router.post("/repositories/{repository_id}/disconnect")
def disconnect(
    body: DisconnectRequest,
    repository: Repository = Depends(get_authorized_repository),
    user: DashboardUser = Depends(get_current_user),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
    _rl: None = Depends(require_dashboard_rate_limit),
) -> dict[str, Any]:
    retention_days = (
        body.retention_days
        if body.retention_days is not None
        else settings.dashboard_default_retention_days
    )
    updated = disconnect_repository(db, repository, user, retention_days)
    return {
        "id": updated.id,
        "is_active": updated.is_active,
        "disconnected_at": updated.disconnected_at.isoformat() if updated.disconnected_at else None,
        "retention_days": updated.retention_days,
    }


class FindingFeedbackRequest(BaseModel):
    reaction: str
    consent: bool
    implemented: bool | None = None
    notes: str | None = None


@router.post("/repositories/{repository_id}/findings/{finding_id}/feedback")
def submit_feedback(
    finding_id: int,
    body: FindingFeedbackRequest,
    repository: Repository = Depends(get_authorized_repository),
    user: DashboardUser = Depends(get_current_user),
    db: Session = Depends(get_db),
    _rl: None = Depends(require_dashboard_rate_limit),
) -> dict[str, Any]:
    actor = FeedbackActor(user_id=user.github_user_id, login=user.login)
    try:
        row = submit_finding_feedback(
            db,
            repository,
            finding_id,
            actor,
            reaction=body.reaction,
            consent=body.consent,
            implemented=body.implemented,
            notes=body.notes,
        )
    except FindingNotFound:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "finding not found") from None
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from None
    return {
        "id": row.id,
        "ai_finding_id": row.ai_finding_id,
        "reaction": row.reaction,
        "implemented": row.implemented,
        "consent": row.consent,
        "created_at": row.created_at.isoformat(),
    }


@router.get("/repositories/{repository_id}/findings/{finding_id}/feedback")
def get_feedback(
    finding_id: int,
    repository: Repository = Depends(get_authorized_repository),
    db: Session = Depends(get_db),
) -> list[dict[str, Any]]:
    return [
        {
            "id": row.id,
            "reaction": row.reaction,
            "implemented": row.implemented,
            "actor_login": row.actor_login,
            "created_at": row.created_at.isoformat(),
        }
        for row in list_finding_feedback(db, repository, finding_id)
    ]


class EscapedDefectRequest(BaseModel):
    description: str
    pull_request_id: int | None = None
    diff_snapshot_id: int | None = None
    ai_finding_id: int | None = None
    evidence_url: str | None = None
    detected_at: datetime | None = None


@router.post("/repositories/{repository_id}/escaped-defects")
def create_escaped_defect(
    body: EscapedDefectRequest,
    repository: Repository = Depends(get_authorized_repository),
    user: DashboardUser = Depends(get_current_user),
    db: Session = Depends(get_db),
    _rl: None = Depends(require_dashboard_rate_limit),
) -> dict[str, Any]:
    actor = FeedbackActor(user_id=user.github_user_id, login=user.login)
    try:
        row = record_escaped_defect(
            db,
            repository,
            actor,
            description=body.description,
            pull_request_id=body.pull_request_id,
            diff_snapshot_id=body.diff_snapshot_id,
            ai_finding_id=body.ai_finding_id,
            evidence_url=body.evidence_url,
            detected_at=body.detected_at,
        )
    except FindingNotFound:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "finding not found") from None
    return {
        "id": row.id,
        "description": row.description,
        "ai_finding_id": row.ai_finding_id,
        "created_at": row.created_at.isoformat(),
    }


@router.get("/repositories/{repository_id}/escaped-defects")
def list_escaped_defects_route(
    repository: Repository = Depends(get_authorized_repository),
    db: Session = Depends(get_db),
) -> list[dict[str, Any]]:
    return [
        {
            "id": row.id,
            "description": row.description,
            "pull_request_id": row.pull_request_id,
            "diff_snapshot_id": row.diff_snapshot_id,
            "ai_finding_id": row.ai_finding_id,
            "evidence_url": row.evidence_url,
            "detected_at": row.detected_at.isoformat() if row.detected_at else None,
            "actor_login": row.actor_login,
            "created_at": row.created_at.isoformat(),
        }
        for row in list_escaped_defects(db, repository)
    ]


def _organization_summary(organization: Organization, role: str) -> dict[str, Any]:
    limits = resolve_limits(organization)
    return {
        "id": organization.id,
        "slug": organization.slug,
        "name": organization.name,
        "role": role,
        "plan": organization.plan,
        "region": organization.region,
        "retention_days_default": organization.retention_days_default,
        "ai_provider_override": organization.ai_provider_override,
        "ai_model_override": organization.ai_model_override,
        "max_ai_reviews_per_day": limits.max_ai_reviews_per_day,
        "max_repositories": limits.max_repositories,
    }


@router.get("/organizations")
def list_organizations(
    user: DashboardUser = Depends(get_current_user), db: Session = Depends(get_db)
) -> list[dict[str, Any]]:
    if not user.organization_roles:
        return []
    rows = (
        db.query(Organization)
        .filter(Organization.id.in_(user.organization_roles.keys()))
        .all()
    )
    return [_organization_summary(org, user.organization_roles[org.id]) for org in rows]


@router.get("/organizations/{organization_id}")
def get_organization(
    organization: Organization = Depends(get_authorized_organization),
    user: DashboardUser = Depends(get_current_user),
) -> dict[str, Any]:
    return _organization_summary(organization, user.organization_roles[organization.id])


class OrganizationSettingsRequest(BaseModel):
    plan: str | None = None
    region: str | None = None
    retention_days_default: int | None = None
    max_ai_reviews_per_day: int | None = None
    max_repositories: int | None = None
    ai_provider_override: str | None = None
    ai_model_override: str | None = None


@router.put("/organizations/{organization_id}/settings")
def put_organization_settings(
    body: OrganizationSettingsRequest,
    organization: Organization = Depends(require_org_admin),
    user: DashboardUser = Depends(get_current_user),
    db: Session = Depends(get_db),
    _rl: None = Depends(require_dashboard_rate_limit),
) -> dict[str, Any]:
    if body.plan is not None:
        if body.plan not in PLAN_DEFAULTS:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "unknown plan")
        organization.plan = body.plan
    if body.region is not None:
        organization.region = body.region
    if body.retention_days_default is not None:
        organization.retention_days_default = body.retention_days_default
    if body.max_ai_reviews_per_day is not None:
        organization.max_ai_reviews_per_day = body.max_ai_reviews_per_day
    if body.max_repositories is not None:
        organization.max_repositories = body.max_repositories
    if body.ai_provider_override is not None:
        organization.ai_provider_override = body.ai_provider_override or None
    if body.ai_model_override is not None:
        organization.ai_model_override = body.ai_model_override or None

    record_audit_event(
        db,
        action="organization.settings_updated",
        target_type="organization",
        target_id=str(organization.id),
        actor_type="user",
        actor_user_id=user.github_user_id,
        actor_login=user.login,
        metadata=body.model_dump(exclude_none=True),
    )
    db.commit()
    db.refresh(organization)
    return _organization_summary(organization, user.organization_roles[organization.id])


@router.post("/organizations/{organization_id}/export")
def export_organization(
    organization: Organization = Depends(get_authorized_organization),
    user: DashboardUser = Depends(get_current_user),
    db: Session = Depends(get_db),
    _rl: None = Depends(require_dashboard_rate_limit),
) -> dict[str, Any]:
    bundle = export_organization_data(db, organization)
    record_audit_event(
        db,
        action="organization.data_exported",
        target_type="organization",
        target_id=str(organization.id),
        actor_type="user",
        actor_user_id=user.github_user_id,
        actor_login=user.login,
    )
    db.commit()
    return bundle


class DeleteOrganizationDataRequest(BaseModel):
    confirm_slug: str


@router.post("/organizations/{organization_id}/delete-data")
def delete_organization_data_route(
    body: DeleteOrganizationDataRequest,
    organization: Organization = Depends(require_org_admin),
    user: DashboardUser = Depends(get_current_user),
    db: Session = Depends(get_db),
    _rl: None = Depends(require_dashboard_rate_limit),
) -> dict[str, Any]:
    if body.confirm_slug != organization.slug:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "confirm_slug does not match the organization's slug",
        )
    counts = delete_organization_data(
        db, organization, actor_user_id=user.github_user_id, actor_login=user.login
    )
    return {"deleted": counts}
