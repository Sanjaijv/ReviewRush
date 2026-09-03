from unittest.mock import MagicMock

from app.models import Organization, OrganizationMember
from app.tenancy.membership import is_elevated, sync_membership


class _FakeInstallation:
    def __init__(self, account_type: str) -> None:
        self.account_type = account_type


def _organization(account_type: str) -> Organization:
    org = Organization(id=1, installation_id=1, slug="acme", name="acme")
    org.installation = _FakeInstallation(account_type)
    return org


def test_personal_account_installer_becomes_owner() -> None:
    db = MagicMock()
    db.query.return_value.filter_by.return_value.one_or_none.return_value = None

    member = sync_membership(
        db, _organization("User"), github_user_id=7, login="octocat"
    )

    assert member.role == "owner"


def test_org_account_member_defaults_to_member_role() -> None:
    db = MagicMock()
    db.query.return_value.filter_by.return_value.one_or_none.return_value = None

    member = sync_membership(
        db, _organization("Organization"), github_user_id=7, login="octocat"
    )

    assert member.role == "member"


def test_existing_admin_is_not_downgraded_on_relogin() -> None:
    existing = OrganizationMember(
        id=1, organization_id=1, github_user_id=7, login="octocat", role="admin"
    )
    db = MagicMock()
    db.query.return_value.filter_by.return_value.one_or_none.return_value = existing

    member = sync_membership(
        db, _organization("Organization"), github_user_id=7, login="octocat"
    )

    assert member is existing
    assert member.role == "admin"
    db.add.assert_not_called()


def test_is_elevated() -> None:
    assert is_elevated("owner")
    assert is_elevated("admin")
    assert not is_elevated("member")
