import hmac
import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.db import get_db
from app.evaluation.runner import EvalTargetNotFound, run_benchmark_eval
from app.finetune.comparison import EvalRunNotFound, compare_to_baseline
from app.finetune.rollback import NoPromotionToRollBackTo, rollback_active_promotion
from app.finetune.training import (
    DatasetTooSmall,
    DatasetVersionNotFound,
    FineTuneDisabled,
    FineTuneJobNotFound,
    TrainerNotConfigured,
    create_job,
    run_job,
)
from app.models import FineTuneJob, ShadowEvalResult

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/finetune", tags=["finetune"])


def _require_finetune_admin(request: Request, settings: Settings = Depends(get_settings)) -> None:
    """Gates the entire Phase 16 fine-tuning admin surface with the same
    static-bearer-token pattern `app.api.v1.evaluation._require_eval_admin`
    uses - this is the same cross-tenant governance surface, and proper
    per-organization RBAC is Phase 17's job, not this one's. Fails closed:
    disabled or an unset/empty token both reject every request.
    """
    if not settings.finetune_enabled:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    if not settings.finetune_admin_token:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, "fine-tune admin token not configured"
        )

    header = request.headers.get("Authorization") or ""
    scheme, _, token = header.partition(" ")
    if scheme.lower() != "bearer" or not hmac.compare_digest(token, settings.finetune_admin_token):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid fine-tune admin token")


def _serialize_job(job: FineTuneJob) -> dict[str, Any]:
    return {
        "id": job.id,
        "dataset_version_id": job.dataset_version_id,
        "base_model": job.base_model,
        "method": job.method,
        "status": job.status,
        "training_example_count": job.training_example_count,
        "adapter_path": job.adapter_path,
        "output_model": job.output_model,
        "error_message": job.error_message,
        "created_at": job.created_at.isoformat(),
        "started_at": job.started_at.isoformat() if job.started_at else None,
        "completed_at": job.completed_at.isoformat() if job.completed_at else None,
    }


class CreateJobRequest(BaseModel):
    dataset_version_id: int
    notes: str = ""


@router.post("/jobs", dependencies=[Depends(_require_finetune_admin)])
def create_finetune_job(
    body: CreateJobRequest,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    try:
        job = create_job(
            db,
            dataset_version_id=body.dataset_version_id,
            settings=settings,
            actor_user_id=0,
            actor_login="finetune-admin",
            notes=body.notes,
        )
    except FineTuneDisabled:
        raise HTTPException(status.HTTP_404_NOT_FOUND) from None
    except DatasetVersionNotFound:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "dataset version not found") from None
    except DatasetTooSmall as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from None
    return _serialize_job(job)


@router.post("/jobs/{job_id}/run", dependencies=[Depends(_require_finetune_admin)])
def run_finetune_job(
    job_id: int, db: Session = Depends(get_db), settings: Settings = Depends(get_settings)
) -> dict[str, Any]:
    """Runs the job synchronously in the request. `app.tasks.finetune` is
    the intended path for real training runs (which can take a long time) -
    this endpoint exists for tests and for operators who want a blocking
    call against a fast/local trainer.
    """
    try:
        job = run_job(db, job_id, settings=settings)
    except FineTuneDisabled:
        raise HTTPException(status.HTTP_404_NOT_FOUND) from None
    except FineTuneJobNotFound:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "fine-tune job not found") from None
    except TrainerNotConfigured:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, "finetune_trainer_command is not configured"
        ) from None
    return _serialize_job(job)


@router.get("/jobs/{job_id}", dependencies=[Depends(_require_finetune_admin)])
def get_finetune_job(job_id: int, db: Session = Depends(get_db)) -> dict[str, Any]:
    job = db.get(FineTuneJob, job_id)
    if job is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "fine-tune job not found")
    return _serialize_job(job)


@router.get("/jobs", dependencies=[Depends(_require_finetune_admin)])
def list_finetune_jobs(db: Session = Depends(get_db)) -> list[dict[str, Any]]:
    rows = db.query(FineTuneJob).order_by(FineTuneJob.created_at.desc()).limit(100).all()
    return [_serialize_job(r) for r in rows]


class CandidateBenchmarkRequest(BaseModel):
    job_id: int


@router.post("/jobs/{job_id}/benchmark", dependencies=[Depends(_require_finetune_admin)])
def run_candidate_benchmark(job_id: int, db: Session = Depends(get_db)) -> dict[str, Any]:
    """Runs the frozen Phase 15 benchmark against a completed job's
    `output_model`, exactly like `POST /eval/benchmark/run` does for the
    live provider/model - the roadmap's "evaluate against the generic model
    on the frozen benchmark" step, made concrete for a candidate.
    """
    job = db.get(FineTuneJob, job_id)
    if job is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "fine-tune job not found")
    if job.status != "completed" or not job.output_model:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "job is not completed or has no registered output_model to evaluate",
        )
    try:
        run = run_benchmark_eval(db, provider="ollama", model_name=job.output_model)
    except EvalTargetNotFound as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from None
    return {
        "id": run.id,
        "provider": run.provider,
        "model": run.model,
        "metrics": run.metrics,
        "created_at": run.created_at.isoformat(),
    }


class CompareRequest(BaseModel):
    candidate_run_id: int
    baseline_run_id: int


@router.post("/compare", dependencies=[Depends(_require_finetune_admin)])
def compare_runs(
    body: CompareRequest, db: Session = Depends(get_db), settings: Settings = Depends(get_settings)
) -> dict[str, Any]:
    try:
        comparison = compare_to_baseline(
            db,
            candidate_run_id=body.candidate_run_id,
            baseline_run_id=body.baseline_run_id,
            settings=settings,
        )
    except EvalRunNotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"eval run not found: {exc}") from None
    return {
        "candidate_run_id": comparison.candidate_run_id,
        "baseline_run_id": comparison.baseline_run_id,
        "recall_delta": comparison.recall_delta,
        "false_positive_rate_delta": comparison.false_positive_rate_delta,
        "passes_regression_guardrail": comparison.passes_regression_guardrail,
        "reasons": comparison.reasons,
    }


@router.get("/shadow-results", dependencies=[Depends(_require_finetune_admin)])
def list_shadow_results(db: Session = Depends(get_db)) -> list[dict[str, Any]]:
    rows = (
        db.query(ShadowEvalResult).order_by(ShadowEvalResult.created_at.desc()).limit(100).all()
    )
    return [
        {
            "id": r.id,
            "ai_review_id": r.ai_review_id,
            "finetune_job_id": r.finetune_job_id,
            "candidate_provider": r.candidate_provider,
            "candidate_model": r.candidate_model,
            "live_issue_count": r.live_issue_count,
            "candidate_issue_count": r.candidate_issue_count,
            "comparison": r.comparison,
            "status": r.status,
            "error_message": r.error_message,
            "created_at": r.created_at.isoformat(),
        }
        for r in rows
    ]


class RollbackRequest(BaseModel):
    notes: str = ""


@router.post("/rollback", dependencies=[Depends(_require_finetune_admin)])
def rollback(body: RollbackRequest, db: Session = Depends(get_db)) -> dict[str, Any]:
    try:
        promotion = rollback_active_promotion(
            db, actor_user_id=0, actor_login="finetune-admin", notes=body.notes
        )
    except NoPromotionToRollBackTo as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from None
    return {
        "id": promotion.id,
        "eval_run_id": promotion.eval_run_id,
        "provider": promotion.provider,
        "model": promotion.model,
        "created_at": promotion.created_at.isoformat(),
    }
