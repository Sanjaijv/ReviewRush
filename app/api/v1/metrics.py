from fastapi import APIRouter, Depends, HTTPException, Response, status
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from app.config import Settings, get_settings
from app.observability.queue_depth import sample_queue_depth

router = APIRouter(tags=["metrics"])


@router.get("/metrics")
def metrics(settings: Settings = Depends(get_settings)) -> Response:
    """Prometheus scrape endpoint (Phase 13). No authentication of its own -
    an operator running this in production should restrict network access
    to it (reverse-proxy allowlist, internal-only ingress), the same as any
    other operator-facing endpoint with no per-user auth model.
    """
    if not settings.metrics_enabled:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    sample_queue_depth()
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)
