"""K8s adapter — drop-in replacement for the retired service."""

from __future__ import annotations

from .client import KubernetesService
from .manifests import ResourceRef
from .slugs import hostnames_for_slug, repo_slug_from_url

__all__ = [
    "KubernetesService",
    "ResourceRef",
    "hostnames_for_slug",
    "repo_slug_from_url",
]
