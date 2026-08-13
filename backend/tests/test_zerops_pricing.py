"""Unit tests for Zerops pricing estimates."""

from app.models.analysis import ArchitectureGraph, ArchitectureNode
from app.services.zerops_pricing import (
    build_deployment_plan,
    estimate_service_monthly,
    project_core_cost,
    service_resources_for_type,
)


def test_service_resources_match_zerops_recipe_baselines() -> None:
    db = service_resources_for_type("database")
    assert db.cpu_cores == 1.0
    assert db.ram_gb == 1.25
    assert db.disk_gb == 1.0

    cache = service_resources_for_type("cache")
    assert cache.ram_gb == 0.56


def test_estimate_service_monthly_uses_published_rates() -> None:
    # 1 shared CPU + 1 GB RAM + 1 GB disk = 0.60 + 3.00 + 0.10
    resources = service_resources_for_type("api")
    assert estimate_service_monthly(resources) == 2.20


def test_fullstack_plan_cost_lightweight_core() -> None:
    nodes = [
        ArchitectureNode(id="frontend", label="Frontend", type="frontend"),
        ArchitectureNode(id="api", label="API", type="api"),
        ArchitectureNode(id="database", label="Database", type="database"),
        ArchitectureNode(id="cache", label="Cache", type="cache"),
        ArchitectureNode(id="search", label="Search", type="search"),
    ]
    graph = ArchitectureGraph(nodes=nodes, edges=[])
    plan = build_deployment_plan(graph.nodes, project_core="lightweight")

    assert len(plan.services) == 5
    assert plan.project_core_usd_month == 0.0
    assert plan.pricing_source == "zerops_official_rates"
    # 1.45 + 2.20 + 4.45 + 2.38 + 2.20 = 12.68
    assert plan.estimated_cost_usd_month == 12.68
    assert all(s.estimated_cost_usd_month > 0 for s in plan.services)


def test_fullstack_plan_cost_serious_core() -> None:
    nodes = [
        ArchitectureNode(id="frontend", label="Frontend", type="frontend"),
        ArchitectureNode(id="api", label="API", type="api"),
        ArchitectureNode(id="database", label="Database", type="database"),
    ]
    graph = ArchitectureGraph(nodes=nodes, edges=[])
    plan = build_deployment_plan(graph.nodes, project_core="serious")

    assert project_core_cost("serious") == 10.0
    assert plan.project_core_usd_month == 10.0
    assert plan.estimated_cost_usd_month > 10.0
