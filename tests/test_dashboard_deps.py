from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException

from app.dashboard.deps import DashboardUser, get_authorized_repository


class _FakeInstallation:
    def __init__(self, github_installation_id: int) -> None:
        self.github_installation_id = github_installation_id


class _FakeRepository:
    def __init__(self, installation: _FakeInstallation) -> None:
        self.installation = installation


def _user(installation_ids: frozenset[int]) -> DashboardUser:
    return DashboardUser(
        github_user_id=1, login="octocat", avatar_url="", installation_ids=installation_ids
    )


def test_authorized_repository_is_returned() -> None:
    repo = _FakeRepository(_FakeInstallation(100))
    db = MagicMock()
    db.get.return_value = repo

    result = get_authorized_repository(1, user=_user(frozenset({100})), db=db)

    assert result is repo


def test_unauthorized_installation_is_404_not_403() -> None:
    repo = _FakeRepository(_FakeInstallation(999))
    db = MagicMock()
    db.get.return_value = repo

    with pytest.raises(HTTPException) as exc_info:
        get_authorized_repository(1, user=_user(frozenset({100})), db=db)

    assert exc_info.value.status_code == 404


def test_nonexistent_repository_is_404() -> None:
    db = MagicMock()
    db.get.return_value = None

    with pytest.raises(HTTPException) as exc_info:
        get_authorized_repository(1, user=_user(frozenset({100})), db=db)

    assert exc_info.value.status_code == 404
