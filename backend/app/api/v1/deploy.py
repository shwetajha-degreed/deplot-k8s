from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from app.agents.orchestrator import AgentContext
from app.api.deps import get_orchestrator
from app.bootstrap import get_service
from app.config import get_settings
from app.models.deployment import (
    DeployRequest,
    DeployResponse,
    Deployment,
    DeploymentScore,
    DeploymentStage,
    DeploymentStatus,
    DeploymentStatusResponse,
    RetryDeployRequest,
)
from app.services.deploy_failure import (
    classify_import_failure,
    classify_pipeline_failure,
    retry_from_phase,
    stage_to_ui_index,
)
from app.services.deploy_stream import stream_deployment_sse
from app.services.timeline import record_ops_event
from app.services.zerops import hostnames_for_slug
from app.services.store import deployment_store, session_store
from app.services.zerops import repo_slug_from_url

router = APIRouter()


def _stack_summary(session) -> str:
    if not session.stack:
        return "unknown"
    s = session.stack
    parts = [
        f"framework={s.framework}",
        f"backend={s.backend_framework}",
        f"db={s.database}",
        f"cache={s.cache}",
        f"search={s.search}",
    ]
    return ", ".join(p for p in parts if p.split("=")[-1] not in ("None", ""))


def _status_response(deployment: Deployment) -> DeploymentStatusResponse:
    return DeploymentStatusResponse(
        deployment_id=deployment.id,
        status=deployment.status,
        stage=deployment.stage,
        live_url=deployment.live_url,
        service_urls=deployment.service_urls,
        service_hostnames=deployment.service_hostnames,
        routing_checklist=deployment.routing_checklist,
        pipeline_state=deployment.pipeline_state,
        message=deployment.zerops_message,
        demo_mode=deployment.demo_mode,
        failure_phase=deployment.failure_phase,
        failure_summary=deployment.failure_summary,
        retry_from=retry_from_phase(deployment.failure_phase) if deployment.failure_phase else None,
        deploy_ui_stage_index=stage_to_ui_index(
            deployment.stage, failure_phase=deployment.failure_phase
        ),
    )


def _clear_failure(deployment: Deployment) -> None:
    deployment.failure_phase = None
    deployment.failure_summary = None


async def _mark_import_failure(
    deployment: Deployment,
    *,
    result: dict,
    session,
    config,
    aiops,
    zerops_svc,
    target_project: str | None,
    slug: str,
) -> None:
    phase, summary = classify_import_failure(result)
    deployment.status = DeploymentStatus.FAILED
    deployment.stage = DeploymentStage.FAILED
    deployment.pipeline_state = "import_failed"
    deployment.failure_phase = phase
    deployment.failure_summary = summary
    deployment.zerops_message = (result.get("stderr") or "")[:2000] or result.get("error") or summary
    record_ops_event(
        deployment.id,
        source="deploy",
        event_type="import_failed",
        message=summary,
        service="platform",
    )
    logs = [
        result.get("stderr") or "",
        result.get("stdout") or "",
        result.get("error") or summary,
    ]
    logs = [line for line in logs if line]
    await aiops.create_incident_from_failure(
        deployment.id,
        title="Zerops service import failed",
        logs=logs,
        stack_summary=_stack_summary(session),
        yaml_excerpt=config.import_yaml[:3000],
    )


async def _apply_import_success(
    deployment: Deployment,
    *,
    result: dict,
    zerops_svc,
    target_project: str | None,
    slug: str,
) -> None:
    deployment.status = DeploymentStatus.IN_PROGRESS
    deployment.stage = DeploymentStage.PROVISIONING_DB
    deployment.pipeline_state = "imported"
    deployment.routing_checklist = result.get("routing_checklist") or []
    _clear_failure(deployment)
    record_ops_event(
        deployment.id,
        source="deploy",
        event_type="import_succeeded",
        message="Zerops service import completed — pipelines starting",
        service="platform",
    )
    urls = await zerops_svc.get_service_urls(
        {"web": f"{slug}-web", "api": f"{slug}-api"},
        target_project,
    )
    deployment.service_urls = urls
    deployment.live_url = urls.get("web") or urls.get("api")


async def _run_live_import(
    deployment: Deployment,
    *,
    session,
    config,
    zerops_svc,
    aiops,
    target_project: str | None,
    slug: str,
) -> None:
    result = await zerops_svc.deploy(
        config,
        demo_mode=False,
        project_id=target_project,
        repo_slug=slug,
    )
    deployment.zerops_message = (result.get("stdout") or "")[:2000] or result.get("error")
    deployment.routing_checklist = result.get("routing_checklist") or []

    if result.get("ok"):
        await _apply_import_success(
            deployment,
            result=result,
            zerops_svc=zerops_svc,
            target_project=target_project,
            slug=slug,
        )
    else:
        await _mark_import_failure(
            deployment,
            result=result,
            session=session,
            config=config,
            aiops=aiops,
            zerops_svc=zerops_svc,
            target_project=target_project,
            slug=slug,
        )


@router.post("/deploy", response_model=DeployResponse)
async def start_deploy(body: DeployRequest):
    session = session_store.get(body.session_id)
    if not session or not session.stack:
        raise HTTPException(status_code=404, detail="Session not found")

    yaml_svc = get_service("yaml_generator")
    zerops_svc = get_service("zerops")
    planner = get_service("planner")
    aiops = get_service("aiops")

    if session.repo_url:
        session.stack.repo_slug = repo_slug_from_url(session.repo_url)

    config = yaml_svc.generate(session.stack, session.repo_url)

    graph = session.architecture
    if not graph:
        orchestrator = get_orchestrator()
        graph = await orchestrator.run(
            "infrastructure_planner",
            AgentContext(payload={"stack": session.stack}),
        )

    plan = planner.build_plan(session.stack, graph)
    settings = get_settings()
    slug = session.stack.repo_slug or repo_slug_from_url(session.repo_url)
    target_project = settings.zerops_target_project_id

    deployment = Deployment(
        session_id=body.session_id,
        config=config,
        plan=plan,
        demo_mode=body.demo_mode,
        repo_slug=slug,
        zerops_project_id=target_project or None,
        service_hostnames=hostnames_for_slug(slug),
    )
    deployment_store.save(deployment)
    record_ops_event(
        deployment.id,
        source="deploy",
        event_type="started",
        message=f"Deploy started for {slug} ({'demo' if body.demo_mode else 'live'})",
        service="platform",
    )

    if body.demo_mode:
        await zerops_svc.deploy(config, demo_mode=True, repo_slug=slug)
        deployment.status = DeploymentStatus.IN_PROGRESS
        deployment.stage = DeploymentStage.BUILDING
        deployment.live_url = "https://demo-app.zerops.app"
        deployment.pipeline_state = "simulated"
        deployment_store.save(deployment)
        await aiops.create_incident(
            deployment.id,
            "Backend cannot start — migration failed",
            demo_mode=True,
            repo_slug=slug,
        )
    else:
        await _run_live_import(
            deployment,
            session=session,
            config=config,
            zerops_svc=zerops_svc,
            aiops=aiops,
            target_project=target_project,
            slug=slug,
        )
        deployment_store.save(deployment)

    return DeployResponse(
        deployment_id=deployment.id,
        status=deployment.status,
        stage=deployment.stage,
    )


@router.get("/deployment/{deployment_id}", response_model=Deployment)
async def get_deployment(deployment_id: UUID):
    deployment = deployment_store.get(deployment_id)
    if not deployment:
        raise HTTPException(status_code=404, detail="Deployment not found")
    return deployment


@router.get("/deployment/{deployment_id}/status", response_model=DeploymentStatusResponse)
async def get_deployment_status(deployment_id: UUID):
    deployment = deployment_store.get(deployment_id)
    if not deployment:
        raise HTTPException(status_code=404, detail="Deployment not found")

    zerops_svc = get_service("zerops")
    aiops = get_service("aiops")

    if not deployment.demo_mode and deployment.status == DeploymentStatus.IN_PROGRESS:
        api_host = deployment.service_hostnames.get("api", "")
        if api_host:
            pipe = await zerops_svc.get_pipeline_status(api_host, deployment.zerops_project_id)
            deployment.stage = pipe.get("stage", deployment.stage)
            pipeline_state = str(pipe.get("state", deployment.pipeline_state))
            deployment.pipeline_state = pipeline_state
            if pipe.get("stage") == DeploymentStage.COMPLETE:
                deployment.status = DeploymentStatus.SUCCEEDED
                deployment.stage = DeploymentStage.COMPLETE
                _clear_failure(deployment)
                urls = await zerops_svc.get_service_urls(
                    {
                        "web": deployment.service_hostnames.get("frontend", ""),
                        "api": api_host,
                    },
                    deployment.zerops_project_id,
                )
                deployment.service_urls = urls
                deployment.live_url = urls.get("web") or urls.get("api")
            elif pipe.get("stage") == DeploymentStage.FAILED:
                deployment.status = DeploymentStatus.FAILED
                logs = await zerops_svc.fetch_logs(
                    api_host, tail=80, project_id=deployment.zerops_project_id
                )
                phase, summary = classify_pipeline_failure(deployment.stage, logs)
                deployment.failure_phase = phase
                deployment.failure_summary = summary
                session = session_store.get(deployment.session_id)
                existing = await aiops.list_incidents(deployment_id)
                if not existing and session:
                    await aiops.create_incident_from_failure(
                        deployment_id,
                        title="Pipeline or readiness check failed",
                        logs=logs,
                        stack_summary=_stack_summary(session),
                        yaml_excerpt=(deployment.config.import_yaml if deployment.config else "")[:3000],
                    )
        deployment.updated_at = datetime.utcnow()
        deployment_store.save(deployment)

    return _status_response(deployment)


@router.post("/deploy/{deployment_id}/redeploy", response_model=DeployResponse)
async def redeploy(deployment_id: UUID, body: RetryDeployRequest | None = None):
    return await retry_deploy(deployment_id, body or RetryDeployRequest(from_phase="pipeline"))


@router.post("/deploy/{deployment_id}/retry", response_model=DeployResponse)
async def retry_deploy(deployment_id: UUID, body: RetryDeployRequest):
    deployment = deployment_store.get(deployment_id)
    if not deployment:
        raise HTTPException(status_code=404, detail="Deployment not found")
    if not deployment.config:
        raise HTTPException(status_code=400, detail="Deployment has no Zerops config to retry")

    session = session_store.get(deployment.session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    aiops = get_service("aiops")
    zerops_svc = get_service("zerops")
    await aiops.resolve_all_for_deployment(deployment_id)

    slug = deployment.repo_slug or "app"
    _clear_failure(deployment)
    deployment.status = DeploymentStatus.IN_PROGRESS
    deployment.updated_at = datetime.utcnow()

    if deployment.demo_mode:
        deployment.status = DeploymentStatus.SUCCEEDED
        deployment.stage = DeploymentStage.COMPLETE
        deployment.live_url = deployment.live_url or "https://demo-app.zerops.app"
        deployment.pipeline_state = "simulated"
    elif body.from_phase == "import":
        deployment.stage = DeploymentStage.BUILDING
        deployment.pipeline_state = "retrying_import"
        deployment_store.save(deployment)
        await _run_live_import(
            deployment,
            session=session,
            config=deployment.config,
            zerops_svc=zerops_svc,
            aiops=aiops,
            target_project=deployment.zerops_project_id,
            slug=slug,
        )
    else:
        deployment.stage = DeploymentStage.BUILDING
        deployment.pipeline_state = "redeploying"
        for hostname in (f"{slug}-web", f"{slug}-api"):
            await zerops_svc.trigger_redeploy(hostname, deployment.zerops_project_id)
        deployment.stage = DeploymentStage.READINESS_CHECK
        deployment.status = DeploymentStatus.IN_PROGRESS
        urls = await zerops_svc.get_service_urls(
            {"web": f"{slug}-web", "api": f"{slug}-api"},
            deployment.zerops_project_id,
        )
        deployment.service_urls = urls
        deployment.live_url = urls.get("web") or urls.get("api")

    deployment_store.save(deployment)
    record_ops_event(
        deployment_id,
        source="deploy",
        event_type="retry",
        message=f"Retry from {body.from_phase} phase",
        service="platform",
    )

    return DeployResponse(
        deployment_id=deployment.id,
        status=deployment.status,
        stage=deployment.stage,
    )


@router.get("/deployment/{deployment_id}/score", response_model=DeploymentScore)
async def deployment_score(deployment_id: UUID):
    deployment = deployment_store.get(deployment_id)
    if not deployment:
        raise HTTPException(status_code=404, detail="Deployment not found")

    orchestrator = get_orchestrator()
    score = await orchestrator.run(
        "optimization_advisor",
        AgentContext(payload={"deployment_id": str(deployment_id)}),
    )
    deployment.score = score
    deployment_store.save(deployment)
    record_ops_event(
        deployment_id,
        source="score",
        event_type="computed",
        message=f"Deployment score computed — overall {score.overall}/10",
        service="platform",
        metadata={"overall": score.overall},
    )
    return score


@router.get("/deployment/{deployment_id}/stream")
async def deployment_stream(deployment_id: UUID):
    deployment = deployment_store.get(deployment_id)
    if not deployment:
        raise HTTPException(status_code=404, detail="Deployment not found")

    zerops_svc = get_service("zerops")

    async def event_generator():
        async for chunk in stream_deployment_sse(deployment_id, zerops_svc):
            yield chunk

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
