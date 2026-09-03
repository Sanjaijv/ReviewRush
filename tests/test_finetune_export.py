import json
from unittest.mock import MagicMock

from app.finetune.export import build_training_records, write_jsonl
from app.models import EvalDatasetItem


def _item(**overrides) -> EvalDatasetItem:
    defaults = dict(
        id=1,
        dataset_version_id=1,
        category="security",
        repository_ref="repo-abc123",
        diff_text="@@ -1 +1 @@\n-old\n+new",
        expected_findings=[{"category": "security", "severity": "high", "line": 2}],
    )
    defaults.update(overrides)
    return EvalDatasetItem(**defaults)


def test_build_training_records_maps_each_item() -> None:
    db = MagicMock()
    items = [_item(id=1), _item(id=2, category="correctness", expected_findings=[])]
    db.query.return_value.filter_by.return_value.order_by.return_value.all.return_value = items

    records = build_training_records(db, dataset_version_id=1)

    assert len(records) == 2
    assert records[0].input == items[0].diff_text
    assert json.loads(records[0].output) == {"issues": items[0].expected_findings}
    assert json.loads(records[1].output) == {"issues": []}
    assert all(r.instruction for r in records)


def test_build_training_records_empty_dataset() -> None:
    db = MagicMock()
    db.query.return_value.filter_by.return_value.order_by.return_value.all.return_value = []

    assert build_training_records(db, dataset_version_id=1) == []


def test_write_jsonl_writes_one_line_per_record(tmp_path) -> None:
    db = MagicMock()
    items = [_item(id=1), _item(id=2)]
    db.query.return_value.filter_by.return_value.order_by.return_value.all.return_value = items
    records = build_training_records(db, dataset_version_id=1)

    out_path = tmp_path / "nested" / "train.jsonl"
    count = write_jsonl(records, out_path)

    assert count == 2
    lines = out_path.read_text().strip().splitlines()
    assert len(lines) == 2
    for line, record in zip(lines, records, strict=True):
        assert json.loads(line) == record.as_dict()
