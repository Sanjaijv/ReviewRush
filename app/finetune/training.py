"""Orchestrates one Phase 16 fine-tuning attempt: export training data from a
frozen `EvalDatasetVersion`, invoke an operator-supplied external trainer
process, and (optionally) register the resulting adapter as a model tag
reachable through the existing provider-neutral `ReviewModel` interface.

This module deliberately does not bundle a trainer. `finetune_trainer_command`
points at an external LoRA/QLoRA training script (e.g. axolotl, unsloth,
peft) the operator has vetted and provisioned with appropriate hardware -
the same boundary `analysis_docker_binary` draws around the deterministic
analysis sandbox: this application shells out to it, it does not implement
it.
"""

import logging
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy.orm import Session

from app.config import Settings
from app.finetune.export import build_training_records, write_jsonl
from app.models import EvalDatasetVersion, FineTuneJob

logger = logging.getLogger(__name__)


class FineTuneDisabled(Exception):
    pass


class DatasetTooSmall(Exception):
    def __init__(self, actual: int, minimum: int):
        super().__init__(f"dataset has {actual} examples, minimum is {minimum}")
        self.actual = actual
        self.minimum = minimum


class TrainerNotConfigured(Exception):
    pass


class DatasetVersionNotFound(Exception):
    pass


class FineTuneJobNotFound(Exception):
    pass


def create_job(
    db: Session,
    *,
    dataset_version_id: int,
    settings: Settings,
    actor_user_id: int,
    actor_login: str,
    notes: str = "",
) -> FineTuneJob:
    """Creates a `pending` FineTuneJob row after enforcing the roadmap's
    prerequisite that fine-tuning only proceeds with enough training
    examples. Training itself is not started here - `run_job` does that
    separately so job creation and execution can be retried independently.
    """
    if not settings.finetune_enabled:
        raise FineTuneDisabled()

    dataset_version = db.get(EvalDatasetVersion, dataset_version_id)
    if dataset_version is None:
        raise DatasetVersionNotFound(dataset_version_id)
    if dataset_version.item_count < settings.finetune_min_training_examples:
        raise DatasetTooSmall(dataset_version.item_count, settings.finetune_min_training_examples)

    job = FineTuneJob(
        dataset_version_id=dataset_version_id,
        base_model=settings.finetune_base_model,
        method=settings.finetune_method,
        hyperparams={},
        status="pending",
        training_example_count=dataset_version.item_count,
        actor_user_id=actor_user_id,
        actor_login=actor_login,
        notes=notes,
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    return job


def _build_ollama_modelfile(*, base_model: str, adapter_path: str) -> str:
    return f"FROM {base_model}\nADAPTER {adapter_path}\n"


def _register_ollama_model(
    *, settings: Settings, output_model: str, base_model: str, adapter_path: str
) -> tuple[bool, str]:
    """Best-effort `ollama create` registration so the fine-tuned adapter
    becomes just another model tag `OllamaReviewModel` can call - no new
    ReviewModel implementation is needed. Returns (ok, message).
    """
    modelfile_path = Path(settings.finetune_output_dir) / f"{output_model}.Modelfile"
    modelfile_path.parent.mkdir(parents=True, exist_ok=True)
    modelfile_path.write_text(
        _build_ollama_modelfile(base_model=base_model, adapter_path=adapter_path)
    )
    try:
        completed = subprocess.run(
            [settings.finetune_ollama_binary, "create", output_model, "-f", str(modelfile_path)],
            capture_output=True,
            timeout=settings.finetune_trainer_timeout_seconds,
            text=True,
        )
    except subprocess.TimeoutExpired:
        return False, "ollama create timed out"
    except FileNotFoundError as exc:
        return False, f"ollama executable not found: {exc}"

    if completed.returncode != 0:
        return False, f"ollama create failed: {completed.stderr[-2000:]}"
    return True, completed.stdout[-2000:]


def run_job(db: Session, job_id: int, *, settings: Settings) -> FineTuneJob:
    """Runs one FineTuneJob synchronously: export -> external trainer ->
    (optional) model registration. Called from `app.tasks.finetune` inside a
    Celery task, but kept synchronous/side-effect-explicit here so it can
    also be exercised directly in tests without a broker.

    Every failure path sets `status="failed"` with `error_message` rather
    than raising past this point once the job has started running - a
    fine-tuning job's failure must never surface as an unhandled worker
    exception that could be mistaken for an infrastructure retry case.
    """
    if not settings.finetune_enabled:
        raise FineTuneDisabled()

    job: FineTuneJob | None = db.get(FineTuneJob, job_id)
    if job is None:
        raise FineTuneJobNotFound(job_id)

    if not settings.finetune_trainer_command:
        job.status = "failed"
        job.error_message = "finetune_trainer_command is not configured"
        db.commit()
        raise TrainerNotConfigured()

    job.status = "running"
    job.started_at = datetime.now(UTC)
    db.commit()

    records = build_training_records(db, job.dataset_version_id)
    dataset_path = Path(settings.finetune_output_dir) / f"job-{job.id}" / "train.jsonl"
    write_jsonl(records, dataset_path)

    adapter_dir = Path(settings.finetune_output_dir) / f"job-{job.id}" / "adapter"
    adapter_dir.mkdir(parents=True, exist_ok=True)

    args = [
        settings.finetune_trainer_command,
        "--base-model",
        job.base_model,
        "--method",
        job.method,
        "--train-file",
        str(dataset_path),
        "--output-dir",
        str(adapter_dir),
    ]

    started = time.monotonic()
    try:
        completed = subprocess.run(
            args,
            capture_output=True,
            timeout=settings.finetune_trainer_timeout_seconds,
            text=True,
        )
    except subprocess.TimeoutExpired:
        job.status = "failed"
        job.error_message = f"trainer timed out after {settings.finetune_trainer_timeout_seconds}s"
        db.commit()
        return job
    except FileNotFoundError as exc:
        job.status = "failed"
        job.error_message = f"trainer command not found: {exc}"
        db.commit()
        return job

    duration_ms = int((time.monotonic() - started) * 1000)
    job.log_excerpt = (completed.stdout[-4000:] + "\n" + completed.stderr[-4000:]).strip()

    if completed.returncode != 0:
        job.status = "failed"
        job.error_message = f"trainer exited {completed.returncode}"
        db.commit()
        logger.error(
            "fine-tune trainer failed",
            extra={
                "job_id": job.id,
                "returncode": completed.returncode,
                "duration_ms": duration_ms,
            },
        )
        return job

    job.adapter_path = str(adapter_dir)
    output_model = f"reviewrush-finetune-{job.id}"

    if settings.finetune_ollama_create_enabled:
        ok, message = _register_ollama_model(
            settings=settings,
            output_model=output_model,
            base_model=job.base_model,
            adapter_path=job.adapter_path,
        )
        if not ok:
            job.status = "failed"
            job.error_message = f"model registration failed: {message}"
            db.commit()
            return job
        job.output_model = output_model
    else:
        # No registration step requested: the adapter exists on disk but is
        # not yet reachable through the ReviewModel interface under any tag.
        job.output_model = None

    job.status = "completed"
    job.completed_at = datetime.now(UTC)
    db.commit()
    db.refresh(job)
    return job
