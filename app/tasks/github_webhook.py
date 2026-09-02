import logging
from datetime import UTC, datetime
from typing import Any

from app.celery_app import celery_app
from app.db import SessionLocal
from app.models import Installation, Repository, WebhookDelivery

logger = logging.getLogger(__name__)


def _mark_delivery(db: Any, delivery_id: str, status: str) -> None:
    delivery = db.query(WebhookDelivery).filter_by(delivery_id=delivery_id).one_or_none()
    if delivery is None:
        return
    delivery.status = status
    delivery.processed_at = datetime.now(UTC)
    db.commit()


def _handle_installation(db: Any, payload: dict) -> None:
    action = payload.get("action")
    installation_payload = payload.get("installation") or {}
    github_installation_id = installation_payload.get("id")
    account = installation_payload.get("account") or {}

    installation = (
        db.query(Installation)
        .filter_by(github_installation_id=github_installation_id)
        .one_or_none()
    )

    if action == "deleted":
        if installation is not None:
            installation.status = "deleted"
            for repository in installation.repositories:
                repository.is_active = False
            db.commit()
        return

    if installation is None:
        installation = Installation(
            github_installation_id=github_installation_id,
            account_login=account.get("login", ""),
            account_type=account.get("type", ""),
            status="active",
        )
        db.add(installation)
    else:
        installation.account_login = account.get("login", installation.account_login)
        installation.account_type = account.get("type", installation.account_type)
        installation.status = "suspended" if action == "suspend" else "active"
    db.commit()


def _handle_installation_repositories(db: Any, payload: dict) -> None:
    installation_payload = payload.get("installation") or {}
    github_installation_id = installation_payload.get("id")

    installation = (
        db.query(Installation)
        .filter_by(github_installation_id=github_installation_id)
        .one_or_none()
    )
    if installation is None:
        logger.warning(
            "installation_repositories event for unknown installation",
            extra={"github_installation_id": github_installation_id},
        )
        return

    for repo_payload in payload.get("repositories_added", []):
        github_repo_id = repo_payload.get("id")
        repository = db.query(Repository).filter_by(github_repo_id=github_repo_id).one_or_none()
        full_name = repo_payload.get("full_name", "")
        owner, _, name = full_name.partition("/")
        if repository is None:
            db.add(
                Repository(
                    installation_id=installation.id,
                    github_repo_id=github_repo_id,
                    owner=owner,
                    name=name,
                    full_name=full_name,
                    is_active=True,
                )
            )
        else:
            repository.is_active = True
            repository.installation_id = installation.id

    for repo_payload in payload.get("repositories_removed", []):
        github_repo_id = repo_payload.get("id")
        repository = db.query(Repository).filter_by(github_repo_id=github_repo_id).one_or_none()
        if repository is not None:
            repository.is_active = False

    db.commit()


_HANDLERS = {
    "installation": _handle_installation,
    "installation_repositories": _handle_installation_repositories,
}


@celery_app.task(name="reviewrush.process_github_webhook")
def process_github_webhook(delivery_id: str, event_type: str, payload: dict) -> str:
    """Route one verified, deduplicated webhook delivery to its handler.

    Events without a dedicated handler (push, pull_request, pull_request_review,
    check_run, check_suite) are only acknowledged here — handling them is later phases.
    """
    db = SessionLocal()
    try:
        handler = _HANDLERS.get(event_type)
        if handler is not None:
            handler(db, payload)
        _mark_delivery(db, delivery_id, "processed")
        return "processed"
    except Exception:
        logger.exception(
            "github webhook processing failed",
            extra={"delivery_id": delivery_id, "event_type": event_type},
        )
        db.rollback()
        _mark_delivery(db, delivery_id, "failed")
        return "failed"
    finally:
        db.close()
