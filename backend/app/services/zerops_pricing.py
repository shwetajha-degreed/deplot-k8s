"""Zerops monthly cost estimation using official published resource rates.

Zerops does not expose a pricing-calculator REST endpoint; billing APIs cover
account credits and invoices. Estimates here mirror docs.zerops.io/company/pricing
and baseline NON_HA resource footprints from Zerops recipe stacks.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from app.models.deployment import DeploymentPlan, DeploymentPlanService


class ZeropsProjectCore(StrEnum):
    LIGHTWEIGHT = "lightweight"
    SERIOUS = "serious"


# Published 30-day rates — https://docs.zerops.io/company/pricing
SHARED_CPU_USD_PER_CORE_MONTH = 0.60
DEDICATED_CPU_USD_PER_CORE_MONTH = 6.00
RAM_USD_PER_025GB_MONTH = 0.75
DISK_USD_PER_05GB_MONTH = 0.05
PROJECT_CORE_USD_MONTH = {
    ZeropsProjectCore.LIGHTWEIGHT: 0.0,
    ZeropsProjectCore.SERIOUS: 10.0,
}

# Baseline footprints for NON_HA services (shared CPU) aligned with Zerops recipes.
_SERVICE_BASELINES: dict[str, tuple[float, float, float]] = {
    "frontend": (1.0, 0.25, 1.0),
    "api": (1.0, 0.50, 1.0),
    "database": (1.0, 1.25, 1.0),
    "cache": (1.0, 0.56, 1.0),
    "search": (1.0, 0.50, 1.0),
}
_DEFAULT_BASELINE = (1.0, 0.50, 1.0)


@dataclass(frozen=True)
class ServiceResources:
    cpu_cores: float
    ram_gb: float
    disk_gb: float
    cpu_mode: str = "shared"


def service_resources_for_type(service_type: str) -> ServiceResources:
    cpu, ram, disk = _SERVICE_BASELINES.get(service_type, _DEFAULT_BASELINE)
    return ServiceResources(cpu_cores=cpu, ram_gb=ram, disk_gb=disk)


def estimate_service_monthly(resources: ServiceResources) -> float:
    cpu_rate = (
        DEDICATED_CPU_USD_PER_CORE_MONTH
        if resources.cpu_mode == "dedicated"
        else SHARED_CPU_USD_PER_CORE_MONTH
    )
    cpu_cost = resources.cpu_cores * cpu_rate
    ram_cost = (resources.ram_gb / 0.25) * RAM_USD_PER_025GB_MONTH
    disk_cost = (resources.disk_gb / 0.5) * DISK_USD_PER_05GB_MONTH
    return round(cpu_cost + ram_cost + disk_cost, 2)


def project_core_cost(project_core: str | ZeropsProjectCore) -> float:
    try:
        core = ZeropsProjectCore(str(project_core).lower())
    except ValueError:
        core = ZeropsProjectCore.LIGHTWEIGHT
    return PROJECT_CORE_USD_MONTH[core]


def build_deployment_plan(
    graph_nodes: list,
    *,
    project_core: str = ZeropsProjectCore.LIGHTWEIGHT,
) -> DeploymentPlan:
    """Build a plan with per-service Zerops resource baselines and cost roll-up."""
    services: list[DeploymentPlanService] = []
    for node in graph_nodes:
        resources = service_resources_for_type(node.type)
        services.append(
            DeploymentPlanService(
                name=node.id,
                type=node.type,
                estimated_cpu=resources.cpu_cores,
                estimated_ram_gb=resources.ram_gb,
                estimated_disk_gb=resources.disk_gb,
                cpu_mode=resources.cpu_mode,
                estimated_cost_usd_month=estimate_service_monthly(resources),
            )
        )

    core_cost = project_core_cost(project_core)
    services_total = round(sum(s.estimated_cost_usd_month for s in services), 2)
    total = round(services_total + core_cost, 2)
    build_services = sum(1 for s in services if s.type in ("frontend", "api"))

    return DeploymentPlan(
        services=services,
        estimated_cost_usd_month=total,
        estimated_build_minutes=max(5, build_services * 5 + len(services)),
        project_core_usd_month=core_cost,
        pricing_source="zerops_official_rates",
        pricing_note=(
            "Baseline NON_HA shared-CPU resources using Zerops published rates "
            "(CPU, RAM, disk). Actual spend varies with autoscaling and usage."
        ),
    )
