from typing import Any

from app.models import AuditEvent


def record_audit_event(
    db: Any,
    *,
    action: str,
    target_type: str,
    target_id: str | None = None,
    repository_id: int | None = None,
    actor_type: str = "system",
    actor_user_id: int | None = None,
    actor_login: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> AuditEvent:
    """Append one immutable audit event and flush it in the caller's
    transaction. Never call this instead of committing the caller's own
    change - always alongside it, in the same db session, so the audit
    record and the change it describes commit atomically together.

    `metadata` must already be redacted by the caller: this function does
    not scrub secrets, tokens, or raw repository content on its own.
    """
    event = AuditEvent(
        repository_id=repository_id,
        actor_type=actor_type,
        actor_user_id=actor_user_id,
        actor_login=actor_login,
        action=action,
        target_type=target_type,
        target_id=target_id,
        event_metadata=metadata or {},
    )
    db.add(event)
    db.flush()
    return event
