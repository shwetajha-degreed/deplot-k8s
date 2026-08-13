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
        "kubernetes": {
            "cluster": settings.aks_cluster_name,
            "deplot_namespace": settings.deplot_namespace,
            "workload_identity_configured": bool(settings.azure_workload_identity_client_id),
        },
    }


@router.get("/metrics")
async def metrics():
    return {"deplot": {"status": "ok"}, "targets": []}
