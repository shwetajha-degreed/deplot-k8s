"""Kubernetes adapter that mirrors the shape of the retired service."""

from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator
from typing import Any

import yaml
from kubernetes import client, config
from kubernetes.client.rest import ApiException
from kubernetes.config.config_exception import ConfigException

from app.models.deployment import DeploymentStage
from app.services.base import BaseService

from .events import classify_pod, stream_events
from .manifests import (
    DefaultDenyNetworkPolicy,
    Namespace,
    ResourceQuota,
    ResourceRef,
)


# Field manager used for server-side apply; K8s attributes ownership by this name.
_FIELD_MANAGER = "deplot"


class KubernetesService(BaseService):
    name = "kubernetes"

    # Rough map from K8s condition/reason strings to the stage enum callers know.
    STAGE_MAP: dict[str, DeploymentStage] = {
        "pending": DeploymentStage.QUEUED,
        "containercreating": DeploymentStage.CREATING_RUNTIME,
        "podinitializing": DeploymentStage.INSTALLING,
        "imagepull": DeploymentStage.UPLOADING,
        "progressing": DeploymentStage.BUILDING,
        "available": DeploymentStage.COMPLETE,
        "replicafailure": DeploymentStage.FAILED,
    }

    def __init__(self, settings) -> None:
        self._settings = settings
        self._load_config()

    # ------------------------------------------------------------------ auth --

    def _load_config(self) -> None:
        try:
            # In-cluster relies on the projected Azure Workload Identity token
            # mounted on the ServiceAccount annotated with
            # azure.workload.identity/client-id=<settings.azure_workload_identity_client_id>.
            config.load_incluster_config()
        except ConfigException:
            config.load_kube_config(config_file=self._settings.kubeconfig_path or None)

    # Fresh API clients per call keeps this cheap and thread-safe.
    def _core(self) -> client.CoreV1Api:
        return client.CoreV1Api()

    def _apps(self) -> client.AppsV1Api:
        return client.AppsV1Api()

    def _custom(self) -> client.CustomObjectsApi:
        return client.CustomObjectsApi()

    def _networking(self) -> client.NetworkingV1Api:
        return client.NetworkingV1Api()

    def _batch(self) -> client.BatchV1Api:
        return client.BatchV1Api()

    # ------------------------------------------------------------- primitives --

    async def _apply(self, manifest: dict[str, Any]) -> dict[str, Any]:
        """Server-side apply one manifest, keyed by kind."""
        return await asyncio.to_thread(self._apply_sync, manifest)

    def _apply_sync(self, manifest: dict[str, Any]) -> dict[str, Any]:
        ref = ResourceRef.from_manifest(manifest)
        kind = ref.kind
        ns = ref.namespace
        name = ref.name
        try:
            if kind == "Namespace":
                return _to_dict(
                    self._core().patch_namespace(
                        name=name, body=manifest,
                        field_manager=_FIELD_MANAGER, force=True,
                    )
                )
            if kind == "Deployment":
                return _to_dict(
                    self._apps().patch_namespaced_deployment(
                        name=name, namespace=ns, body=manifest,
                        field_manager=_FIELD_MANAGER, force=True,
                    )
                )
            if kind == "Service":
                return _to_dict(
                    self._core().patch_namespaced_service(
                        name=name, namespace=ns, body=manifest,
                        field_manager=_FIELD_MANAGER, force=True,
                    )
                )
            if kind == "Secret":
                return _to_dict(
                    self._core().patch_namespaced_secret(
                        name=name, namespace=ns, body=manifest,
                        field_manager=_FIELD_MANAGER, force=True,
                    )
                )
            if kind == "PersistentVolumeClaim":
                return _to_dict(
                    self._core().patch_namespaced_persistent_volume_claim(
                        name=name, namespace=ns, body=manifest,
                        field_manager=_FIELD_MANAGER, force=True,
                    )
                )
            if kind == "ResourceQuota":
                return _to_dict(
                    self._core().patch_namespaced_resource_quota(
                        name=name, namespace=ns, body=manifest,
                        field_manager=_FIELD_MANAGER, force=True,
                    )
                )
            if kind == "NetworkPolicy":
                return _to_dict(
                    self._networking().patch_namespaced_network_policy(
                        name=name, namespace=ns, body=manifest,
                        field_manager=_FIELD_MANAGER, force=True,
                    )
                )
            if kind == "Job":
                # Jobs are immutable in most spec fields; use create-with-fallback.
                return self._create_sync(manifest)
            if kind == "ServiceAccount":
                return _to_dict(
                    self._core().patch_namespaced_service_account(
                        name=name, namespace=ns, body=manifest,
                        field_manager=_FIELD_MANAGER, force=True,
                    )
                )
            if kind == "HTTPRoute":
                group, version = ref.api_version.split("/", 1)
                return self._custom().patch_namespaced_custom_object(
                    group=group, version=version, namespace=ns,
                    plural="httproutes", name=name, body=manifest,
                    field_manager=_FIELD_MANAGER, force=True,
                )
        except ApiException as exc:
            if exc.status == 404:
                return self._create_sync(manifest)
            raise
        # Unknown kinds fall through to a create attempt so callers get a real
        # error instead of a silent no-op.
        return self._create_sync(manifest)

    def _create_sync(self, manifest: dict[str, Any]) -> dict[str, Any]:
        ref = ResourceRef.from_manifest(manifest)
        kind, ns, name = ref.kind, ref.namespace, ref.name
        if kind == "Namespace":
            return _to_dict(self._core().create_namespace(body=manifest))
        if kind == "Deployment":
            return _to_dict(self._apps().create_namespaced_deployment(namespace=ns, body=manifest))
        if kind == "Service":
            return _to_dict(self._core().create_namespaced_service(namespace=ns, body=manifest))
        if kind == "Secret":
            return _to_dict(self._core().create_namespaced_secret(namespace=ns, body=manifest))
        if kind == "PersistentVolumeClaim":
            return _to_dict(
                self._core().create_namespaced_persistent_volume_claim(namespace=ns, body=manifest)
            )
        if kind == "ResourceQuota":
            return _to_dict(
                self._core().create_namespaced_resource_quota(namespace=ns, body=manifest)
            )
        if kind == "NetworkPolicy":
            return _to_dict(
                self._networking().create_namespaced_network_policy(namespace=ns, body=manifest)
            )
        if kind == "Job":
            return _to_dict(self._batch().create_namespaced_job(namespace=ns, body=manifest))
        if kind == "ServiceAccount":
            return _to_dict(
                self._core().create_namespaced_service_account(namespace=ns, body=manifest)
            )
        if kind == "HTTPRoute":
            group, version = ref.api_version.split("/", 1)
            return self._custom().create_namespaced_custom_object(
                group=group, version=version, namespace=ns,
                plural="httproutes", body=manifest,
            )
        raise ValueError(f"Unsupported kind for apply: {kind} (name={name})")

    # ---------------------------------------------------------- public API ----

    async def import_services(self, manifests_yaml: str, namespace: str) -> dict[str, Any]:
        """Parse a multi-doc YAML string and apply each doc."""
        docs = [d for d in yaml.safe_load_all(manifests_yaml) if d]
        results: list[dict[str, Any]] = []
        errors: list[str] = []
        for doc in docs:
            meta = doc.setdefault("metadata", {})
            # Namespace/cluster-scoped resources keep whatever they specified.
            if doc.get("kind") not in {"Namespace"} and not meta.get("namespace"):
                meta["namespace"] = namespace
            try:
                results.append(await self._apply(doc))
            except ApiException as exc:
                errors.append(f"{doc.get('kind')}/{meta.get('name')}: {exc.reason}")
        return {
            "ok": not errors,
            "namespace": namespace,
            "applied": len(results),
            "errors": errors,
            "stdout": "\n".join(
                f"{r.get('kind', '?')}/{(r.get('metadata') or {}).get('name', '?')} applied"
                for r in results
            ),
            "stderr": "\n".join(errors),
        }

    async def deploy(
        self,
        *,
        namespace: str,
        manifests: list[dict[str, Any]],
        demo_mode: bool = False,
    ) -> dict[str, Any]:
        if demo_mode:
            return {"simulated": True, "namespace": namespace, "applied": len(manifests)}
        yaml_blob = "\n---\n".join(yaml.safe_dump(m) for m in manifests)
        result = await self.import_services(yaml_blob, namespace)
        result["simulated"] = False
        return result

    async def trigger_redeploy(self, deployment_name: str, namespace: str) -> dict[str, Any]:
        # Bumping this annotation forces the ReplicaSet controller to roll pods
        # without changing the pod spec — same trick `kubectl rollout restart` uses.
        patch = {
            "spec": {
                "template": {
                    "metadata": {
                        "annotations": {
                            "kubectl.kubernetes.io/restartedAt": _now_rfc3339(),
                        }
                    }
                }
            }
        }
        try:
            await asyncio.to_thread(
                self._apps().patch_namespaced_deployment,
                name=deployment_name, namespace=namespace, body=patch,
            )
            return {"ok": True, "deployment": deployment_name, "namespace": namespace}
        except ApiException as exc:
            return {"ok": False, "error": exc.reason, "stderr": str(exc)}

    async def get_pipeline_status(
        self, namespace: str, deployment_name: str
    ) -> dict[str, Any]:
        try:
            dep = await asyncio.to_thread(
                self._apps().read_namespaced_deployment_status,
                name=deployment_name, namespace=namespace,
            )
        except ApiException as exc:
            if exc.status == 404:
                return {"state": "provisioning", "stage": DeploymentStage.PROVISIONING_DB}
            return {"state": "unknown", "stage": DeploymentStage.BUILDING, "error": exc.reason}

        status = dep.status or client.V1DeploymentStatus()
        spec_replicas = (dep.spec.replicas if dep.spec else 1) or 1
        ready = status.ready_replicas or 0
        conditions = list(status.conditions or [])

        if ready >= spec_replicas and spec_replicas > 0:
            return {
                "state": "available",
                "stage": DeploymentStage.COMPLETE,
                "ready": ready,
                "desired": spec_replicas,
            }
        for cond in conditions:
            if cond.type == "ReplicaFailure" and cond.status == "True":
                return {
                    "state": "replicafailure",
                    "stage": DeploymentStage.FAILED,
                    "reason": cond.reason,
                    "message": cond.message,
                }

        pod_stage = await self._infer_stage_from_pods(namespace, deployment_name)
        return {
            "state": "progressing",
            "stage": pod_stage or DeploymentStage.BUILDING,
            "ready": ready,
            "desired": spec_replicas,
        }

    async def _infer_stage_from_pods(
        self, namespace: str, deployment_name: str
    ) -> DeploymentStage | None:
        pods = await self._list_deployment_pods(namespace, deployment_name)
        for pod in pods:
            for cs in list((pod.status.container_statuses if pod.status else None) or []):
                waiting = cs.state.waiting if cs.state else None
                if waiting and waiting.reason:
                    reason = waiting.reason.lower()
                    if "imagepull" in reason:
                        return DeploymentStage.UPLOADING
                    if "creating" in reason:
                        return DeploymentStage.CREATING_RUNTIME
                    if "crash" in reason:
                        return DeploymentStage.FAILED
        return None

    async def get_service_urls(self, namespace: str) -> dict[str, str]:
        try:
            routes = await asyncio.to_thread(
                self._custom().list_namespaced_custom_object,
                group="gateway.networking.k8s.io",
                version="v1",
                namespace=namespace,
                plural="httproutes",
            )
        except ApiException:
            return {}

        urls: dict[str, str] = {}
        for item in routes.get("items", []) or []:
            meta = item.get("metadata", {}) or {}
            spec = item.get("spec", {}) or {}
            hostnames = spec.get("hostnames") or []
            if not hostnames:
                continue
            urls[meta.get("name", "")] = f"https://{hostnames[0]}"
        return urls

    async def fetch_logs(
        self, namespace: str, deployment_name: str, tail_lines: int = 200
    ) -> list[str]:
        pod = await self._newest_ready_pod(namespace, deployment_name)
        if pod is None:
            return []
        try:
            raw = await asyncio.to_thread(
                self._core().read_namespaced_pod_log,
                name=pod.metadata.name,
                namespace=namespace,
                tail_lines=tail_lines,
            )
        except ApiException:
            return []
        if not raw:
            return []
        return raw.splitlines()

    async def fetch_metrics(
        self, namespace: str, deployment_name: str
    ) -> list[dict[str, Any]]:
        try:
            data = await asyncio.to_thread(
                self._custom().list_namespaced_custom_object,
                group="metrics.k8s.io",
                version="v1beta1",
                namespace=namespace,
                plural="pods",
            )
        except ApiException:
            return []

        pods = await self._list_deployment_pods(namespace, deployment_name)
        pod_names = {p.metadata.name for p in pods}
        cpu_millis = 0
        memory_bytes = 0
        matched: list[dict[str, Any]] = []
        for item in data.get("items", []) or []:
            if (item.get("metadata") or {}).get("name") not in pod_names:
                continue
            matched.append(item)
            for c in item.get("containers", []) or []:
                usage = c.get("usage", {}) or {}
                cpu_millis += _parse_cpu(usage.get("cpu", "0"))
                memory_bytes += _parse_memory(usage.get("memory", "0"))
        return [
            {
                "cpu_millicores": cpu_millis,
                "memory_bytes": memory_bytes,
                "pod_count": len(matched),
                "raw": matched,
            }
        ]

    async def apply_env_changes(
        self,
        deployment_name: str,
        namespace: str,
        env_changes: dict[str, str],
    ) -> dict[str, Any]:
        if not env_changes:
            return {"ok": False, "error": "No environment changes to apply"}

        try:
            dep = await asyncio.to_thread(
                self._apps().read_namespaced_deployment,
                name=deployment_name, namespace=namespace,
            )
        except ApiException as exc:
            return {"ok": False, "error": exc.reason}

        containers = list((dep.spec.template.spec.containers if dep.spec else None) or [])
        patched_containers = []
        for c in containers:
            merged: dict[str, str] = {e.name: (e.value or "") for e in (c.env or [])}
            merged.update(env_changes)
            patched_containers.append(
                {
                    "name": c.name,
                    "env": [{"name": k, "value": v} for k, v in merged.items()],
                }
            )

        patch = {"spec": {"template": {"spec": {"containers": patched_containers}}}}
        try:
            await asyncio.to_thread(
                self._apps().patch_namespaced_deployment,
                name=deployment_name, namespace=namespace, body=patch,
            )
        except ApiException as exc:
            return {"ok": False, "error": exc.reason, "stderr": str(exc)}

        redeploy = await self.trigger_redeploy(deployment_name, namespace)
        return {
            "ok": redeploy.get("ok", False),
            "deployment": deployment_name,
            "namespace": namespace,
            "env_changes": env_changes,
            "redeploy": redeploy,
        }

    async def wait_for_pipeline(
        self,
        namespace: str,
        deployment_name: str,
        timeout: int = 300,
        poll_interval: float = 3.0,
    ) -> dict[str, Any]:
        deadline = time.monotonic() + timeout
        last: dict[str, Any] = {}
        while time.monotonic() < deadline:
            last = await self.get_pipeline_status(namespace, deployment_name)
            stage = last.get("stage")
            if stage == DeploymentStage.COMPLETE:
                return {"ok": True, "stage": stage, "state": last.get("state"), "raw": last}
            if stage == DeploymentStage.FAILED:
                return {"ok": False, "stage": stage, "state": last.get("state"), "raw": last}
            await asyncio.sleep(poll_interval)
        return {
            "ok": False,
            "error": f"Timed out after {timeout}s waiting for {deployment_name}",
            "stage": last.get("stage", DeploymentStage.BUILDING),
            "state": last.get("state"),
        }

    # -------------------------------------------------- K8s-only additions ---

    async def create_namespace(
        self, name: str, labels: dict[str, str] | None = None
    ) -> dict[str, Any]:
        ns = Namespace(name=name, labels=labels).to_dict()
        quota = ResourceQuota(name=f"{name}-quota", namespace=name).to_dict()
        deny = DefaultDenyNetworkPolicy(namespace=name).to_dict()

        errors: list[str] = []
        for manifest in (ns, quota, deny):
            try:
                await self._apply(manifest)
            except ApiException as exc:
                errors.append(f"{manifest['kind']}: {exc.reason}")
        return {"ok": not errors, "namespace": name, "errors": errors}

    async def delete_namespace(self, name: str) -> dict[str, Any]:
        try:
            await asyncio.to_thread(
                self._core().delete_namespace,
                name=name,
                body=client.V1DeleteOptions(propagation_policy="Foreground"),
            )
            return {"ok": True, "namespace": name}
        except ApiException as exc:
            if exc.status == 404:
                return {"ok": True, "namespace": name, "note": "already absent"}
            return {"ok": False, "error": exc.reason}

    async def stream_pod_events(
        self, namespace: str, timeout_seconds: int = 0
    ) -> AsyncIterator[dict[str, Any]]:
        async for event in stream_events(
            self._core(), namespace, timeout_seconds=timeout_seconds
        ):
            yield event

    # ------------------------------------------------------------- helpers ---

    async def _list_deployment_pods(self, namespace: str, deployment_name: str) -> list[Any]:
        selector = f"app.kubernetes.io/name={deployment_name}"
        try:
            pods = await asyncio.to_thread(
                self._core().list_namespaced_pod,
                namespace=namespace, label_selector=selector,
            )
        except ApiException:
            return []
        return list(pods.items or [])

    async def _newest_ready_pod(self, namespace: str, deployment_name: str) -> Any | None:
        pods = await self._list_deployment_pods(namespace, deployment_name)

        def _is_ready(pod: Any) -> bool:
            if classify_pod(pod):
                return False
            for cond in list((pod.status.conditions if pod.status else None) or []):
                if cond.type == "Ready" and cond.status == "True":
                    return True
            return False

        ready = [p for p in pods if _is_ready(p)]
        if not ready:
            ready = pods
        ready.sort(
            key=lambda p: getattr(p.metadata, "creation_timestamp", None) or 0,
            reverse=True,
        )
        return ready[0] if ready else None


# --------------------------------------------------------- private utilities --


def _now_rfc3339() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _to_dict(obj: Any) -> dict[str, Any]:
    """Best-effort convert a kubernetes model object into a plain dict."""
    if isinstance(obj, dict):
        return obj
    to_dict = getattr(obj, "to_dict", None)
    if callable(to_dict):
        return to_dict()
    return {"raw": repr(obj)}


def _parse_cpu(value: str) -> int:
    """Return CPU usage as integer millicores. Accepts ``"250m"`` or ``"1500000n"``."""
    if not value:
        return 0
    v = value.strip()
    try:
        if v.endswith("n"):
            return int(int(v[:-1]) / 1_000_000)
        if v.endswith("u"):
            return int(int(v[:-1]) / 1_000)
        if v.endswith("m"):
            return int(v[:-1])
        return int(float(v) * 1000)
    except ValueError:
        return 0


_MEM_UNITS = {
    "Ki": 1024,
    "Mi": 1024**2,
    "Gi": 1024**3,
    "Ti": 1024**4,
    "K": 1000,
    "M": 1000**2,
    "G": 1000**3,
    "T": 1000**4,
}


def _parse_memory(value: str) -> int:
    if not value:
        return 0
    v = value.strip()
    for suffix, mult in _MEM_UNITS.items():
        if v.endswith(suffix):
            try:
                return int(float(v[: -len(suffix)]) * mult)
            except ValueError:
                return 0
    try:
        return int(v)
    except ValueError:
        return 0
