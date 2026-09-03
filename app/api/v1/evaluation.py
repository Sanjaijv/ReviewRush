import hmac
import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.db import get_db
from app.evaluation.benchmark import load_fixed_benchmark_cases
from app.evaluation.dataset import build_dataset_version, list_dataset_versions
from app.evaluation.promotion import (
    BenchmarkThresholdNotMet,
    EvalRunNotFound,
    get_active_promotion,
    promote_configuration,
)
from app.evaluation.runner import EvalTargetNotFound, run_benchmark_eval, run_dataset_eval
from app.models import BenchmarkCase, EvalRun

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/eval", tags=["evaluation"])


def _require_eval_admin(request: Request, settings: Settings = Depends(get_settings)) -> None:
    """Gates the Phase 15 evaluation admin surface (dataset build, benchmark
    run, promotion). This is a cross-tenant governance surface with no
    per-organization RBAC yet (proper multi-tenant access control is
    Phase 17) - a static bearer token compared in constant time is the
    minimum bar, mirroring how GET /metrics is operator-only by network
    policy alone. Fails closed: disabled or an unset/empty token both reject
    every request, there is no insecure default.
    """
    if not settings.eval_enabled:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    if not settings.eval_admin_token:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, "evaluation admin token not configured"
        )

    header = request.headers.get("Authorization") or ""
    scheme, _, token = header.partition(" ")
    if scheme.lower() != "bearer" or not hmac.compare_digest(token, settings.eval_admin_token):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid evaluation admin token")


def _serialize_run(run: EvalRun) -> dict[str, Any]:
    return {
        "id": run.id,
        "run_type": run.run_type,
        "dataset_version_id": run.dataset_version_id,
        "provider": run.provider,
        "model": run.model,
        "prompt_version": run.prompt_version,
        "policy_version": run.policy_version,
        "status": run.status,
        "case_count": run.case_count,
        "metrics": run.metrics,
        "error_message": run.error_message,
        "created_at": run.created_at.isoformat(),
    }


@router.post("/benchmark/load", dependencies=[Depends(_require_eval_admin)])
def load_benchmark(db: Session = Depends(get_db)) -> list[dict[str, Any]]:
    rows = load_fixed_benchmark_cases(db)
    return [{"id": r.id, "slug": r.slug, "category": r.category} for r in rows]


@router.get("/benchmark/cases", dependencies=[Depends(_require_eval_admin)])
def list_benchmark_cases(db: Session = Depends(get_db)) -> list[dict[str, Any]]:
    rows = db.query(BenchmarkCase).filter_by(is_active=True).all()
    return [
        {"id": r.id, "slug": r.slug, "category": r.category, "description": r.description}
        for r in rows
    ]


@router.post("/benchmark/run", dependencies=[Depends(_require_eval_admin)])
def run_benchmark(db: Session = Depends(get_db)) -> dict[str, Any]:
    try:
        run = run_benchmark_eval(db)
    except EvalTargetNotFound as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from None
    return _serialize_run(run)


class DatasetBuildRequest(BaseModel):
    notes: str = ""


@router.post("/dataset/build", dependencies=[Depends(_require_eval_admin)])
def build_dataset(body: DatasetBuildRequest, db: Session = Depends(get_db)) -> dict[str, Any]:
    version = build_dataset_version(
        db, actor_user_id=0, actor_login="eval-admin", notes=body.notes
    )
    return {"id": version.id, "version": version.version, "item_count": version.item_count}


@router.get("/dataset/versions", dependencies=[Depends(_require_eval_admin)])
def dataset_versions(db: Session = Depends(get_db)) -> list[dict[str, Any]]:
    return [
        {
            "id": v.id,
            "version": v.version,
            "item_count": v.item_count,
            "created_at": v.created_at.isoformat(),
        }
        for v in list_dataset_versions(db)
    ]


@router.post("/dataset/{dataset_version_id}/run", dependencies=[Depends(_require_eval_admin)])
def run_dataset(dataset_version_id: int, db: Session = Depends(get_db)) -> dict[str, Any]:
    try:
        run = run_dataset_eval(db, dataset_version_id)
    except EvalTargetNotFound as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from None
    return _serialize_run(run)


@router.get("/runs", dependencies=[Depends(_require_eval_admin)])
def list_runs(db: Session = Depends(get_db)) -> list[dict[str, Any]]:
    rows = db.query(EvalRun).order_by(EvalRun.created_at.desc()).limit(100).all()
    return [_serialize_run(r) for r in rows]


@router.get("/runs/{run_id}", dependencies=[Depends(_require_eval_admin)])
def get_run(run_id: int, db: Session = Depends(get_db)) -> dict[str, Any]:
    run: Any = db.get(EvalRun, run_id)
    if run is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "eval run not found")
    return _serialize_run(run)


class PromotionRequest(BaseModel):
    eval_run_id: int
    notes: str = ""


@router.post("/promotions", dependencies=[Depends(_require_eval_admin)])
def create_promotion(body: PromotionRequest, db: Session = Depends(get_db)) -> dict[str, Any]:
    try:
        promotion = promote_configuration(
            db,
            eval_run_id=body.eval_run_id,
            actor_user_id=0,
            actor_login="eval-admin",
            notes=body.notes,
        )
    except EvalRunNotFound:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "eval run not found") from None
    except BenchmarkThresholdNotMet as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, exc.message) from None
    return {
        "id": promotion.id,
        "eval_run_id": promotion.eval_run_id,
        "provider": promotion.provider,
        "model": promotion.model,
        "prompt_version": promotion.prompt_version,
        "policy_version": promotion.policy_version,
        "created_at": promotion.created_at.isoformat(),
    }


@router.get("/promotions/active", dependencies=[Depends(_require_eval_admin)])
def active_promotion(db: Session = Depends(get_db)) -> dict[str, Any] | None:
    promotion = get_active_promotion(db)
    if promotion is None:
        return None
    return {
        "id": promotion.id,
        "eval_run_id": promotion.eval_run_id,
        "provider": promotion.provider,
        "model": promotion.model,
        "prompt_version": promotion.prompt_version,
        "policy_version": promotion.policy_version,
        "created_at": promotion.created_at.isoformat(),
    }
