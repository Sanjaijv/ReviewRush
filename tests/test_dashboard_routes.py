from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from app.config import Settings, get_settings
from app.dashboard.deps import DashboardUser, get_authorized_repository, get_current_user
from app.db import get_db
from app.main import app
from app.models import AIFinding, Repository


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


def test_login_redirects_to_github(client: TestClient) -> None:
    response = client.get("/api/v1/dashboard/auth/login", follow_redirects=False)

    assert response.status_code == 302
    assert response.headers["location"].startswith("https://github.com/login/oauth/authorize")
    assert "rr_oauth_state" in response.cookies


def test_login_is_disabled_when_dashboard_disabled() -> None:
    app.dependency_overrides[get_settings] = lambda: Settings(dashboard_enabled=False)
    try:
        with TestClient(app) as c:
            response = c.get("/api/v1/dashboard/auth/login", follow_redirects=False)
    finally:
        app.dependency_overrides.pop(get_settings, None)

    assert response.status_code == 503


def test_me_requires_authentication(client: TestClient) -> None:
    response = client.get("/api/v1/dashboard/me")
    assert response.status_code == 401


def test_repository_route_is_404_for_unauthorized_repo(client: TestClient) -> None:
    def fake_user() -> DashboardUser:
        return DashboardUser(
            github_user_id=1, login="octocat", avatar_url="", installation_ids=frozenset({100})
        )

    fake_db = MagicMock()
    fake_repo = Repository(id=1, installation_id=1, github_repo_id=1, owner="acme", name="w")
    fake_repo.installation = MagicMock(github_installation_id=999)  # not in user's set
    fake_db.get.return_value = fake_repo

    app.dependency_overrides[get_current_user] = fake_user
    app.dependency_overrides[get_db] = lambda: fake_db
    try:
        response = client.get("/api/v1/dashboard/repositories/1/metrics")
    finally:
        app.dependency_overrides.pop(get_current_user, None)
        app.dependency_overrides.pop(get_db, None)

    assert response.status_code == 404


def test_authorized_repository_config_route_returns_repository_file_source(
    client: TestClient,
) -> None:
    def fake_user() -> DashboardUser:
        return DashboardUser(
            github_user_id=1, login="octocat", avatar_url="", installation_ids=frozenset({100})
        )

    def fake_repo() -> Repository:
        repo = Repository(id=1, installation_id=1, github_repo_id=1, owner="acme", name="w")
        return repo

    fake_db = MagicMock()
    chain = fake_db.query.return_value.filter_by.return_value.order_by.return_value
    chain.first.return_value = None

    app.dependency_overrides[get_current_user] = fake_user
    app.dependency_overrides[get_authorized_repository] = fake_repo
    app.dependency_overrides[get_db] = lambda: fake_db
    try:
        response = client.get("/api/v1/dashboard/repositories/1/config")
    finally:
        app.dependency_overrides.pop(get_current_user, None)
        app.dependency_overrides.pop(get_authorized_repository, None)
        app.dependency_overrides.pop(get_db, None)

    assert response.status_code == 200
    assert response.json() == {"source": "repository_file", "version": None, "config": None}


def test_config_put_rejects_invalid_schema(client: TestClient) -> None:
    def fake_user() -> DashboardUser:
        return DashboardUser(
            github_user_id=1, login="octocat", avatar_url="", installation_ids=frozenset({100})
        )

    def fake_repo() -> Repository:
        return Repository(id=1, installation_id=1, github_repo_id=1, owner="acme", name="w")

    fake_db = MagicMock()

    app.dependency_overrides[get_current_user] = fake_user
    app.dependency_overrides[get_authorized_repository] = fake_repo
    app.dependency_overrides[get_db] = lambda: fake_db
    try:
        response = client.put(
            "/api/v1/dashboard/repositories/1/config",
            json={"config": {"version": 1, "not_a_real_field": True}},
        )
    finally:
        app.dependency_overrides.pop(get_current_user, None)
        app.dependency_overrides.pop(get_authorized_repository, None)
        app.dependency_overrides.pop(get_db, None)

    assert response.status_code == 422
    fake_db.add.assert_not_called()


def test_feedback_rejects_finding_from_other_repository(client: TestClient) -> None:
    def fake_user() -> DashboardUser:
        return DashboardUser(
            github_user_id=1, login="octocat", avatar_url="", installation_ids=frozenset({100})
        )

    def fake_repo() -> Repository:
        return Repository(id=1, installation_id=1, github_repo_id=1, owner="acme", name="w")

    fake_db = MagicMock()
    fake_db.get.return_value = AIFinding(id=9, ai_review_id=1, repository_id=999, file="a.py")

    app.dependency_overrides[get_current_user] = fake_user
    app.dependency_overrides[get_authorized_repository] = fake_repo
    app.dependency_overrides[get_db] = lambda: fake_db
    try:
        response = client.post(
            "/api/v1/dashboard/repositories/1/findings/9/feedback",
            json={"reaction": "useful", "consent": True},
        )
    finally:
        app.dependency_overrides.pop(get_current_user, None)
        app.dependency_overrides.pop(get_authorized_repository, None)
        app.dependency_overrides.pop(get_db, None)

    assert response.status_code == 404


def test_feedback_rejects_invalid_reaction(client: TestClient) -> None:
    def fake_user() -> DashboardUser:
        return DashboardUser(
            github_user_id=1, login="octocat", avatar_url="", installation_ids=frozenset({100})
        )

    def fake_repo() -> Repository:
        return Repository(id=1, installation_id=1, github_repo_id=1, owner="acme", name="w")

    fake_db = MagicMock()
    fake_db.get.return_value = AIFinding(id=9, ai_review_id=1, repository_id=1, file="a.py")

    app.dependency_overrides[get_current_user] = fake_user
    app.dependency_overrides[get_authorized_repository] = fake_repo
    app.dependency_overrides[get_db] = lambda: fake_db
    try:
        response = client.post(
            "/api/v1/dashboard/repositories/1/findings/9/feedback",
            json={"reaction": "not_a_real_reaction", "consent": True},
        )
    finally:
        app.dependency_overrides.pop(get_current_user, None)
        app.dependency_overrides.pop(get_authorized_repository, None)
        app.dependency_overrides.pop(get_db, None)

    assert response.status_code == 422
