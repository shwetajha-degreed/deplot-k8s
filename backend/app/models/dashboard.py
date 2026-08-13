from datetime import datetime

from pydantic import BaseModel, Field


class LiveApp(BaseModel):
    name: str
    url: str
    environment: str = "production"


class RecentActivity(BaseModel):
    id: str
    message: str
    occurred_at: datetime
    category: str  # deploy | incident | analyze | score


class DashboardSummary(BaseModel):
    connected_repos: int = 0
    total_deployments: int = 0
    active_deployments: int = 0
    success_rate_percent: float = 0.0
    environments: int = 0
    k8s_services: int = 0
    services_healthy: str = "0/0"
    services_healthy_count: int = 0
    services_total: int = 0
    open_incidents: int = 0
    critical_incidents: int = 0
    deployment_readiness_score: float = 0.0
    estimated_monthly_cost_usd: float = 0.0
    avg_build_time_minutes: float = 0.0
    live_apps: list[LiveApp] = Field(default_factory=list)
    last_deploy_at: datetime | None = None
    last_deploy_relative: str | None = None
    mttr_minutes: float = 0.0
    top_framework: str | None = None
    stack_mix: dict[str, int] = Field(default_factory=dict)
    recent_activity: list[RecentActivity] = Field(default_factory=list)
    is_demo_baseline: bool = False
