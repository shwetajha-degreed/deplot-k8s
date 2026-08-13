from uuid import UUID

from fastapi import APIRouter, HTTPException

from app.agents.orchestrator import AgentContext
from app.api.deps import get_orchestrator
from app.bootstrap import get_service
from app.models.aiops import AIOpsReport, Incident
from app.services.store import deployment_store, session_store

router = APIRouter()


@router.get("/deployment/{deployment_id}/incidents", response_model=list[Incident])
async def list_incidents(deployment_id: UUID):
    aiops = get_service("aiops")
    return await aiops.list_incidents(deployment_id)


@router.get("/incidents/{incident_id}", response_model=Incident)
async def get_incident(incident_id: UUID):
    aiops = get_service("aiops")
    incident = await aiops.get_incident(incident_id)
    if not incident:
        raise HTTPException(status_code=404, detail="Incident not found")
    return incident


@router.post("/incidents/{incident_id}/diagnose", response_model=Incident)
async def diagnose_incident(incident_id: UUID):
    aiops = get_service("aiops")
    incident = await aiops.get_incident(incident_id)
    if not incident:
        raise HTTPException(status_code=404, detail="Incident not found")

    deployment = deployment_store.get(incident.deployment_id)
    zerops = get_service("zerops")
    logs: list[str] = []
    yaml_excerpt = ""
    stack_summary = ""
    if deployment:
        slug = deployment.repo_slug or "app"
        logs = await zerops.fetch_logs(
            f"{slug}-api", tail=100, project_id=deployment.zerops_project_id
        )
        if deployment.config:
            yaml_excerpt = deployment.config.import_yaml[:3000]
        session = session_store.get(deployment.session_id)
        if session and session.stack:
            stack_summary = f"framework={session.stack.framework}, search={session.stack.search}"

    orchestrator = get_orchestrator()
    report: AIOpsReport = await orchestrator.run(
        "aiops_analyst",
        AgentContext(
            payload={
                "logs": logs,
                "stack_summary": stack_summary,
                "yaml_excerpt": yaml_excerpt,
            }
        ),
    )
    return await aiops.diagnose(incident, report)


@router.post("/incidents/{incident_id}/remediate", response_model=Incident)
async def remediate_incident(incident_id: UUID):
    aiops = get_service("aiops")
    incident = await aiops.get_incident(incident_id)
    if not incident:
        raise HTTPException(status_code=404, detail="Incident not found")

    result = await aiops.execute_remediation(incident_id)
    if not result:
        raise HTTPException(status_code=404, detail="Incident not found")
    return result


@router.post("/logs/analyze", response_model=AIOpsReport)
async def analyze_logs():
    orchestrator = get_orchestrator()
    return await orchestrator.run("aiops_analyst", AgentContext(payload={}))
