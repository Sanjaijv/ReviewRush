from unittest.mock import MagicMock

from app.models import Installation, Organization
from app.tenancy.provisioning import get_or_create_organization


def _installation(**overrides) -> Installation:
    defaults = dict(
        id=1, github_installation_id=100, account_login="acme", account_type="Organization"
    )
    defaults.update(overrides)
    return Installation(**defaults)


def test_creates_one_organization_per_installation() -> None:
    db = MagicMock()
    db.query.return_value.filter_by.return_value.one_or_none.return_value = None

    organization = get_or_create_organization(db, _installation())

    db.add.assert_called_once()
    added = db.add.call_args[0][0]
    assert isinstance(added, Organization)
    assert added.installation_id == 1
    assert added.slug == "acme"
    assert added.name == "acme"
    assert organization is added


def test_returns_existing_organization_idempotently() -> None:
    existing = Organization(id=5, installation_id=1, slug="acme", name="acme")
    db = MagicMock()
    db.query.return_value.filter_by.return_value.one_or_none.return_value = existing

    organization = get_or_create_organization(db, _installation())

    db.add.assert_not_called()
    assert organization is existing


def test_slug_falls_back_to_installation_id_when_login_missing() -> None:
    db = MagicMock()
    db.query.return_value.filter_by.return_value.one_or_none.return_value = None

    get_or_create_organization(db, _installation(account_login=""))

    added = db.add.call_args[0][0]
    assert added.slug == "installation-1"
