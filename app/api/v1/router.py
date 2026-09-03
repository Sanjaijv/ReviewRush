from fastapi import APIRouter

from app.api.v1.dashboard import router as dashboard_router
from app.api.v1.evaluation import router as evaluation_router
from app.api.v1.finetune import router as finetune_router
from app.api.v1.github_webhook import router as github_router
from app.api.v1.health import router as health_router

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(health_router)
api_router.include_router(github_router)
api_router.include_router(dashboard_router)
api_router.include_router(evaluation_router)
api_router.include_router(finetune_router)
