from fastapi import APIRouter

from app.api.v1.github_webhook import router as github_router
from app.api.v1.health import router as health_router

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(health_router)
api_router.include_router(github_router)
