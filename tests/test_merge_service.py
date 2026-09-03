from unittest.mock import MagicMock, patch

import httpx

from app.config import Settings
from app.merge.service import attempt_auto_merge_for_snapshot
from app.models import (
    DiffSnapshot,
    MergeAttempt,
    PolicyDecision,
    PullRequest,
    RepositoryConfigVersion,
)


def _added(db: MagicMock, cls: type) -> object:
    """The last db.add()-ed instance of `cls` - merge attempts now also
    write an AuditEvent alongside the MergeAttempt, so a plain
    `db.add.call_args` no longer reliably picks out the MergeAttempt."""
    matches = [c.args[0] for c in db.add.call_args_list if isinstance(c.args[0], cls)]
    assert matches, f"no {cls.__name__} was added"
    return matches[-1]


class _FakeInstallation:
    github_installation_id = 1


class _FakeRepository:
    def __init__(self) -> None:
        self.id = 1
        self.owner = "acme"
        self.name = "widgets"
        self.full_name = "acme/widgets"
        self.installation = _FakeInstallation()


def _diff_snapshot() -> DiffSnapshot:
    return DiffSnapshot(id=1, repository_id=1, head_sha="sha1", base_sha="mainsha", commits=[])


def _pull_request() -> PullRequest:
    return PullRequest(
        id=1,
        repository_id=1,
        github_pr_number=7,
        head_branch="foundations",
        base_branch="main",
        head_sha="sha1",
        state="open",
    )


def _approved_decision(**evidence_overrides) -> PolicyDecision:
    evidence = {"protected_paths_matched": []}
    evidence.update(evidence_overrides)
    return PolicyDecision(
        id=1,
        repository_id=1,
        diff_snapshot_id=1,
        decision="APPROVE",
        risk="LOW",
        reasons=["ok"],
        evidence=evidence,
    )


def _db(*, decision=None, pull_request=None) -> MagicMock:
    db = MagicMock()

    def query_side_effect(model):
        q = MagicMock()
        if model is PolicyDecision:
            q.filter_by.return_value.one_or_none.return_value = decision
        elif model is PullRequest:
            q.filter_by.return_value.one_or_none.return_value = pull_request
        elif model is RepositoryConfigVersion:
            # No dashboard config override in these tests - falls back to
            # fetching .reviewrush.yml from GitHub, same as before Phase 12.
            q.filter_by.return_value.order_by.return_value.first.return_value = None
        return q

    db.query.side_effect = query_side_effect
    return db


def _run(
    db,
    *,
    config_yaml="merge:\n  enabled: true\n  method: squash\n",
    settings=None,
    live_pr=None,
    check_runs=None,
    reviews=None,
    merge_side_effect=None,
):
    settings = settings or Settings(merge_auto_merge_enabled=True)
    live_pr = live_pr or {
        "head": {"sha": "sha1"},
        "base": {"ref": "main"},
        "state": "open",
        "merged": False,
        "draft": False,
        "mergeable": True,
        "mergeable_state": "clean",
    }
    default_check_runs = {
        "check_runs": [{"name": "ReviewRush", "status": "completed", "conclusion": "success"}]
    }
    check_runs = check_runs if check_runs is not None else default_check_runs
    reviews = reviews if reviews is not None else []

    with (
        patch("app.merge.service.get_settings", return_value=settings),
        patch("app.merge.service.get_installation_access_token", return_value="tok"),
        patch("app.merge.service.GitHubClient") as github_client_cls,
    ):
        instance = MagicMock()
        instance.get_file_contents.return_value = config_yaml
        instance.get_pull_request.return_value = live_pr
        instance.list_check_runs_for_ref.return_value = check_runs
        instance.list_reviews.return_value = reviews
        if merge_side_effect is not None:
            instance.merge_pull_request.side_effect = merge_side_effect
        else:
            instance.merge_pull_request.return_value = {"merged": True, "sha": "mergecommit"}
        instance.__enter__.return_value = instance
        github_client_cls.return_value = instance
        result = attempt_auto_merge_for_snapshot(db, _FakeRepository(), _diff_snapshot())
        return result, instance


def test_skips_when_no_policy_decision() -> None:
    db = _db(decision=None, pull_request=_pull_request())

    result, instance = _run(db)

    assert result.outcome == "skipped"
    persisted: MergeAttempt = _added(db, MergeAttempt)
    assert persisted.outcome == "skipped"
    instance.get_pull_request.assert_not_called()


def test_skips_when_no_pull_request() -> None:
    db = _db(decision=_approved_decision(), pull_request=None)

    result, instance = _run(db)

    assert result.outcome == "skipped"
    instance.get_pull_request.assert_not_called()


def test_eligible_change_is_merged() -> None:
    pr = _pull_request()
    db = _db(decision=_approved_decision(), pull_request=pr)

    result, instance = _run(db)

    assert result.outcome == "merged"
    instance.merge_pull_request.assert_called_once_with(
        "acme", "widgets", 7, sha="sha1", merge_method="squash"
    )
    assert pr.state == "merged"
    persisted: MergeAttempt = _added(db, MergeAttempt)
    assert persisted.github_response == {"merged": True, "sha": "mergecommit"}


def test_disabled_auto_merge_is_not_eligible() -> None:
    db = _db(decision=_approved_decision(), pull_request=_pull_request())

    result, instance = _run(db, settings=Settings(merge_auto_merge_enabled=False))

    assert result.outcome == "not_eligible"
    instance.merge_pull_request.assert_not_called()


def test_stale_head_sha_is_not_eligible() -> None:
    db = _db(decision=_approved_decision(), pull_request=_pull_request())
    live_pr = {
        "head": {"sha": "sha2"},
        "base": {"ref": "main"},
        "state": "open",
        "merged": False,
        "draft": False,
        "mergeable": True,
        "mergeable_state": "clean",
    }

    result, instance = _run(db, live_pr=live_pr)

    assert result.outcome == "not_eligible"
    instance.merge_pull_request.assert_not_called()


def test_already_merged_pr_is_recorded_as_already_merged() -> None:
    db = _db(decision=_approved_decision(), pull_request=_pull_request())
    live_pr = {
        "head": {"sha": "sha1"},
        "base": {"ref": "main"},
        "state": "closed",
        "merged": True,
        "draft": False,
        "mergeable": None,
        "mergeable_state": "unknown",
    }

    result, instance = _run(db, live_pr=live_pr)

    assert result.outcome == "already_merged"
    instance.merge_pull_request.assert_not_called()


def test_protected_path_evidence_is_not_eligible() -> None:
    matched = [{"path": "infra/x", "pattern": "infra/**"}]
    db = _db(
        decision=_approved_decision(protected_paths_matched=matched),
        pull_request=_pull_request(),
    )

    result, instance = _run(db)

    assert result.outcome == "not_eligible"
    instance.merge_pull_request.assert_not_called()


def test_github_merge_rejection_is_recorded_as_failed() -> None:
    db = _db(decision=_approved_decision(), pull_request=_pull_request())
    response = MagicMock()
    response.status_code = 405
    response.json.return_value = {"message": "not mergeable"}
    error = httpx.HTTPStatusError("boom", request=MagicMock(), response=response)

    result, instance = _run(db, merge_side_effect=error)

    assert result.outcome == "failed"
    persisted: MergeAttempt = _added(db, MergeAttempt)
    assert persisted.github_response == {"message": "not mergeable"}


def test_invalid_merge_method_falls_back_to_squash() -> None:
    db = _db(decision=_approved_decision(), pull_request=_pull_request())

    result, instance = _run(db, config_yaml="merge:\n  enabled: true\n  method: rebase-and-pray\n")

    assert result.outcome == "merged"
    instance.merge_pull_request.assert_called_once_with(
        "acme", "widgets", 7, sha="sha1", merge_method="squash"
    )
