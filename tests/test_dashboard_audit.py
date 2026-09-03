from unittest.mock import MagicMock

from app.dashboard.audit import record_audit_event
from app.models import AuditEvent


def test_record_audit_event_defaults_to_system_actor() -> None:
    db = MagicMock()

    event = record_audit_event(
        db, action="policy.decided", target_type="policy_decision", target_id="1",
        repository_id=1,
    )

    assert isinstance(event, AuditEvent)
    assert event.actor_type == "system"
    assert event.actor_user_id is None
    db.add.assert_called_once_with(event)
    db.flush.assert_called_once()


def test_record_audit_event_captures_user_actor() -> None:
    db = MagicMock()

    event = record_audit_event(
        db,
        action="config.updated",
        target_type="repository_config_version",
        target_id="3",
        repository_id=1,
        actor_type="user",
        actor_user_id=42,
        actor_login="octocat",
        metadata={"version": 3},
    )

    assert event.actor_type == "user"
    assert event.actor_user_id == 42
    assert event.actor_login == "octocat"
    assert event.event_metadata == {"version": 3}


def test_metadata_defaults_to_empty_dict() -> None:
    db = MagicMock()

    event = record_audit_event(db, action="x", target_type="y")

    assert event.event_metadata == {}
