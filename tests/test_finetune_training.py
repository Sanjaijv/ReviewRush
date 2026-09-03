import subprocess
from unittest.mock import MagicMock, patch

import pytest

from app.config import Settings
from app.finetune.training import (
    DatasetTooSmall,
    DatasetVersionNotFound,
    FineTuneDisabled,
    FineTuneJobNotFound,
    TrainerNotConfigured,
    create_job,
    run_job,
)
from app.models import EvalDatasetVersion, FineTuneJob


def _settings(tmp_path, **overrides) -> Settings:
    defaults = dict(
        finetune_enabled=True,
        finetune_base_model="qwen2.5-coder:7b",
        finetune_method="lora",
        finetune_trainer_command="/usr/local/bin/fake-trainer",
        finetune_trainer_timeout_seconds=60,
        finetune_output_dir=str(tmp_path),
        finetune_min_training_examples=2,
        finetune_ollama_create_enabled=False,
        finetune_ollama_binary="ollama",
    )
    defaults.update(overrides)
    return Settings(**defaults)


def test_create_job_raises_when_disabled(tmp_path) -> None:
    db = MagicMock()
    with pytest.raises(FineTuneDisabled):
        create_job(
            db, dataset_version_id=1, settings=_settings(tmp_path, finetune_enabled=False),
            actor_user_id=1, actor_login="a",
        )
    db.add.assert_not_called()


def test_create_job_raises_when_dataset_missing(tmp_path) -> None:
    db = MagicMock()
    db.get.return_value = None
    with pytest.raises(DatasetVersionNotFound):
        create_job(
            db, dataset_version_id=1, settings=_settings(tmp_path),
            actor_user_id=1, actor_login="a",
        )


def test_create_job_raises_when_dataset_too_small(tmp_path) -> None:
    db = MagicMock()
    db.get.return_value = EvalDatasetVersion(id=1, version=1, item_count=1)
    with pytest.raises(DatasetTooSmall):
        create_job(
            db, dataset_version_id=1,
            settings=_settings(tmp_path, finetune_min_training_examples=2),
            actor_user_id=1, actor_login="a",
        )


def test_create_job_succeeds(tmp_path) -> None:
    db = MagicMock()
    db.get.return_value = EvalDatasetVersion(id=1, version=1, item_count=5)
    job = create_job(
        db, dataset_version_id=1, settings=_settings(tmp_path), actor_user_id=1, actor_login="a",
        notes="test run",
    )
    assert job.status == "pending"
    assert job.base_model == "qwen2.5-coder:7b"
    assert job.training_example_count == 5
    db.commit.assert_called_once()


def test_run_job_raises_when_disabled(tmp_path) -> None:
    db = MagicMock()
    with pytest.raises(FineTuneDisabled):
        run_job(db, 1, settings=_settings(tmp_path, finetune_enabled=False))


def test_run_job_raises_when_job_missing(tmp_path) -> None:
    db = MagicMock()
    db.get.return_value = None
    with pytest.raises(FineTuneJobNotFound):
        run_job(db, 1, settings=_settings(tmp_path))


def test_run_job_raises_when_trainer_not_configured(tmp_path) -> None:
    db = MagicMock()
    job = FineTuneJob(id=1, dataset_version_id=1, base_model="m", method="lora", status="pending")
    db.get.return_value = job
    with pytest.raises(TrainerNotConfigured):
        run_job(db, 1, settings=_settings(tmp_path, finetune_trainer_command=""))
    assert job.status == "failed"
    assert "finetune_trainer_command" in job.error_message


def _job(tmp_path, **overrides) -> FineTuneJob:
    defaults = dict(
        id=7, dataset_version_id=1, base_model="qwen2.5-coder:7b", method="lora",
        status="pending",
    )
    defaults.update(overrides)
    return FineTuneJob(**defaults)


def _db_with_job(job) -> MagicMock:
    db = MagicMock()
    db.get.return_value = job
    db.query.return_value.filter_by.return_value.order_by.return_value.all.return_value = []
    return db


def test_run_job_marks_failed_on_trainer_timeout(tmp_path) -> None:
    job = _job(tmp_path)
    db = _db_with_job(job)
    with patch(
        "app.finetune.training.subprocess.run",
        side_effect=subprocess.TimeoutExpired(cmd="trainer", timeout=60),
    ):
        result = run_job(db, job.id, settings=_settings(tmp_path))
    assert result.status == "failed"
    assert "timed out" in result.error_message


def test_run_job_marks_failed_on_trainer_command_not_found(tmp_path) -> None:
    job = _job(tmp_path)
    db = _db_with_job(job)
    with patch("app.finetune.training.subprocess.run", side_effect=FileNotFoundError("no")):
        result = run_job(db, job.id, settings=_settings(tmp_path))
    assert result.status == "failed"
    assert "not found" in result.error_message


def test_run_job_marks_failed_on_nonzero_exit(tmp_path) -> None:
    job = _job(tmp_path)
    db = _db_with_job(job)
    trainer_result = subprocess.CompletedProcess(args=[], returncode=1, stdout="", stderr="boom")
    with patch("app.finetune.training.subprocess.run", return_value=trainer_result):
        result = run_job(db, job.id, settings=_settings(tmp_path))
    assert result.status == "failed"
    assert "exited 1" in result.error_message


def test_run_job_completes_without_ollama_registration(tmp_path) -> None:
    job = _job(tmp_path)
    db = _db_with_job(job)
    trainer_result = subprocess.CompletedProcess(args=[], returncode=0, stdout="ok", stderr="")
    with patch("app.finetune.training.subprocess.run", return_value=trainer_result):
        result = run_job(
            db, job.id, settings=_settings(tmp_path, finetune_ollama_create_enabled=False)
        )
    assert result.status == "completed"
    assert result.adapter_path is not None
    assert result.output_model is None


def test_run_job_completes_and_registers_ollama_model(tmp_path) -> None:
    job = _job(tmp_path)
    db = _db_with_job(job)
    trainer_result = subprocess.CompletedProcess(args=[], returncode=0, stdout="ok", stderr="")
    ollama_result = subprocess.CompletedProcess(args=[], returncode=0, stdout="created", stderr="")
    with patch(
        "app.finetune.training.subprocess.run", side_effect=[trainer_result, ollama_result]
    ):
        result = run_job(
            db, job.id, settings=_settings(tmp_path, finetune_ollama_create_enabled=True)
        )
    assert result.status == "completed"
    assert result.output_model == f"reviewrush-finetune-{job.id}"


def test_run_job_fails_when_ollama_registration_fails(tmp_path) -> None:
    job = _job(tmp_path)
    db = _db_with_job(job)
    trainer_result = subprocess.CompletedProcess(args=[], returncode=0, stdout="ok", stderr="")
    ollama_result = subprocess.CompletedProcess(args=[], returncode=1, stdout="", stderr="nope")
    with patch(
        "app.finetune.training.subprocess.run", side_effect=[trainer_result, ollama_result]
    ):
        result = run_job(
            db, job.id, settings=_settings(tmp_path, finetune_ollama_create_enabled=True)
        )
    assert result.status == "failed"
    assert "model registration failed" in result.error_message
