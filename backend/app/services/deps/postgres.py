"""Provisions a Postgres cluster via the CloudNativePG operator."""

from __future__ import annotations

import asyncio
import base64
import time
from typing import Any

from kubernetes.client.rest import ApiException

from app.services.base import BaseService
from app.services.k8s import KubernetesService


_CNPG_GROUP = "postgresql.cnpg.io"
_CNPG_VERSION = "v1"
_CNPG_PLURAL = "clusters"


class PostgresProvisioner(BaseService):
    name = "deps_postgres"

    def __init__(self, k8s: KubernetesService) -> None:
        self._k8s = k8s

    async def provision(
        self,
        namespace: str,
        release_name: str,
        storage_gb: int = 5,
        instances: int = 1,
    ) -> dict[str, Any]:
        manifest: dict[str, Any] = {
            "apiVersion": f"{_CNPG_GROUP}/{_CNPG_VERSION}",
            "kind": "Cluster",
            "metadata": {"name": release_name, "namespace": namespace},
            "spec": {
                "instances": instances,
                "storage": {"size": f"{storage_gb}Gi"},
            },
        }

        try:
            await self._k8s._apply(manifest)
        except ApiException as exc:
            if exc.status not in (409,):
                return {"ready": False, "error": f"apply failed: {exc.reason}"}

        ready = await self._wait_ready(namespace, release_name, timeout=300)
        if not ready:
            return {"ready": False, "error": f"cluster {release_name} not ready within timeout"}

        secret_name = f"{release_name}-app"
        try:
            secret_data = await self._read_secret(namespace, secret_name)
        except ApiException as exc:
            return {"ready": False, "error": f"secret {secret_name} unreadable: {exc.reason}"}

        uri = secret_data.get("uri")
        if uri:
            # CNPG's `uri` value is bare — append sslmode for downstream clients.
            database_url = uri if "sslmode=" in uri else f"{uri}?sslmode=require"
        else:
            user = secret_data.get("username", "")
            pw = secret_data.get("password", "")
            host = secret_data.get("host", f"{release_name}-rw.{namespace}.svc")
            port = secret_data.get("port", "5432")
            db = secret_data.get("dbname", "app")
            database_url = f"postgres://{user}:{pw}@{host}:{port}/{db}?sslmode=require"

        return {
            "env": {"DATABASE_URL": database_url},
            "cluster": release_name,
            "ready": True,
            "secret_name": secret_name,
        }

    async def _wait_ready(
        self, namespace: str, name: str, timeout: int = 300, interval: float = 5.0
    ) -> bool:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                obj = await asyncio.to_thread(
                    self._k8s._custom().get_namespaced_custom_object_status,
                    group=_CNPG_GROUP,
                    version=_CNPG_VERSION,
                    namespace=namespace,
                    plural=_CNPG_PLURAL,
                    name=name,
                )
            except ApiException:
                await asyncio.sleep(interval)
                continue

            status = (obj or {}).get("status") or {}
            phase = status.get("phase", "")
            ready_instances = status.get("readyInstances", 0)
            instances = status.get("instances", 0)
            if "healthy" in phase.lower() or (
                instances and ready_instances and ready_instances >= instances
            ):
                return True
            for cond in status.get("conditions", []) or []:
                if cond.get("type") == "Ready" and cond.get("status") == "True":
                    return True
            await asyncio.sleep(interval)
        return False

    async def _read_secret(self, namespace: str, name: str) -> dict[str, str]:
        secret = await asyncio.to_thread(
            self._k8s._core().read_namespaced_secret,
            name=name,
            namespace=namespace,
        )
        raw: dict[str, str] = getattr(secret, "data", None) or {}
        return {k: base64.b64decode(v).decode("utf-8") for k, v in raw.items()}
