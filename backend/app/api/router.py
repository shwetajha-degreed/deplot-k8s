from fastapi import APIRouter

from app.api.v1 import aiops, analyze, dashboard, deploy, health, observability

api_router = APIRouter()
api_router.include_router(health.router, tags=["health"])
api_router.include_router(dashboard.router, tags=["dashboard"])
api_router.include_router(analyze.router, tags=["analyze"])
api_router.include_router(deploy.router, tags=["deploy"])
api_router.include_router(observability.router, tags=["observability"])
api_router.include_router(aiops.router, tags=["aiops"])
