from datetime import UTC, datetime
from unittest.mock import MagicMock

from app.dashboard.runs import get_run_detail, list_review_runs, summarize_run
from app.models import (
    AIFinding,
    AIReview,
    ChangedFile,
    DiffSnapshot,
    MergeAttempt,
    PolicyDecision,
    ToolRun,
)


def _snapshot() -> DiffSnapshot:
    snapshot = DiffSnapshot(
        id=5,
        repository_id=1,
        head_sha="abc123",
        base_sha="def456",
        file_count=1,
        total_changed_lines=10,
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
    )
    snapshot.changed_files = [
        ChangedFile(new_path="src/app.py", old_path="src/app.py", status="modified",
                    additions=5, deletions=2)
    ]
    return snapshot


def test_list_review_runs_paginates() -> None:
    db = MagicMock()
    ordered = db.query.return_value.filter_by.return_value.order_by.return_value
    ordered.offset.return_value.limit.return_value.all.return_value = [_snapshot()]

    result = list_review_runs(db, repository_id=1, limit=10, offset=0)

    assert len(result) == 1
    ordered.offset.assert_called_with(0)


def test_summarize_run_shape() -> None:
    summary = summarize_run(_snapshot())
    assert summary["head_sha"] == "abc123"
    assert summary["file_count"] == 1


def test_run_detail_returns_none_when_not_found() -> None:
    db = MagicMock()
    db.query.return_value.filter_by.return_value.one_or_none.return_value = None

    assert get_run_detail(db, repository_id=1, diff_snapshot_id=999) is None


def test_run_detail_assembles_full_evidence() -> None:
    snapshot = _snapshot()
    tool_run = ToolRun(
        id=1, repository_id=1, diff_snapshot_id=5, check_name="tests", category="test",
        conclusion="passed", required=True,
    )
    ai_review = AIReview(
        id=1, repository_id=1, diff_snapshot_id=5, status="completed", decision="approve",
        risk="low", confidence=0.95, provider="ollama", model="qwen2.5-coder:7b",
    )
    ai_review.findings = [
        AIFinding(
            id=1, ai_review_id=1, repository_id=1, file="src/app.py", start_line=1, end_line=2,
            severity="medium", category="quality", title="t", evidence="e",
        )
    ]
    policy_decision = PolicyDecision(
        id=1, repository_id=1, diff_snapshot_id=5, policy_version="1", decision="APPROVE",
        risk="LOW", reasons=["ok"],
    )
    merge_attempt = MergeAttempt(
        id=1, repository_id=1, diff_snapshot_id=5, outcome="merged", reasons=[],
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
    )

    db = MagicMock()

    def query_side_effect(model):
        q = MagicMock()
        if model is DiffSnapshot:
            q.filter_by.return_value.one_or_none.return_value = snapshot
        elif model is ToolRun:
            q.filter_by.return_value.all.return_value = [tool_run]
        elif model is AIReview:
            q.filter_by.return_value.one_or_none.return_value = ai_review
        elif model is PolicyDecision:
            q.filter_by.return_value.one_or_none.return_value = policy_decision
        elif model is MergeAttempt:
            q.filter_by.return_value.order_by.return_value.all.return_value = [merge_attempt]
        return q

    db.query.side_effect = query_side_effect

    detail = get_run_detail(db, repository_id=1, diff_snapshot_id=5)

    assert detail is not None
    assert detail["run"]["head_sha"] == "abc123"
    assert detail["tool_runs"][0]["check_name"] == "tests"
    assert detail["ai_review"]["findings"][0]["severity"] == "medium"
    assert detail["policy_decision"]["decision"] == "APPROVE"
    assert detail["merge_attempts"][0]["outcome"] == "merged"
