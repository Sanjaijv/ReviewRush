import logging
from typing import Any

from app.models import Installation, Organization

logger = logging.getLogger(__name__)


def _slug_for(installation: Installation) -> str:
    base = (installation.account_login or f"installation-{installation.id}").strip().lower()
    return base or f"installation-{installation.id}"


def get_or_create_organization(db: Any, installation: Installation) -> Organization:
    """Fetch the tenant Organization for one Installation, creating it if
    this is the first time we've seen it.

    One Organization per Installation, always - see `app.models.tenancy`
    for why the boundary is drawn there rather than allowing manual
    cross-installation grouping. Idempotent: a second call for the same
    installation returns the existing row rather than creating a duplicate
    (enforced by the unique constraint on `installation_id` as the source of
    truth under concurrent webhook deliveries, this lookup is just the fast
    path).
    """
    existing = db.query(Organization).filter_by(installation_id=installation.id).one_or_none()
    if existing is not None:
        return existing

    slug = _slug_for(installation)
    if db.query(Organization).filter_by(slug=slug).one_or_none() is not None:
        slug = f"{slug}-{installation.id}"

    organization = Organization(
        installation_id=installation.id,
        slug=slug,
        name=installation.account_login or slug,
    )
    # Populate the relationship in-memory immediately rather than relying on
    # a later lazy-load - callers commonly need `organization.installation`
    # right after provisioning (e.g. resolving plan limits against
    # `organization.installation.repositories`), and the object we already
    # have here is authoritative.
    organization.installation = installation
    db.add(organization)
    try:
        db.flush()
    except Exception:
        # Another concurrent request already created it - defer to that row
        # rather than racing on the unique constraint.
        db.rollback()
        existing = db.query(Organization).filter_by(installation_id=installation.id).one_or_none()
        if existing is not None:
            return existing
        raise
    logger.info(
        "organization provisioned",
        extra={"organization_id": organization.id, "installation_id": installation.id},
    )
    return organization
