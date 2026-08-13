from uuid import UUID

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.agents.orchestrator import AgentContext
from app.api.deps import get_orchestrator
from app.bootstrap import get_service
from app.models.analysis import (
    AnalysisSession,
    AnalyzeRequest,
    AnalyzeResponse,
    ArchitectureGraph,
    SessionStatus,
    ValidationReport,
)
from app.models.deployment import DeploymentPlan, K8sConfig
from app.services.k8s import repo_slug_from_url
from app.services.store import session_store

router = APIRouter()


class SessionIdBody(BaseModel):
    session_id: UUID


@router.post("/analyze", response_model=AnalyzeResponse)
async def analyze_repo(body: AnalyzeRequest):
    session = AnalysisSession(
        repo_url=str(body.repo_url) if body.repo_url else None,
        status=SessionStatus.ANALYZING,
    )
    session_store.save(session)

    github = get_service("github")
    orchestrator = get_orchestrator()

    files: dict[str, str] = {}
    if body.demo_mode:
        files = _demo_files()
    elif body.repo_url:
        try:
            files = await github.fetch_repo_tree(str(body.repo_url))
        except Exception as exc:
            raise HTTPException(
                status_code=422,
                detail={
                    "message": f"Could not fetch repository: {exc}",
                    "code": "REPO_FETCH_FAILED",
                },
            ) from exc
    else:
        raise HTTPException(
            status_code=400,
            detail="repo_url is required when demo_mode is false",
        )

    stack = await orchestrator.run("repository_analyzer", AgentContext(payload={"files": files}))
    if session.repo_url:
        stack.repo_slug = repo_slug_from_url(session.repo_url)
    elif body.demo_mode:
        stack.repo_slug = "demo"
    session.stack = stack
    session.status = SessionStatus.READY
    session_store.save(session)

    return AnalyzeResponse(session_id=session.id, status=session.status, stack=stack)


@router.post("/architecture", response_model=ArchitectureGraph)
async def generate_architecture(body: SessionIdBody):
    session = session_store.get(body.session_id)
    if not session or not session.stack:
        raise HTTPException(status_code=404, detail="Session not found or not analyzed")

    orchestrator = get_orchestrator()
    graph = await orchestrator.run(
        "infrastructure_planner",
        AgentContext(payload={"stack": session.stack}),
    )
    session.architecture = graph
    session_store.save(session)
    return graph


@router.post("/generate-yaml", response_model=K8sConfig)
async def generate_yaml(body: SessionIdBody):
    session = session_store.get(body.session_id)
    if not session or not session.stack:
        raise HTTPException(status_code=404, detail="Session not found or not analyzed")

    orchestrator = get_orchestrator()
    config = await orchestrator.run(
        "yaml_generator",
        AgentContext(payload={"stack": session.stack, "repo_url": session.repo_url}),
    )
    return config


class ValidateRequest(BaseModel):
    session_id: UUID


@router.post("/validate", response_model=ValidationReport)
async def validate_config(body: ValidateRequest):
    session = session_store.get(body.session_id)
    if not session or not session.stack:
        raise HTTPException(status_code=404, detail="Session not found")

    yaml_svc = get_service("yaml_generator")
    config = yaml_svc.generate(session.stack, session.repo_url)

    orchestrator = get_orchestrator()
    return await orchestrator.run(
        "deployment_validator",
        AgentContext(payload={"stack": session.stack, "config": config}),
    )


@router.get("/sessions/{session_id}", response_model=AnalysisSession)
async def get_session(session_id: UUID):
    session = session_store.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    return session


@router.get("/sessions/{session_id}/plan", response_model=DeploymentPlan)
async def get_plan(session_id: UUID):
    session = session_store.get(session_id)
    if not session or not session.stack:
        raise HTTPException(status_code=404, detail="Session not found")

    if not session.architecture:
        orchestrator = get_orchestrator()
        session.architecture = await orchestrator.run(
            "infrastructure_planner",
            AgentContext(payload={"stack": session.stack}),
        )
        session_store.save(session)

    planner = get_service("planner")
    return planner.build_plan(session.stack, session.architecture)


def _demo_files() -> dict[str, str]:
    return {
        "package.json": '{"dependencies":{"next":"15.0.0","@prisma/client":"5.0.0","typesense":"2.0.0","ioredis":"5.0.0"},"engines":{"node":">=22"}}',
        "requirements.txt": "fastapi\nuvicorn\n",
        "prisma/schema.prisma": 'datasource db { provider = "postgresql" url = env("DATABASE_URL") }',
    }
