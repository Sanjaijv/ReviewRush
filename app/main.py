from fastapi import FastAPI

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

# The dashboard UI (Phase 12) is now the Next.js app in frontend/, served as
# its own process/origin and proxying /api/* back here (see
# frontend/next.config.ts) - this service no longer serves any dashboard
# HTML itself. See docs/frontend.md.
