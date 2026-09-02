from fastapi import FastAPI

from app.api.v1.router import api_router
from app.config import get_settings
from app.logging import CorrelationIdMiddleware, configure_logging

settings = get_settings()
configure_logging(settings.log_level)

app = FastAPI(title="ReviewRush", version="0.1.0")
app.add_middleware(CorrelationIdMiddleware)
app.include_router(api_router)
