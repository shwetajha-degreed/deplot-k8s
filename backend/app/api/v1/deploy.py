import asyncio
from datetime import datetime
from pathlib import Path
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
from app.services.k8s import hostnames_for_slug, repo_slug_from_url
from app.services.store import deployment_store, session_store
from app.services.timeline import record_ops_event

router = APIRouter()


def _inject_env_into_deployments(manifests: list[dict], env: dict[str, str]) -> None:
    if not env:
        return
    for manifest in manifests:
        if not isinstance(manifest, dict) or manifest.get("kind") != "Deployment":
            continue
        containers = (
            (((manifest.get("spec") or {}).get("template") or {}).get("spec") or {}).get(
                "containers"
            )
            or []
        )
        for container in containers:
            existing = container.get("env") or []
            by_name = {e.get("name"): e for e in existing if isinstance(e, dict)}
            for key, value in env.items():
                by_name[key] = {"name": key, "value": value}
            container["env"] = list(by_name.values())


def _fallback_dockerfile(stack, service_name: str) -> str:
    is_frontend = service_name in ("web", "frontend")
    fw = ((stack.backend_framework if not is_frontend else stack.framework) or "").lower()
    runtime = ((stack.backend_runtime if not is_frontend else stack.runtime) or "").lower()
    sub = (
        stack.monorepo_frontend_path if is_frontend else stack.monorepo_backend_path
    ) or "."

    if is_frontend or "next" in fw or "node" in runtime:
        # npm install (not `npm ci`) — lockfile may be absent; robustness over
        # reproducibility for the sandbox smoke path.
        # ARG NEXT_PUBLIC_API_URL is baked into the Next.js build because
        # Next.js compiles NEXT_PUBLIC_* env vars into the client bundle at
        # build time; setting it at runtime doesn't reach the browser.
        return (
            f"FROM node:22-alpine AS builder\n"
            f"ARG NEXT_PUBLIC_API_URL\n"
            f"ENV NEXT_PUBLIC_API_URL=$NEXT_PUBLIC_API_URL\n"
            f"WORKDIR /app\n"
            f"COPY {sub}/package*.json ./\n"
            f"RUN npm install --no-audit --no-fund\n"
            f"COPY {sub}/ ./\n"
            f"RUN npm run build || echo 'no build step'\n"
            f"\n"
            f"FROM node:22-alpine\n"
            f"WORKDIR /app\n"
            f"ENV NODE_ENV=production\n"
            f"RUN addgroup -S app && adduser -S app -G app\n"
            f"COPY --from=builder --chown=app:app /app ./\n"
            f"USER app\n"
            f"EXPOSE 3000\n"
            f'CMD ["npm", "start"]\n'
        )
    if "fastapi" in fw or "python" in runtime:
        return (
            f"FROM python:3.12-slim\n"
            f"WORKDIR /app\n"
            f"ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1\n"
            f"COPY {sub}/requirements.txt* {sub}/pyproject.toml* ./\n"
            f"RUN pip install --no-cache-dir -r requirements.txt || true\n"
            f"COPY {sub}/ ./\n"
            "RUN useradd -u 1001 -m app && chown -R app:app /app\n"
            "USER app\n"
            "EXPOSE 8000\n"
            'CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]\n'
        )
    return (
        "FROM alpine:3.20\n"
        "WORKDIR /app\n"
        "COPY . .\n"
        "RUN adduser -D -u 1001 app\n"
        "USER app\n"
        "EXPOSE 8080\n"
        'CMD ["/bin/sh", "-c", "echo no runtime configured; sleep infinity"]\n'
    )


def _dockerfile_stack_summary(stack) -> str:
    parts = [
        f"framework={stack.framework}",
        f"runtime={stack.runtime}",
        f"has_backend={stack.has_backend}",
        f"has_frontend={stack.has_frontend}",
        f"backend_framework={stack.backend_framework}",
        f"backend_runtime={stack.backend_runtime}",
    ]
    return ", ".join(p for p in parts if p.split("=")[1] not in ("None", ""))


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
        message=deployment.k8s_message,
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
) -> None:
    phase, summary = classify_import_failure(result)
    deployment.status = DeploymentStatus.FAILED
    deployment.stage = DeploymentStage.FAILED
    deployment.pipeline_state = "import_failed"
    deployment.failure_phase = phase
    deployment.failure_summary = summary
    deployment.k8s_message = (result.get("stderr") or "")[:2000] or result.get("error") or summary
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
        title="K8s manifest apply failed",
        logs=logs,
        stack_summary=_stack_summary(session),
        yaml_excerpt=str(config.manifests)[:3000],
    )


async def _apply_import_success(
    deployment: Deployment,
    *,
    result: dict,
    k8s_svc,
    namespace: str,
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
        message="K8s manifest apply completed — rollout starting",
        service="platform",
    )
    urls = await k8s_svc.get_service_urls(namespace) if namespace else {}
    deployment.service_urls = urls
    deployment.live_url = urls.get("web") or urls.get("api") or (next(iter(urls.values()), None))


async def _run_live_import(
    deployment: Deployment,
    *,
    session,
    config,
    k8s_svc,
    aiops,
    namespace: str,
    slug: str,
) -> None:
    result = await k8s_svc.deploy(
        namespace=namespace,
        manifests=config.manifests,
        demo_mode=False,
    )
    deployment.k8s_message = (result.get("stdout") or "")[:2000] or result.get("error")
    deployment.routing_checklist = result.get("routing_checklist") or []

    if result.get("ok"):
        await _apply_import_success(
            deployment,
            result=result,
            k8s_svc=k8s_svc,
            namespace=namespace,
            slug=slug,
        )
        # WHY: fire-and-forget — HTTP response returns immediately while the
        # heal loop watches the Deployment in the background for up to 10 min.
        try:
            deployment_names = [
                (m.get("metadata") or {}).get("name")
                for m in (config.manifests or [])
                if isinstance(m, dict) and m.get("kind") == "Deployment"
            ]
            deployment_names = [n for n in deployment_names if n]
            if deployment_names:
                heal = get_service("heal_loop")
                asyncio.create_task(
                    heal.watch_and_heal(deployment.id, namespace, deployment_names)
                )
        except Exception as exc:
            record_ops_event(
                deployment.id,
                source="heal",
                event_type="loop_start_failed",
                message=f"failed to start heal loop: {exc!r}"[:500],
                service="platform",
            )
    else:
        await _mark_import_failure(
            deployment,
            result=result,
            session=session,
            config=config,
            aiops=aiops,
        )


@router.post("/deploy", response_model=DeployResponse)
async def start_deploy(body: DeployRequest):
    session = session_store.get(body.session_id)
    if not session or not session.stack:
        raise HTTPException(status_code=404, detail="Session not found")

    yaml_svc = get_service("yaml_generator")
    k8s_svc = get_service("kubernetes")
    planner = get_service("planner")
    aiops = get_service("aiops")
    gemini = get_service("gemini")
    kaniko_svc = get_service("kaniko_build")

    if session.repo_url:
        session.stack.repo_slug = repo_slug_from_url(session.repo_url)

    settings = get_settings()
    slug = session.stack.repo_slug or repo_slug_from_url(session.repo_url)
    namespace = f"deploy-{slug}"

    if not body.demo_mode and session.repo_url:
        services: list[str] = []
        if session.stack.has_backend:
            services.append("api")
        if session.stack.has_frontend:
            services.append("frontend")

        if services:
            ns_result = await k8s_svc.create_namespace(namespace)
            if not ns_result.get("ok"):
                raise HTTPException(
                    status_code=502,
                    detail={"error": "namespace_create_failed", **ns_result},
                )
            # Kaniko runs in a shared build namespace so one federated
            # credential covers every deploy. NetworkPolicy/quota apply here
            # too — the LimitRange defaults let admission-injected sidecars
            # pass the quota.
            build_ns_result = await k8s_svc.create_namespace(settings.build_namespace)
            if not build_ns_result.get("ok"):
                raise HTTPException(
                    status_code=502,
                    detail={"error": "build_namespace_create_failed", **build_ns_result},
                )

            prompt_path = Path(settings.prompts_dir) / "dockerfile_generator.md"
            prompt_template = (
                prompt_path.read_text(encoding="utf-8") if prompt_path.exists() else ""
            )
            stack_summary = _dockerfile_stack_summary(session.stack)

            # Deterministic hostnames — computed BEFORE builds so the
            # frontend can bake the API URL into its build (NEXT_PUBLIC_*
            # env vars are compiled into the Next.js JS bundle at build
            # time, not read at runtime).
            api_url = (
                f"https://{slug}-api.{settings.base_domain}/api/v1"
                if "api" in services
                else ""
            )

            build_coros = []
            for svc_name in services:
                dockerfile = await gemini.generate_dockerfile(
                    slug=slug,
                    repo_url=session.repo_url,
                    service_name=svc_name,
                    stack_summary=stack_summary,
                    prompt_template=prompt_template,
                )
                if not dockerfile:
                    dockerfile = _fallback_dockerfile(session.stack, svc_name)
                svc_build_args: dict[str, str] = {}
                if svc_name in ("frontend", "web") and api_url:
                    svc_build_args["NEXT_PUBLIC_API_URL"] = api_url
                build_coros.append(
                    kaniko_svc.build_image(
                        namespace=settings.build_namespace,
                        service_name=svc_name,
                        slug=slug,
                        repo_url=session.repo_url,
                        dockerfile=dockerfile,
                        build_args=svc_build_args,
                    )
                )
            submissions = await asyncio.gather(*build_coros)

            waits = [
                kaniko_svc.wait_for_build(settings.build_namespace, sub["job_name"])
                for sub in submissions
            ]
            results = await asyncio.gather(*waits)

            for sub, res in zip(submissions, results):
                if res.get("status") != "succeeded":
                    raise HTTPException(
                        status_code=502,
                        detail={
                            "error": "image build failed",
                            "image": sub["image"],
                            "job_name": sub["job_name"],
                            "logs": (res.get("logs") or [])[-40:],
                        },
                    )

    deps_env: dict[str, str] = {}
    if not body.demo_mode and session.stack.database:
        postgres = get_service("deps_postgres")
        pg_result = await postgres.provision(namespace, f"{slug}-db")
        if not pg_result.get("ready"):
            raise HTTPException(
                status_code=502,
                detail={
                    "error": "postgres provisioning failed",
                    "detail": pg_result.get("error"),
                },
            )
        deps_env.update(pg_result["env"])
    if not body.demo_mode and session.stack.cache:
        redis = get_service("deps_redis")
        rd_result = await redis.provision(namespace, f"{slug}-cache")
        if not rd_result.get("ready"):
            raise HTTPException(
                status_code=502,
                detail={
                    "error": "redis provisioning failed",
                    "detail": rd_result.get("error"),
                },
            )
        deps_env.update(rd_result["env"])
    if not body.demo_mode and session.stack.search:
        typesense = get_service("deps_typesense")
        ts_result = await typesense.provision(namespace, f"{slug}-search")
        if not ts_result.get("ready"):
            raise HTTPException(
                status_code=502,
                detail={
                    "error": "typesense provisioning failed",
                    "detail": ts_result.get("error"),
                },
            )
        deps_env.update(ts_result["env"])

    config = await yaml_svc.generate(session.stack, session.repo_url)
    _inject_env_into_deployments(config.manifests, deps_env)

    graph = session.architecture
    if not graph:
        orchestrator = get_orchestrator()
        graph = await orchestrator.run(
            "infrastructure_planner",
            AgentContext(payload={"stack": session.stack}),
        )

    plan = planner.build_plan(session.stack, graph)
    namespace = config.namespace or namespace

    deployment = Deployment(
        session_id=body.session_id,
        config=config,
        plan=plan,
        demo_mode=body.demo_mode,
        repo_slug=slug,
        namespace=namespace,
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
        await k8s_svc.deploy(namespace=namespace, manifests=config.manifests, demo_mode=True)
        deployment.status = DeploymentStatus.IN_PROGRESS
        deployment.stage = DeploymentStage.BUILDING
        deployment.live_url = "https://demo-app.example.com"
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
            k8s_svc=k8s_svc,
            aiops=aiops,
            namespace=namespace,
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

    k8s_svc = get_service("kubernetes")
    aiops = get_service("aiops")

    if not deployment.demo_mode and deployment.status == DeploymentStatus.IN_PROGRESS:
        api_host = deployment.service_hostnames.get("api", "")
        namespace = deployment.namespace or ""
        if api_host and namespace:
            pipe = await k8s_svc.get_pipeline_status(namespace, api_host)
            deployment.stage = pipe.get("stage", deployment.stage)
            pipeline_state = str(pipe.get("state", deployment.pipeline_state))
            deployment.pipeline_state = pipeline_state
            if pipe.get("stage") == DeploymentStage.COMPLETE:
                deployment.status = DeploymentStatus.SUCCEEDED
                deployment.stage = DeploymentStage.COMPLETE
                _clear_failure(deployment)
                urls = await k8s_svc.get_service_urls(namespace)
                deployment.service_urls = urls
                deployment.live_url = urls.get("web") or urls.get("api") or (next(iter(urls.values()), None))
            elif pipe.get("stage") == DeploymentStage.FAILED:
                deployment.status = DeploymentStatus.FAILED
                logs = await k8s_svc.fetch_logs(namespace, api_host, tail_lines=80)
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
                        yaml_excerpt=str(deployment.config.manifests if deployment.config else "")[:3000],
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
        raise HTTPException(status_code=400, detail="Deployment has no K8s config to retry")

    session = session_store.get(deployment.session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    aiops = get_service("aiops")
    k8s_svc = get_service("kubernetes")
    await aiops.resolve_all_for_deployment(deployment_id)

    slug = deployment.repo_slug or "app"
    namespace = deployment.namespace or f"deploy-{slug}"
    _clear_failure(deployment)
    deployment.status = DeploymentStatus.IN_PROGRESS
    deployment.updated_at = datetime.utcnow()

    if deployment.demo_mode:
        deployment.status = DeploymentStatus.SUCCEEDED
        deployment.stage = DeploymentStage.COMPLETE
        deployment.live_url = deployment.live_url or "https://demo-app.example.com"
        deployment.pipeline_state = "simulated"
    elif body.from_phase == "import":
        deployment.stage = DeploymentStage.BUILDING
        deployment.pipeline_state = "retrying_import"
        deployment_store.save(deployment)
        await _run_live_import(
            deployment,
            session=session,
            config=deployment.config,
            k8s_svc=k8s_svc,
            aiops=aiops,
            namespace=namespace,
            slug=slug,
        )
    else:
        deployment.stage = DeploymentStage.BUILDING
        deployment.pipeline_state = "redeploying"
        for hostname in (f"{slug}-web", f"{slug}-api"):
            await k8s_svc.trigger_redeploy(hostname, namespace)
        deployment.stage = DeploymentStage.READINESS_CHECK
        deployment.status = DeploymentStatus.IN_PROGRESS
        urls = await k8s_svc.get_service_urls(namespace)
        deployment.service_urls = urls
        deployment.live_url = urls.get("web") or urls.get("api") or (next(iter(urls.values()), None))

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

    k8s_svc = get_service("kubernetes")

    async def event_generator():
        async for chunk in stream_deployment_sse(deployment_id, k8s_svc):
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
