from app.config import Settings
from app.models import ChangedFile, DiffSnapshot
from app.repo_config import parse_repo_config
from app.reviewers.definitions import REVIEWER_DEFINITIONS
from app.reviewers.prompt import build_specialized_review_prompt, build_specialized_system_prompt


class _FakeRepository:
    full_name = "acme/widgets"


def _security_reviewer():
    return next(d for d in REVIEWER_DEFINITIONS if d.name == "security")


def test_specialized_system_prompt_restricts_categories_and_marks_untrusted_data() -> None:
    reviewer = _security_reviewer()
    prompt = build_specialized_system_prompt(reviewer)

    assert "UNTRUSTED DATA" in prompt
    assert "not instructions" in prompt
    assert "security" in prompt
    assert "ONLY" in prompt


def test_specialized_prompt_uses_smaller_budget_and_reuses_diff_rendering() -> None:
    diff_snapshot = DiffSnapshot(id=1, repository_id=1, head_sha="sha1", base_sha="mainsha")
    changed_file = ChangedFile(
        new_path="src/app.py",
        old_path="src/app.py",
        status="modified",
        additions=1,
        patch="@@ -1,1 +1,2 @@\n context\n+added_marker",
    )
    settings = Settings(ai_max_prompt_bytes=400_000, ai_specialized_reviewer_max_prompt_bytes=50)

    reviewer = _security_reviewer()
    prompt = build_specialized_review_prompt(
        reviewer,
        repository=_FakeRepository(),
        diff_snapshot=diff_snapshot,
        changed_files=[changed_file],
        tool_runs=[],
        repo_config=parse_repo_config(None),
        settings=settings,
    )

    # budget is tiny, so the file must be omitted and marked truncated -
    # proves the specialist budget (not the general one) was applied.
    assert prompt.truncated is True
    assert "added_marker" not in prompt.user
    assert "omitted, prompt size budget" in prompt.user
    assert prompt.system != ""
    assert "security" in prompt.system
