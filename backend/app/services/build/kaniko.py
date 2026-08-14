"""Kaniko-based in-cluster image builder.

Given a public repo URL and a generated Dockerfile, submits a Kubernetes Job
that clones the repo, drops in the Dockerfile, and runs Kaniko to build/push
to ACR. Workload identity on the `kaniko-builder` ServiceAccount handles
registry auth — no docker-config Secret is required.
"""

from __future__ import annotations

import asyncio
import hashlib
import shlex
import time
from typing import Any

from kubernetes import client
from kubernetes.client.rest import ApiException

from app.config import Settings
from app.services.base import BaseService
from app.services.k8s.client import KubernetesService


_KANIKO_IMAGE = "gcr.io/kaniko-project/executor:latest"
_GIT_IMAGE = "alpine/git:latest"
_AZ_CLI_IMAGE = "mcr.microsoft.com/azure-cli:latest"
_SA_NAME = "kaniko-builder"


class KanikoBuildService(BaseService):
    name = "kaniko_build"

    def __init__(self, settings: Settings, k8s: KubernetesService) -> None:
        self._settings = settings
        self._k8s = k8s

    async def build_image(
        self,
        namespace: str,
        service_name: str,
        slug: str,
        repo_url: str,
        dockerfile: str,
        git_ref: str = "main",
        build_args: dict[str, str] | None = None,
        github_token: str | None = None,
    ) -> dict[str, Any]:
        # SA must exist before the Job pod schedules; auto-create so callers
        # don't have to pre-provision every namespace.
        await self._ensure_service_account(namespace)

        image = f"{self._settings.acr_registry}/{slug}-{service_name}:latest"
        ref_hash = hashlib.sha1(f"{repo_url}@{git_ref}".encode()).hexdigest()[:8]
        job_name = f"build-{slug}-{service_name}-{ref_hash}"

        # Private repos: store the PAT in a Secret so the git-clone init
        # container can read it via env var (not baked into argv where
        # `kubectl describe` would leak it).
        token_secret_name: str | None = None
        if github_token:
            token_secret_name = f"gh-token-{ref_hash}"
            await self._ensure_github_token_secret(namespace, token_secret_name, github_token)

        job = self._build_job_manifest(
            job_name=job_name,
            namespace=namespace,
            image=image,
            repo_url=repo_url,
            git_ref=git_ref,
            dockerfile=dockerfile,
            build_args=build_args or {},
            token_secret_name=token_secret_name,
        )

        # Delete any prior Job with the same name so re-runs re-execute cleanly.
        await self._delete_job_if_exists(namespace, job_name)

        try:
            await self._k8s._apply(job)
            status = "queued"
            logs: list[str] = []
        except ApiException as exc:
            status = "failed"
            logs = [f"job submit failed: {exc.reason}", str(exc)]

        return {
            "image": image,
            "job_name": job_name,
            "namespace": namespace,
            "status": status,
            "logs": logs,
        }

    async def wait_for_build(
        self,
        namespace: str,
        job_name: str,
        timeout: int = 600,
    ) -> dict[str, Any]:
        deadline = time.monotonic() + timeout
        batch = client.BatchV1Api()
        while time.monotonic() < deadline:
            try:
                job = await asyncio.to_thread(
                    batch.read_namespaced_job_status,
                    name=job_name,
                    namespace=namespace,
                )
            except ApiException as exc:
                if exc.status == 404:
                    await asyncio.sleep(2.0)
                    continue
                return {
                    "status": "failed",
                    "job_name": job_name,
                    "logs": [f"read job status failed: {exc.reason}"],
                }

            status = job.status or client.V1JobStatus()
            if (status.succeeded or 0) >= 1:
                return {
                    "status": "succeeded",
                    "job_name": job_name,
                    "logs": await self._tail_job_logs(namespace, job_name),
                }
            # status.failed counts individual POD failures; when backoffLimit
            # allows retries (or when the Job is throttled by a ResourceQuota
            # and pods get FailedCreate), that counter climbs while the Job
            # itself is still healthy. Only treat the JOB as failed when a
            # Failed condition is on the Job — that's what backoffLimit
            # exceeded produces.
            for cond in status.conditions or []:
                if getattr(cond, "type", "") == "Failed" and getattr(cond, "status", "") == "True":
                    return {
                        "status": "failed",
                        "job_name": job_name,
                        "logs": await self._tail_job_logs(namespace, job_name),
                    }
            await asyncio.sleep(3.0)

        return {
            "status": "failed",
            "job_name": job_name,
            "logs": [f"timed out after {timeout}s"]
            + await self._tail_job_logs(namespace, job_name),
        }

    # --------------------------------------------------------------- helpers --

    async def _ensure_github_token_secret(
        self, namespace: str, name: str, token: str
    ) -> None:
        import base64

        body = {
            "apiVersion": "v1",
            "kind": "Secret",
            "metadata": {
                "name": name,
                "namespace": namespace,
                "labels": {"app.kubernetes.io/managed-by": "deplot"},
            },
            "type": "Opaque",
            "data": {"token": base64.b64encode(token.encode()).decode()},
        }
        try:
            await self._k8s._apply(body)
        except ApiException as exc:
            if exc.status not in (404, 409, 422):
                raise

    async def _ensure_service_account(self, namespace: str) -> None:
        wi_client_id = self._settings.azure_workload_identity_client_id
        sa = client.V1ServiceAccount(
            metadata=client.V1ObjectMeta(
                name=_SA_NAME,
                namespace=namespace,
                labels={"azure.workload.identity/use": "true"},
                annotations=(
                    {"azure.workload.identity/client-id": wi_client_id}
                    if wi_client_id
                    else None
                ),
            )
        )
        try:
            await asyncio.to_thread(
                self._k8s._core().create_namespaced_service_account,
                namespace=namespace,
                body=sa,
            )
        except ApiException as exc:
            if exc.status != 409:
                raise

    async def _delete_job_if_exists(self, namespace: str, job_name: str) -> None:
        batch = client.BatchV1Api()
        try:
            await asyncio.to_thread(
                batch.delete_namespaced_job,
                name=job_name,
                namespace=namespace,
                body=client.V1DeleteOptions(propagation_policy="Background"),
            )
        except ApiException as exc:
            if exc.status != 404:
                raise
            return
        # Give the API server a moment to reap the old pods before we recreate.
        await asyncio.sleep(1.0)

    async def _tail_job_logs(
        self, namespace: str, job_name: str, tail_lines: int = 200
    ) -> list[str]:
        core = self._k8s._core()
        try:
            pods = await asyncio.to_thread(
                core.list_namespaced_pod,
                namespace=namespace,
                label_selector=f"job-name={job_name}",
            )
        except ApiException:
            return []

        items = list(pods.items or [])
        if not items:
            return []
        items.sort(
            key=lambda p: getattr(p.metadata, "creation_timestamp", None) or 0,
            reverse=True,
        )
        pod_name = items[0].metadata.name
        try:
            raw = await asyncio.to_thread(
                core.read_namespaced_pod_log,
                name=pod_name,
                namespace=namespace,
                container="kaniko",
                tail_lines=tail_lines,
            )
        except ApiException:
            return []
        return (raw or "").splitlines()

    def _build_job_manifest(
        self,
        *,
        job_name: str,
        namespace: str,
        image: str,
        repo_url: str,
        git_ref: str,
        dockerfile: str,
        build_args: dict[str, str],
        token_secret_name: str | None = None,
    ) -> dict[str, Any]:
        # Passing the Dockerfile through argv keeps us from needing a ConfigMap;
        # base64 avoids quoting hazards inside the shell.
        import base64

        encoded = base64.b64encode(dockerfile.encode("utf-8")).decode("ascii")

        # For private repos, GITHUB_TOKEN is mounted as an env var from a
        # Secret and injected into the clone URL as x-access-token password.
        # Not in argv so `kubectl describe` doesn't leak it.
        if token_secret_name:
            clone_url_expr = (
                'https://x-access-token:${GITHUB_TOKEN}@'
                + repo_url.replace("https://", "", 1)
            )
            clone_cmd = (
                f"set -eu; "
                f'git clone --depth 1 --branch {shlex.quote(git_ref)} '
                f'"{clone_url_expr}" /workspace/src && '
                f"cp -a /workspace/src/. /workspace/ && "
                f"echo {shlex.quote(encoded)} | base64 -d > /workspace/Dockerfile.deplot"
            )
        else:
            clone_cmd = (
                f"set -eu; "
                f"git clone --depth 1 --branch {shlex.quote(git_ref)} "
                f"{shlex.quote(repo_url)} /workspace/src && "
                f"cp -a /workspace/src/. /workspace/ && "
                f"echo {shlex.quote(encoded)} | base64 -d > /workspace/Dockerfile.deplot"
            )

        # ACR name derives from the FQDN (`dgscucorecr01.azurecr.io` -> `dgscucorecr01`).
        acr_name = self._settings.acr_registry.split(".")[0]
        acr_server = self._settings.acr_registry
        # az acr login without --expose-token invokes docker login; the az-cli
        # image has no docker daemon. --expose-token returns the token as JSON
        # so we can write /kaniko/.docker/config.json directly. Username
        # 00000000-0000-0000-0000-000000000000 is the ACR sentinel for
        # token-based auth.
        acr_auth_cmd = (
            "set -eu; "
            'az login --federated-token "$(cat $AZURE_FEDERATED_TOKEN_FILE)" '
            "--service-principal -u $AZURE_CLIENT_ID -t $AZURE_TENANT_ID > /dev/null; "
            f"TOKEN=$(az acr login --name {shlex.quote(acr_name)} --expose-token "
            "--output tsv --query accessToken); "
            "mkdir -p /kaniko/.docker; "
            f"AUTH=$(printf %s '00000000-0000-0000-0000-000000000000:'\"$TOKEN\" | base64 -w0); "
            f'printf \'{{"auths":{{"{acr_server}":{{"auth":"%s"}}}}}}\' "$AUTH" '
            "> /kaniko/.docker/config.json"
        )

        return {
            "apiVersion": "batch/v1",
            "kind": "Job",
            "metadata": {
                "name": job_name,
                "namespace": namespace,
                "labels": {
                    "app.kubernetes.io/managed-by": "deplot",
                    "app.kubernetes.io/component": "image-build",
                },
            },
            "spec": {
                "backoffLimit": 1,
                "ttlSecondsAfterFinished": 3600,
                "template": {
                    "metadata": {
                        "labels": {
                            "job-name": job_name,
                            "app.kubernetes.io/managed-by": "deplot",
                            "azure.workload.identity/use": "true",
                        }
                    },
                    "spec": {
                        # TODO: kaniko-builder SA is auto-created per namespace
                        # in _ensure_service_account; platform annotates it
                        # with azure.workload.identity/client-id for ACR push.
                        "serviceAccountName": _SA_NAME,
                        "restartPolicy": "Never",
                        "initContainers": [
                            {
                                "name": "git-clone",
                                "image": _GIT_IMAGE,
                                "command": ["/bin/sh", "-c", clone_cmd],
                                "env": (
                                    [
                                        {
                                            "name": "GITHUB_TOKEN",
                                            "valueFrom": {
                                                "secretKeyRef": {
                                                    "name": token_secret_name,
                                                    "key": "token",
                                                }
                                            },
                                        }
                                    ]
                                    if token_secret_name
                                    else []
                                ),
                                "volumeMounts": [
                                    {"name": "workspace", "mountPath": "/workspace"}
                                ],
                            },
                            {
                                # Exchange projected federated token -> ACR
                                # refresh token via az CLI; write docker config
                                # to a shared volume Kaniko reads.
                                "name": "acr-auth",
                                "image": _AZ_CLI_IMAGE,
                                "command": ["/bin/sh", "-c", acr_auth_cmd],
                                "volumeMounts": [
                                    {"name": "docker-config", "mountPath": "/kaniko/.docker"}
                                ],
                            },
                        ],
                        "containers": [
                            {
                                "name": "kaniko",
                                "image": _KANIKO_IMAGE,
                                "args": [
                                    "--dockerfile=/workspace/Dockerfile.deplot",
                                    "--context=/workspace",
                                    f"--destination={image}",
                                    "--cache=true",
                                    "--use-new-run",
                                    *[f"--build-arg={k}={v}" for k, v in build_args.items()],
                                ],
                                # Node builds routinely need >1 GB during
                                # snapshot; the namespace LimitRange default
                                # (512 Mi) OOMs mid-build.
                                "resources": {
                                    "requests": {"cpu": "500m", "memory": "2Gi"},
                                    "limits": {"cpu": "2", "memory": "3Gi"},
                                },
                                "volumeMounts": [
                                    {"name": "workspace", "mountPath": "/workspace"},
                                    {"name": "docker-config", "mountPath": "/kaniko/.docker"},
                                ],
                            }
                        ],
                        "volumes": [
                            {"name": "workspace", "emptyDir": {}},
                            {"name": "docker-config", "emptyDir": {}},
                        ],
                    },
                },
            },
        }
