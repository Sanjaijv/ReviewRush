from typing import Any

from pydantic import ValidationError

from app.dashboard.audit import record_audit_event
from app.dashboard.deps import DashboardUser
from app.models import Repository, RepositoryConfigVersion
from app.repo_config import RepoConfig


class InvalidRepoConfig(Exception):
    def __init__(self, errors: Any):
        self.errors = errors
        super().__init__("repository configuration failed schema validation")


def get_active_config_version(db: Any, repository_id: int) -> RepositoryConfigVersion | None:
    return (
        db.query(RepositoryConfigVersion)
        .filter_by(repository_id=repository_id)
        .order_by(RepositoryConfigVersion.version.desc())
        .first()
    )


def list_config_versions(db: Any, repository_id: int) -> list[RepositoryConfigVersion]:
    return (
        db.query(RepositoryConfigVersion)
        .filter_by(repository_id=repository_id)
        .order_by(RepositoryConfigVersion.version.desc())
        .all()
    )


def save_config_version(
    db: Any, repository: Repository, raw_config: dict[str, Any], user: DashboardUser
) -> RepositoryConfigVersion:
    """Validate and persist a new dashboard-authored config override.

    Never mutates a previous version - always inserts `previous + 1`, same
    idempotency-by-append pattern as every other immutable row in this
    codebase, so a bad edit is fixed by writing a new version, not rewriting
    history. Fails closed: a document that doesn't pass RepoConfig's schema
    is rejected before anything is written.
    """
    try:
        validated = RepoConfig.model_validate(raw_config)
    except ValidationError as exc:
        raise InvalidRepoConfig(exc.errors()) from exc

    latest = get_active_config_version(db, repository.id)
    next_version = (latest.version + 1) if latest is not None else 1

    row = RepositoryConfigVersion(
        repository_id=repository.id,
        version=next_version,
        config=validated.model_dump(mode="json"),
        actor_user_id=user.github_user_id,
        actor_login=user.login,
    )
    db.add(row)
    db.flush()

    record_audit_event(
        db,
        action="config.updated",
        target_type="repository_config_version",
        target_id=str(row.id),
        repository_id=repository.id,
        actor_type="user",
        actor_user_id=user.github_user_id,
        actor_login=user.login,
        metadata={"version": next_version},
    )
    db.commit()
    db.refresh(row)
    return row
