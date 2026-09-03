from unittest.mock import MagicMock

import pytest

from app.dashboard.config_service import InvalidRepoConfig, save_config_version
from app.dashboard.deps import DashboardUser
from app.models import Repository, RepositoryConfigVersion


def _db(*, latest_version: RepositoryConfigVersion | None = None) -> MagicMock:
    db = MagicMock()

    def query_side_effect(model):
        q = MagicMock()
        if model is RepositoryConfigVersion:
            q.filter_by.return_value.order_by.return_value.first.return_value = latest_version
        return q

    db.query.side_effect = query_side_effect
    return db


def _user() -> DashboardUser:
    return DashboardUser(
        github_user_id=42, login="octocat", avatar_url="", installation_ids=frozenset({1})
    )


def test_first_save_creates_version_one() -> None:
    db = _db(latest_version=None)
    repository = Repository(id=1, installation_id=1, github_repo_id=1, owner="acme", name="w")

    row = save_config_version(db, repository, {"version": 1}, _user())

    assert row.version == 1
    assert row.actor_login == "octocat"
    assert row.actor_user_id == 42
    db.commit.assert_called_once()


def test_second_save_increments_version() -> None:
    existing = RepositoryConfigVersion(id=1, repository_id=1, version=3, config={"version": 1})
    db = _db(latest_version=existing)
    repository = Repository(id=1, installation_id=1, github_repo_id=1, owner="acme", name="w")

    row = save_config_version(db, repository, {"version": 1}, _user())

    assert row.version == 4


def test_invalid_config_is_rejected_before_writing() -> None:
    db = _db()
    repository = Repository(id=1, installation_id=1, github_repo_id=1, owner="acme", name="w")

    with pytest.raises(InvalidRepoConfig):
        save_config_version(db, repository, {"version": 1, "unknown_field": True}, _user())

    db.add.assert_not_called()
    db.commit.assert_not_called()


def test_org_protected_paths_are_not_bypassed_by_a_valid_but_empty_override() -> None:
    # An empty protected_paths list is schema-valid on its own - the org
    # floor from Settings.policy_org_protected_paths is unioned back in at
    # evaluation time (app.policy.service), never weakened here.
    db = _db()
    repository = Repository(id=1, installation_id=1, github_repo_id=1, owner="acme", name="w")

    row = save_config_version(db, repository, {"version": 1, "protected_paths": []}, _user())

    assert row.config["protected_paths"] == []
