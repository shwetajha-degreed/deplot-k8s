"""Provisions a single-instance Redis via a plain Deployment + Service + PVC."""

from __future__ import annotations

import asyncio
import base64
import secrets
import time
from typing import Any

from kubernetes.client.rest import ApiException

from app.services.base import BaseService
from app.services.k8s import KubernetesService


class RedisProvisioner(BaseService):
    name = "deps_redis"

    def __init__(self, k8s: KubernetesService) -> None:
        self._k8s = k8s

    async def provision(
        self,
        namespace: str,
        release_name: str,
        storage_gb: int = 1,
    ) -> dict[str, Any]:
        secret_name = f"{release_name}-auth"
        password = await self._ensure_password(namespace, secret_name)

        labels = {
            "app.kubernetes.io/name": release_name,
            "app.kubernetes.io/managed-by": "deplot",
            "app.kubernetes.io/component": "cache",
        }

        pvc = {
            "apiVersion": "v1",
            "kind": "PersistentVolumeClaim",
            "metadata": {"name": f"{release_name}-data", "namespace": namespace, "labels": labels},
            "spec": {
                "accessModes": ["ReadWriteOnce"],
                "resources": {"requests": {"storage": f"{storage_gb}Gi"}},
            },
        }

        secret_manifest = {
            "apiVersion": "v1",
            "kind": "Secret",
            "metadata": {"name": secret_name, "namespace": namespace, "labels": labels},
            "type": "Opaque",
            "data": {"password": base64.b64encode(password.encode()).decode()},
        }

        deployment = {
            "apiVersion": "apps/v1",
            "kind": "Deployment",
            "metadata": {"name": release_name, "namespace": namespace, "labels": labels},
            "spec": {
                "replicas": 1,
                "selector": {"matchLabels": labels},
                "strategy": {"type": "Recreate"},
                "template": {
                    "metadata": {"labels": labels},
                    "spec": {
                        "containers": [
                            {
                                "name": "redis",
                                "image": "redis:7-alpine",
                                "command": ["redis-server"],
                                "args": [
                                    "--requirepass",
                                    "$(REDIS_PASSWORD)",
                                    "--appendonly",
                                    "yes",
                                ],
                                "env": [
                                    {
                                        "name": "REDIS_PASSWORD",
                                        "valueFrom": {
                                            "secretKeyRef": {
                                                "name": secret_name,
                                                "key": "password",
                                            }
                                        },
                                    }
                                ],
                                "ports": [{"containerPort": 6379, "name": "redis"}],
                                "resources": {
                                    "requests": {"cpu": "50m", "memory": "64Mi"},
                                    "limits": {"cpu": "200m", "memory": "256Mi"},
                                },
                                "volumeMounts": [
                                    {"name": "data", "mountPath": "/data"}
                                ],
                            }
                        ],
                        "volumes": [
                            {
                                "name": "data",
                                "persistentVolumeClaim": {"claimName": f"{release_name}-data"},
                            }
                        ],
                    },
                },
            },
        }

        service = {
            "apiVersion": "v1",
            "kind": "Service",
            "metadata": {"name": release_name, "namespace": namespace, "labels": labels},
            "spec": {
                "selector": labels,
                "ports": [{"name": "redis", "port": 6379, "targetPort": 6379}],
                "type": "ClusterIP",
            },
        }

        try:
            await self._k8s._apply(pvc)
            await self._k8s._apply(secret_manifest)
            await self._k8s._apply(deployment)
            await self._k8s._apply(service)
        except ApiException as exc:
            return {"ready": False, "error": f"apply failed: {exc.reason}"}

        ready = await self._wait_ready(namespace, release_name, timeout=180)
        if not ready:
            return {"ready": False, "error": f"redis {release_name} not ready within timeout"}

        return {
            "env": {"REDIS_URL": f"redis://:{password}@{release_name}:6379/0"},
            "service": release_name,
            "ready": True,
            "secret_name": secret_name,
        }

    async def _ensure_password(self, namespace: str, secret_name: str) -> str:
        # Reuse an existing password so reruns don't invalidate live clients.
        try:
            existing = await asyncio.to_thread(
                self._k8s._core().read_namespaced_secret,
                name=secret_name,
                namespace=namespace,
            )
            data = getattr(existing, "data", None) or {}
            pw_b64 = data.get("password")
            if pw_b64:
                return base64.b64decode(pw_b64).decode("utf-8")
        except ApiException as exc:
            if exc.status != 404:
                raise
        return secrets.token_hex(8)

    async def _wait_ready(
        self, namespace: str, name: str, timeout: int = 180, interval: float = 3.0
    ) -> bool:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                dep = await asyncio.to_thread(
                    self._k8s._apps().read_namespaced_deployment_status,
                    name=name,
                    namespace=namespace,
                )
            except ApiException:
                await asyncio.sleep(interval)
                continue
            status = dep.status
            spec_replicas = (dep.spec.replicas if dep.spec else 1) or 1
            ready = (status.ready_replicas if status else 0) or 0
            if ready >= spec_replicas:
                return True
            await asyncio.sleep(interval)
        return False
