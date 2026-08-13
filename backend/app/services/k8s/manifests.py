"""Dataclasses that build the K8s object dicts used by :class:`KubernetesService`.

Every dataclass exposes ``to_dict()`` returning a mapping ready to feed to the
``kubernetes`` client (server-side apply expects plain dict/JSON payloads).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


ResourceDict = dict[str, Any]


@dataclass(frozen=True)
class ResourceRef:
    api_version: str
    kind: str
    name: str
    namespace: str | None = None

    @classmethod
    def from_manifest(cls, manifest: ResourceDict) -> "ResourceRef":
        meta = manifest.get("metadata") or {}
        return cls(
            api_version=str(manifest.get("apiVersion", "")),
            kind=str(manifest.get("kind", "")),
            name=str(meta.get("name", "")),
            namespace=meta.get("namespace"),
        )


def _labels(name: str, extra: dict[str, str] | None = None) -> dict[str, str]:
    base = {"app.kubernetes.io/name": name, "app.kubernetes.io/managed-by": "deplot"}
    if extra:
        base.update(extra)
    return base


@dataclass
class Namespace:
    name: str
    labels: dict[str, str] | None = None

    def to_dict(self) -> ResourceDict:
        return {
            "apiVersion": "v1",
            "kind": "Namespace",
            "metadata": {
                "name": self.name,
                "labels": _labels(self.name, self.labels),
            },
        }


@dataclass
class ResourceQuota:
    name: str
    namespace: str
    cpu: str = "4"
    memory: str = "4Gi"
    storage: str = "20Gi"

    def to_dict(self) -> ResourceDict:
        return {
            "apiVersion": "v1",
            "kind": "ResourceQuota",
            "metadata": {"name": self.name, "namespace": self.namespace},
            "spec": {
                "hard": {
                    "requests.cpu": self.cpu,
                    "requests.memory": self.memory,
                    "limits.cpu": self.cpu,
                    "limits.memory": self.memory,
                    "requests.storage": self.storage,
                },
            },
        }


@dataclass
class ContainerLimitRange:
    """Auto-fills requests/limits for containers that don't declare them.

    Required when the cluster has admission webhooks (Datadog, service mesh
    sidecars, etc.) that inject containers without resource specs into user
    pods — a strict ResourceQuota otherwise rejects the whole pod.
    """

    namespace: str
    name: str = "default-limits"
    default_cpu: str = "500m"
    default_memory: str = "512Mi"
    default_request_cpu: str = "100m"
    default_request_memory: str = "128Mi"

    def to_dict(self) -> ResourceDict:
        return {
            "apiVersion": "v1",
            "kind": "LimitRange",
            "metadata": {"name": self.name, "namespace": self.namespace},
            "spec": {
                "limits": [
                    {
                        "type": "Container",
                        "default": {
                            "cpu": self.default_cpu,
                            "memory": self.default_memory,
                        },
                        "defaultRequest": {
                            "cpu": self.default_request_cpu,
                            "memory": self.default_request_memory,
                        },
                    }
                ]
            },
        }


@dataclass
class DefaultDenyNetworkPolicy:
    """Default-deny ingress, allow-all egress.

    Egress is intentionally open: Kaniko needs to pull base images from
    Docker Hub / gcr.io / ACR and git needs to reach the source repo;
    apps need outbound DNS + HTTP(S) at minimum. Locking egress down
    per-workload is a future exercise (e.g. FQDN policies via Cilium).
    """

    namespace: str
    name: str = "default-deny-ingress"

    def to_dict(self) -> ResourceDict:
        return {
            "apiVersion": "networking.k8s.io/v1",
            "kind": "NetworkPolicy",
            "metadata": {"name": self.name, "namespace": self.namespace},
            "spec": {
                "podSelector": {},
                "policyTypes": ["Ingress", "Egress"],
                "egress": [{}],
            },
        }


@dataclass
class Secret:
    name: str
    namespace: str
    string_data: dict[str, str] = field(default_factory=dict)
    secret_type: str = "Opaque"

    def to_dict(self) -> ResourceDict:
        return {
            "apiVersion": "v1",
            "kind": "Secret",
            "type": self.secret_type,
            "metadata": {"name": self.name, "namespace": self.namespace},
            "stringData": dict(self.string_data),
        }


@dataclass
class PersistentVolumeClaim:
    name: str
    namespace: str
    storage: str = "1Gi"
    storage_class: str | None = None
    access_modes: tuple[str, ...] = ("ReadWriteOnce",)

    def to_dict(self) -> ResourceDict:
        spec: ResourceDict = {
            "accessModes": list(self.access_modes),
            "resources": {"requests": {"storage": self.storage}},
        }
        if self.storage_class:
            spec["storageClassName"] = self.storage_class
        return {
            "apiVersion": "v1",
            "kind": "PersistentVolumeClaim",
            "metadata": {"name": self.name, "namespace": self.namespace},
            "spec": spec,
        }


@dataclass
class ContainerPort:
    container_port: int
    name: str | None = None
    protocol: str = "TCP"

    def to_dict(self) -> ResourceDict:
        d: ResourceDict = {"containerPort": self.container_port, "protocol": self.protocol}
        if self.name:
            d["name"] = self.name
        return d


@dataclass
class Deployment:
    name: str
    namespace: str
    image: str
    replicas: int = 1
    ports: list[ContainerPort] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)
    env_from_secret: str | None = None
    service_account: str | None = None
    cpu_request: str = "50m"
    memory_request: str = "64Mi"
    cpu_limit: str = "500m"
    memory_limit: str = "512Mi"
    labels: dict[str, str] | None = None

    def to_dict(self) -> ResourceDict:
        selector_labels = _labels(self.name, self.labels)
        container: ResourceDict = {
            "name": self.name,
            "image": self.image,
            "ports": [p.to_dict() for p in self.ports],
            "env": [{"name": k, "value": v} for k, v in self.env.items()],
            "resources": {
                "requests": {"cpu": self.cpu_request, "memory": self.memory_request},
                "limits": {"cpu": self.cpu_limit, "memory": self.memory_limit},
            },
        }
        if self.env_from_secret:
            container["envFrom"] = [{"secretRef": {"name": self.env_from_secret}}]

        pod_spec: ResourceDict = {"containers": [container]}
        if self.service_account:
            pod_spec["serviceAccountName"] = self.service_account

        return {
            "apiVersion": "apps/v1",
            "kind": "Deployment",
            "metadata": {
                "name": self.name,
                "namespace": self.namespace,
                "labels": selector_labels,
            },
            "spec": {
                "replicas": self.replicas,
                "selector": {"matchLabels": selector_labels},
                "template": {
                    "metadata": {"labels": selector_labels},
                    "spec": pod_spec,
                },
            },
        }


@dataclass
class ServicePort:
    port: int
    target_port: int | str
    name: str | None = None
    protocol: str = "TCP"

    def to_dict(self) -> ResourceDict:
        d: ResourceDict = {
            "port": self.port,
            "targetPort": self.target_port,
            "protocol": self.protocol,
        }
        if self.name:
            d["name"] = self.name
        return d


@dataclass
class Service:
    name: str
    namespace: str
    ports: list[ServicePort]
    selector_name: str | None = None
    service_type: str = "ClusterIP"

    def to_dict(self) -> ResourceDict:
        selector = _labels(self.selector_name or self.name)
        return {
            "apiVersion": "v1",
            "kind": "Service",
            "metadata": {"name": self.name, "namespace": self.namespace},
            "spec": {
                "type": self.service_type,
                "selector": selector,
                "ports": [p.to_dict() for p in self.ports],
            },
        }


@dataclass
class HTTPRoute:
    """Gateway API HTTPRoute wired to the shared internal gateway.

    TLS is intentionally absent — the parent Gateway terminates HTTPS.
    """

    name: str
    namespace: str
    hostname: str
    service_name: str
    service_port: int
    gateway_name: str = "internal-gateway"
    gateway_namespace: str = "internal-gateway"
    # TODO: confirm the actual listener section name on the shared gateway.
    section_name: str | None = "https-degreed-com"
    path_prefix: str = "/"

    def to_dict(self) -> ResourceDict:
        parent_ref: ResourceDict = {
            "name": self.gateway_name,
            "namespace": self.gateway_namespace,
        }
        if self.section_name:
            parent_ref["sectionName"] = self.section_name
        return {
            "apiVersion": "gateway.networking.k8s.io/v1",
            "kind": "HTTPRoute",
            "metadata": {"name": self.name, "namespace": self.namespace},
            "spec": {
                "parentRefs": [parent_ref],
                "hostnames": [self.hostname],
                "rules": [
                    {
                        "matches": [{"path": {"type": "PathPrefix", "value": self.path_prefix}}],
                        "backendRefs": [
                            {"name": self.service_name, "port": self.service_port},
                        ],
                    }
                ],
            },
        }
