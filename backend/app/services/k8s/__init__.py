"""K8s adapter — drop-in replacement for the retired ``ZeropsService``."""

from __future__ import annotations

from .client import KubernetesService
from .manifests import ResourceRef

__all__ = ["KubernetesService", "ResourceRef"]
