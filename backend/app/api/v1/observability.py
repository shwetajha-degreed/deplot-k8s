from uuid import UUID

from fastapi import APIRouter, HTTPException

from app.bootstrap import get_service
from app.models.observability import ObservabilitySnapshot

router = APIRouter()


@router.get("/deployment/{deployment_id}/observability", response_model=ObservabilitySnapshot)
async def get_observability(deployment_id: UUID):
    obs = get_service("observability")
    return await obs.get_snapshot(deployment_id)


@router.get("/deployment/{deployment_id}/metrics")
async def get_metrics(deployment_id: UUID):
    snap = await get_observability(deployment_id)
    return {"deployment_id": str(deployment_id), "metrics": snap.metrics}


@router.get("/deployment/{deployment_id}/logs")
async def get_logs(deployment_id: UUID, tail: int = 500):
    from app.services.store import deployment_store

    deployment = deployment_store.get(deployment_id)
    zerops = get_service("zerops")
    hostname = str(deployment_id)
    project_id = None
    if deployment and deployment.service_hostnames:
        hostname = deployment.service_hostnames.get("api") or hostname
        project_id = deployment.zerops_project_id
    lines = await zerops.fetch_logs(hostname, tail=tail, project_id=project_id)
    return {"deployment_id": str(deployment_id), "lines": lines}


@router.get("/deployment/{deployment_id}/timeline")
async def get_timeline(deployment_id: UUID):
    obs = get_service("observability")
    snap = await obs.get_snapshot(deployment_id)
    return {"deployment_id": str(deployment_id), "events": snap.timeline}


@router.post("/logs/summarize")
async def summarize_logs(body: dict):
    deployment_id = body.get("deployment_id")
    if not deployment_id:
        raise HTTPException(status_code=422, detail="deployment_id required")
    from uuid import UUID

    obs = get_service("observability")
    snap = await obs.get_snapshot(UUID(str(deployment_id)))
    return {
        "summary": snap.log_summary or "No log data available.",
        "deployment_id": str(deployment_id),
    }
