from fastapi import APIRouter

from app.config import get_settings

router = APIRouter()


@router.get("/health")
async def health_check():
    settings = get_settings()
    return {
        "status": "ok",
        "app": settings.app_name,
        "version": settings.app_version,
        "zerops": {
            "platform_project_configured": bool(settings.zerops_project_id),
            "deploy_project_configured": bool(settings.zerops_target_project_id),
            "deploy_project_isolated": settings.deploy_project_isolated,
        },
    }


@router.get("/metrics")
async def metrics():
    return {"deplot": {"status": "ok"}, "targets": []}
