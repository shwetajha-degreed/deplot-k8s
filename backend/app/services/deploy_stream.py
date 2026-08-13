"""SSE helpers for live deployment log streaming."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from uuid import UUID

from app.models.deployment import DeploymentStatus
from app.services.k8s import KubernetesService
from app.services.store import deployment_store

DEMO_DEPLOY_LOGS = [
    "[build] Resolving monorepo packages...",
    "[build] npm ci — frontend workspace",
    "[build] pip install — backend workspace",
    "[build] Compiling Next.js production bundle",
    "[upload] Pushing image to ACR",
    "[runtime] Rolling out python@3.12 deployment demo-api",
    "[runtime] Provisioning demo-postgres",
    "[runtime] Provisioning demo-cache",
    "[readiness] Running HTTP probe on /api/v1/health",
    "[error] Prisma P1001 — Can't reach database server",
    "[readiness] API readiness check failed",
]


async def stream_deployment_sse(
    deployment_id: UUID,
    k8s: KubernetesService,
    *,
    max_ticks: int = 90,
    poll_seconds: float = 2.0,
) -> AsyncIterator[str]:
    seen_logs = 0
    demo_line = 0

    for tick in range(max_ticks):
        deployment = deployment_store.get(deployment_id)
        if not deployment:
            yield _sse("error", {"message": "Deployment not found"})
            break

        status_payload = {
            "status": deployment.status.value,
            "stage": deployment.stage.value,
            "pipeline_state": deployment.pipeline_state,
            "demo_mode": deployment.demo_mode,
        }
        yield _sse("status", status_payload)

        new_lines: list[str] = []
        if deployment.demo_mode:
            batch_size = 2
            if demo_line < len(DEMO_DEPLOY_LOGS):
                new_lines = DEMO_DEPLOY_LOGS[demo_line : demo_line + batch_size]
                demo_line += len(new_lines)
            poll = 0.6
        else:
            poll = poll_seconds
            import_msg = deployment.k8s_message
            if tick == 0 and import_msg:
                new_lines = [import_msg[:500], *new_lines]
            api_deployment = deployment.service_hostnames.get("api", "")
            namespace = deployment.namespace or ""
            if api_deployment and namespace:
                all_logs = await k8s.fetch_logs(
                    namespace, api_deployment, tail_lines=200
                )
                if seen_logs < len(all_logs):
                    new_lines = [*new_lines, *all_logs[seen_logs:]]
                    seen_logs = len(all_logs)

        for line in new_lines:
            yield _sse("log", {"line": line, "service": "api"})

        terminal = deployment.status in (DeploymentStatus.SUCCEEDED, DeploymentStatus.FAILED)
        if terminal and (tick > 1 or deployment.demo_mode):
            yield _sse("done", {"status": deployment.status.value})
            break

        if deployment.demo_mode and demo_line >= len(DEMO_DEPLOY_LOGS) and tick >= 3:
            yield _sse("done", {"status": deployment.status.value})
            break

        await asyncio.sleep(poll if deployment.demo_mode else poll_seconds)

    yield _sse("end", {})


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"
