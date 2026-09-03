from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.config import Settings, get_settings
from app.db import get_db
from app.evaluation.runner import EvalTargetNotFound
from app.finetune.comparison import EvalRunNotFound
from app.finetune.rollback import NoPromotionToRollBackTo
from app.finetune.training import DatasetTooSmall, DatasetVersionNotFound, FineTuneJobNotFound
from app.main import app
from app.models import EvalRun, FineTuneJob, ModelPromotion


@pytest.fixture
def finetune_settings() -> Settings:
    return Settings(finetune_enabled=True, finetune_admin_token="secret-token")


@pytest.fixture
def client(finetune_settings: Settings):
    app.dependency_overrides[get_settings] = lambda: finetune_settings
    app.dependency_overrides[get_db] = lambda: MagicMock()
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.pop(get_settings, None)
        app.dependency_overrides.pop(get_db, None)


def _auth() -> dict[str, str]:
    return {"Authorization": "Bearer secret-token"}


def test_finetune_admin_route_404_when_disabled() -> None:
    app.dependency_overrides[get_settings] = lambda: Settings(finetune_enabled=False)
    try:
        with TestClient(app) as c:
            response = c.get("/api/v1/finetune/jobs", headers=_auth())
    finally:
        app.dependency_overrides.pop(get_settings, None)

    assert response.status_code == 404


def test_finetune_admin_route_rejects_missing_token(client: TestClient) -> None:
    response = client.get("/api/v1/finetune/jobs")
    assert response.status_code == 401


def test_finetune_admin_route_rejects_wrong_token(client: TestClient) -> None:
    response = client.get("/api/v1/finetune/jobs", headers={"Authorization": "Bearer wrong"})
    assert response.status_code == 401


def test_finetune_admin_route_503_when_token_not_configured() -> None:
    app.dependency_overrides[get_settings] = lambda: Settings(
        finetune_enabled=True, finetune_admin_token=""
    )
    app.dependency_overrides[get_db] = lambda: MagicMock()
    try:
        with TestClient(app) as c:
            response = c.get("/api/v1/finetune/jobs", headers=_auth())
    finally:
        app.dependency_overrides.pop(get_settings, None)
        app.dependency_overrides.pop(get_db, None)

    assert response.status_code == 503


def _job(**overrides) -> FineTuneJob:
    defaults = dict(
        id=1, dataset_version_id=1, base_model="qwen2.5-coder:7b", method="lora",
        status="pending", training_example_count=1000, created_at=datetime.now(UTC),
    )
    defaults.update(overrides)
    return FineTuneJob(**defaults)


def test_create_job_returns_422_when_dataset_too_small(client: TestClient) -> None:
    with patch("app.api.v1.finetune.create_job", side_effect=DatasetTooSmall(1, 1000)):
        response = client.post(
            "/api/v1/finetune/jobs", headers=_auth(), json={"dataset_version_id": 1}
        )
    assert response.status_code == 422


def test_create_job_returns_404_when_dataset_missing(client: TestClient) -> None:
    with patch("app.api.v1.finetune.create_job", side_effect=DatasetVersionNotFound(1)):
        response = client.post(
            "/api/v1/finetune/jobs", headers=_auth(), json={"dataset_version_id": 1}
        )
    assert response.status_code == 404


def test_create_job_succeeds(client: TestClient) -> None:
    job = _job()
    with patch("app.api.v1.finetune.create_job", return_value=job):
        response = client.post(
            "/api/v1/finetune/jobs", headers=_auth(), json={"dataset_version_id": 1}
        )
    assert response.status_code == 200
    assert response.json()["status"] == "pending"


def test_run_job_returns_404_when_missing(client: TestClient) -> None:
    with patch("app.api.v1.finetune.run_job", side_effect=FineTuneJobNotFound(1)):
        response = client.post("/api/v1/finetune/jobs/1/run", headers=_auth())
    assert response.status_code == 404


def test_run_job_succeeds(client: TestClient) -> None:
    job = _job(status="completed", output_model="reviewrush-finetune-1")
    with patch("app.api.v1.finetune.run_job", return_value=job):
        response = client.post("/api/v1/finetune/jobs/1/run", headers=_auth())
    assert response.status_code == 200
    assert response.json()["output_model"] == "reviewrush-finetune-1"


def test_get_job_returns_404_when_missing(client: TestClient) -> None:
    app.dependency_overrides[get_db] = lambda: MagicMock(get=MagicMock(return_value=None))
    response = client.get("/api/v1/finetune/jobs/1", headers=_auth())
    assert response.status_code == 404


def test_candidate_benchmark_returns_409_when_job_not_completed(client: TestClient) -> None:
    db = MagicMock(get=MagicMock(return_value=_job(status="running")))
    app.dependency_overrides[get_db] = lambda: db
    response = client.post("/api/v1/finetune/jobs/1/benchmark", headers=_auth())
    assert response.status_code == 409


def test_candidate_benchmark_returns_409_when_no_benchmark_cases(client: TestClient) -> None:
    db = MagicMock(get=MagicMock(return_value=_job(status="completed", output_model="m")))
    app.dependency_overrides[get_db] = lambda: db
    with patch(
        "app.api.v1.finetune.run_benchmark_eval", side_effect=EvalTargetNotFound("no cases")
    ):
        response = client.post("/api/v1/finetune/jobs/1/benchmark", headers=_auth())
    assert response.status_code == 409


def test_candidate_benchmark_succeeds(client: TestClient) -> None:
    db = MagicMock(get=MagicMock(return_value=_job(status="completed", output_model="m")))
    app.dependency_overrides[get_db] = lambda: db
    run = EvalRun(
        id=2, run_type="benchmark", provider="ollama", model="m", prompt_version="1",
        policy_version="1", status="completed", metrics={"recall": 0.9},
        created_at=datetime.now(UTC),
    )
    with patch("app.api.v1.finetune.run_benchmark_eval", return_value=run):
        response = client.post("/api/v1/finetune/jobs/1/benchmark", headers=_auth())
    assert response.status_code == 200
    assert response.json()["model"] == "m"


def test_compare_returns_404_when_run_missing(client: TestClient) -> None:
    with patch("app.api.v1.finetune.compare_to_baseline", side_effect=EvalRunNotFound(1)):
        response = client.post(
            "/api/v1/finetune/compare", headers=_auth(),
            json={"candidate_run_id": 1, "baseline_run_id": 2},
        )
    assert response.status_code == 404


def test_rollback_returns_409_when_nothing_to_roll_back_to(client: TestClient) -> None:
    with patch(
        "app.api.v1.finetune.rollback_active_promotion",
        side_effect=NoPromotionToRollBackTo("none"),
    ):
        response = client.post("/api/v1/finetune/rollback", headers=_auth(), json={})
    assert response.status_code == 409


def test_rollback_succeeds(client: TestClient) -> None:
    promotion = ModelPromotion(
        id=3, eval_run_id=1, provider="ollama", model="qwen2.5-coder:7b",
        prompt_version="1", policy_version="1", actor_user_id=0, actor_login="finetune-admin",
        created_at=datetime.now(UTC),
    )
    with patch("app.api.v1.finetune.rollback_active_promotion", return_value=promotion):
        response = client.post("/api/v1/finetune/rollback", headers=_auth(), json={})
    assert response.status_code == 200
    assert response.json()["model"] == "qwen2.5-coder:7b"
