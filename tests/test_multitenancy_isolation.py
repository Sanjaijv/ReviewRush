from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from app.config import Settings, get_settings
from app.dashboard.deps import (
    DashboardUser,
    get_authorized_organization,
    get_current_user,
    require_org_admin,
)
from app.db import get_db
from app.main import app
from app.models import Organization

ORG_A_ID = 1
ORG_B_ID = 2


@pytest.fixture
def dashboard_settings() -> Settings:
    return Settings(
        dashboard_enabled=True,
        github_oauth_client_id="client-id",
        github_oauth_client_secret="client-secret",
        dashboard_session_secret="test-secret",
        dashboard_base_url="http://testserver",
        environment="development",
    )


@pytest.fixture
def client(dashboard_settings: Settings):
    app.dependency_overrides[get_settings] = lambda: dashboard_settings
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.pop(get_settings, None)


def _user_in_org_a() -> DashboardUser:
    return DashboardUser(
        github_user_id=1,
        login="octocat",
        avatar_url="",
        installation_ids=frozenset({100}),
        organization_roles={ORG_A_ID: "admin"},
    )


def test_user_from_org_a_gets_404_for_org_b_settings(client: TestClient) -> None:
    fake_db = MagicMock()
    fake_db.get.return_value = Organization(
        id=ORG_B_ID, installation_id=2, slug="org-b", name="Org B"
    )

    app.dependency_overrides[get_current_user] = _user_in_org_a
    app.dependency_overrides[get_db] = lambda: fake_db
    try:
        response = client.get(f"/api/v1/dashboard/organizations/{ORG_B_ID}")
    finally:
        app.dependency_overrides.pop(get_current_user, None)
        app.dependency_overrides.pop(get_db, None)

    assert response.status_code == 404


def test_user_from_org_a_gets_404_deleting_org_b_data(client: TestClient) -> None:
    fake_db = MagicMock()
    fake_db.get.return_value = Organization(
        id=ORG_B_ID, installation_id=2, slug="org-b", name="Org B"
    )

    app.dependency_overrides[get_current_user] = _user_in_org_a
    app.dependency_overrides[get_db] = lambda: fake_db
    try:
        response = client.post(
            f"/api/v1/dashboard/organizations/{ORG_B_ID}/delete-data",
            json={"confirm_slug": "org-b"},
        )
    finally:
        app.dependency_overrides.pop(get_current_user, None)
        app.dependency_overrides.pop(get_db, None)

    assert response.status_code == 404


def test_member_role_cannot_delete_own_org_data(client: TestClient) -> None:
    def member_user() -> DashboardUser:
        return DashboardUser(
            github_user_id=1,
            login="octocat",
            avatar_url="",
            installation_ids=frozenset({100}),
            organization_roles={ORG_A_ID: "member"},
        )

    fake_db = MagicMock()
    fake_db.get.return_value = Organization(
        id=ORG_A_ID, installation_id=1, slug="org-a", name="Org A"
    )

    app.dependency_overrides[get_current_user] = member_user
    app.dependency_overrides[get_db] = lambda: fake_db
    try:
        response = client.post(
            f"/api/v1/dashboard/organizations/{ORG_A_ID}/delete-data",
            json={"confirm_slug": "org-a"},
        )
    finally:
        app.dependency_overrides.pop(get_current_user, None)
        app.dependency_overrides.pop(get_db, None)

    assert response.status_code == 403


def test_admin_role_can_reach_delete_data_dependency_but_wrong_slug_is_rejected(
    client: TestClient,
) -> None:
    fake_db = MagicMock()
    fake_db.get.return_value = Organization(
        id=ORG_A_ID, installation_id=1, slug="org-a", name="Org A"
    )

    app.dependency_overrides[get_current_user] = _user_in_org_a
    app.dependency_overrides[get_db] = lambda: fake_db
    try:
        response = client.post(
            f"/api/v1/dashboard/organizations/{ORG_A_ID}/delete-data",
            json={"confirm_slug": "not-the-right-slug"},
        )
    finally:
        app.dependency_overrides.pop(get_current_user, None)
        app.dependency_overrides.pop(get_db, None)

    assert response.status_code == 422


def test_get_authorized_organization_is_404_not_403_for_nonmember() -> None:
    from fastapi import HTTPException

    db = MagicMock()
    db.get.return_value = Organization(
        id=ORG_B_ID, installation_id=2, slug="org-b", name="Org B"
    )

    with pytest.raises(HTTPException) as exc_info:
        get_authorized_organization(ORG_B_ID, user=_user_in_org_a(), db=db)

    assert exc_info.value.status_code == 404


def test_require_org_admin_rejects_member_role() -> None:
    from fastapi import HTTPException

    org = Organization(
        id=ORG_A_ID, installation_id=1, slug="org-a", name="Org A"
    )
    user = DashboardUser(
        github_user_id=1,
        login="octocat",
        avatar_url="",
        installation_ids=frozenset({100}),
        organization_roles={ORG_A_ID: "member"},
    )

    with pytest.raises(HTTPException) as exc_info:
        require_org_admin(organization=org, user=user)

    assert exc_info.value.status_code == 403
