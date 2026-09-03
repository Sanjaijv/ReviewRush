"""Converts a Phase 15 `EvalDatasetVersion` into instruction/response
training records for Phase 16 LoRA/QLoRA fine-tuning.

Deliberately reads only already-sanitized `EvalDatasetItem` rows - by the
time a dataset version exists, `app.evaluation.dataset.build_dataset_version`
has already filtered to consented, "useful"-confirmed feedback and run
`app.evaluation.redaction` over `diff_text`/`repository_ref`. This module
adds no new path to real repository content or secrets; it only reshapes
data that has already passed that gate.

Each `EvalDatasetItem.expected_findings` covers only the single confirmed
finding it was built from (see `app.evaluation.dataset`'s docstring), not a
full `AIReviewIssue` - so the training target here is intentionally a
reduced signal (category/severity/line), not a claim that these records
alone teach summary/evidence/recommendation text.
"""

import json
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy.orm import Session

from app.models import EvalDatasetItem

_INSTRUCTION = (
    "You are a code review assistant. Given a unified diff, identify any "
    "correctness, security, reliability, performance, or maintainability "
    "issues introduced by the change. Respond with a JSON object listing "
    "the issues found, each with a category, severity, and the changed "
    "line number it applies to. If the diff introduces no issues, respond "
    "with an empty issues list."
)


@dataclass(frozen=True)
class TrainingRecord:
    instruction: str
    input: str
    output: str  # JSON-encoded {"issues": [...]}

    def as_dict(self) -> dict[str, str]:
        return {"instruction": self.instruction, "input": self.input, "output": self.output}


def build_training_records(db: Session, dataset_version_id: int) -> list[TrainingRecord]:
    items = (
        db.query(EvalDatasetItem)
        .filter_by(dataset_version_id=dataset_version_id)
        .order_by(EvalDatasetItem.id)
        .all()
    )
    records = []
    for item in items:
        output = json.dumps({"issues": item.expected_findings}, sort_keys=True)
        records.append(
            TrainingRecord(instruction=_INSTRUCTION, input=item.diff_text, output=output)
        )
    return records


def write_jsonl(records: list[TrainingRecord], path: Path) -> int:
    """Writes `records` as one JSON object per line and returns the count
    written. The caller is responsible for choosing a path under
    `settings.finetune_output_dir` (or elsewhere) - this function performs
    no path validation of its own.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for record in records:
            fh.write(json.dumps(record.as_dict(), sort_keys=True))
            fh.write("\n")
    return len(records)
