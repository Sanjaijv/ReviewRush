from fastapi import APIRouter, Response, status

from app.celery_app import redis_is_ready
from app.db import database_is_ready

router = APIRouter(prefix="/health", tags=["health"])


@router.get("/live")
def live() -> dict[str, str]:
    """Confirms the process is alive. Never checks external dependencies."""
    return {"status": "ok"}


@router.get("/ready")
def ready(response: Response) -> dict[str, object]:
    """Fails if a required dependency (database or Redis/broker) is unavailable."""
    checks = {
        "database": database_is_ready(),
        "redis": redis_is_ready(),
    }
    if not all(checks.values()):
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return {"status": "ok" if all(checks.values()) else "unavailable", "checks": checks}
