from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.api.v1.metrics import router as metrics_router
from app.api.v1.router import api_router
from app.config import get_settings
from app.logging import CorrelationIdMiddleware, configure_logging
from app.observability.tracing import instrument_fastapi_app, setup_tracing

settings = get_settings()
configure_logging(settings.log_level)
setup_tracing(settings)

app = FastAPI(title="ReviewRush", version="0.1.0")
app.add_middleware(CorrelationIdMiddleware)
app.include_router(api_router)
# Mounted at root, not under /api/v1: both are operator/infra-facing
# endpoints (a Prometheus scraper, a liveness/readiness probe), following
# the convention those tools expect rather than the versioned product API.
app.include_router(metrics_router)
instrument_fastapi_app(app, settings)

# Minimal, dependency-free dashboard UI (Phase 12) - a thin client over the
# JSON API in app/api/v1/dashboard.py. No build step: served as-is.
_dashboard_static_dir = Path(__file__).parent / "static" / "dashboard"
app.mount(
    "/dashboard", StaticFiles(directory=_dashboard_static_dir, html=True), name="dashboard"
)
