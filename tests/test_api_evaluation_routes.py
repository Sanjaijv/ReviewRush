from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.config import Settings, get_settings
from app.db import get_db
from app.evaluation.promotion import BenchmarkThresholdNotMet, EvalRunNotFound
from app.evaluation.runner import EvalTargetNotFound
from app.main import app
from app.models import EvalRun


@pytest.fixture
def eval_settings() -> Settings:
    return Settings(eval_enabled=True, eval_admin_token="secret-token")


@pytest.fixture
def client(eval_settings: Settings):
    app.dependency_overrides[get_settings] = lambda: eval_settings
    app.dependency_overrides[get_db] = lambda: MagicMock()
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.pop(get_settings, None)
        app.dependency_overrides.pop(get_db, None)


def _auth() -> dict[str, str]:
    return {"Authorization": "Bearer secret-token"}


def test_eval_admin_route_404_when_disabled() -> None:
    app.dependency_overrides[get_settings] = lambda: Settings(eval_enabled=False)
    try:
        with TestClient(app) as c:
            response = c.post("/api/v1/eval/benchmark/load", headers=_auth())
    finally:
        app.dependency_overrides.pop(get_settings, None)

    assert response.status_code == 404


def test_eval_admin_route_rejects_missing_token(client: TestClient) -> None:
    response = client.post("/api/v1/eval/benchmark/load")
    assert response.status_code == 401


def test_eval_admin_route_rejects_wrong_token(client: TestClient) -> None:
    response = client.post(
        "/api/v1/eval/benchmark/load", headers={"Authorization": "Bearer wrong"}
    )
    assert response.status_code == 401


def test_eval_admin_route_503_when_token_not_configured() -> None:
    app.dependency_overrides[get_settings] = lambda: Settings(
        eval_enabled=True, eval_admin_token=""
    )
    app.dependency_overrides[get_db] = lambda: MagicMock()
    try:
        with TestClient(app) as c:
            response = c.post("/api/v1/eval/benchmark/load", headers=_auth())
    finally:
        app.dependency_overrides.pop(get_settings, None)
        app.dependency_overrides.pop(get_db, None)

    assert response.status_code == 503


def test_load_benchmark_returns_loaded_cases(client: TestClient) -> None:
    fake_case = MagicMock(id=1, slug="clean-rename-variable", category="clean")
    with patch("app.api.v1.evaluation.load_fixed_benchmark_cases", return_value=[fake_case]):
        response = client.post("/api/v1/eval/benchmark/load", headers=_auth())

    assert response.status_code == 200
    assert response.json() == [{"id": 1, "slug": "clean-rename-variable", "category": "clean"}]


def test_run_benchmark_returns_409_when_no_cases_loaded(client: TestClient) -> None:
    with patch(
        "app.api.v1.evaluation.run_benchmark_eval", side_effect=EvalTargetNotFound("no cases")
    ):
        response = client.post("/api/v1/eval/benchmark/run", headers=_auth())

    assert response.status_code == 409


def test_run_benchmark_returns_serialized_run(client: TestClient) -> None:
    run = EvalRun(
        id=1, run_type="benchmark", provider="ollama", model="m", prompt_version="1",
        policy_version="1", status="completed", case_count=4, metrics={"precision": 1.0},
        created_at=datetime.now(UTC),
    )
    with patch("app.api.v1.evaluation.run_benchmark_eval", return_value=run):
        response = client.post("/api/v1/eval/benchmark/run", headers=_auth())

    assert response.status_code == 200
    body = response.json()
    assert body["id"] == 1
    assert body["metrics"] == {"precision": 1.0}


def test_create_promotion_returns_422_when_thresholds_not_met(client: TestClient) -> None:
    with patch(
        "app.api.v1.evaluation.promote_configuration",
        side_effect=BenchmarkThresholdNotMet("precision too low"),
    ):
        response = client.post(
            "/api/v1/eval/promotions", headers=_auth(), json={"eval_run_id": 1}
        )

    assert response.status_code == 422


def test_create_promotion_returns_404_when_run_missing(client: TestClient) -> None:
    with patch("app.api.v1.evaluation.promote_configuration", side_effect=EvalRunNotFound(1)):
        response = client.post(
            "/api/v1/eval/promotions", headers=_auth(), json={"eval_run_id": 1}
        )

    assert response.status_code == 404


def test_create_promotion_succeeds(client: TestClient) -> None:
    from app.models import ModelPromotion

    promotion = ModelPromotion(
        id=1, eval_run_id=1, provider="ollama", model="m", prompt_version="1",
        policy_version="1", actor_user_id=0, actor_login="eval-admin",
        created_at=datetime.now(UTC),
    )
    with patch("app.api.v1.evaluation.promote_configuration", return_value=promotion):
        response = client.post(
            "/api/v1/eval/promotions", headers=_auth(), json={"eval_run_id": 1}
        )

    assert response.status_code == 200
    assert response.json()["eval_run_id"] == 1
