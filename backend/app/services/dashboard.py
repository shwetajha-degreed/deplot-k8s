from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone

from app.config import get_settings
from app.models.aiops import IncidentSeverity, IncidentStatus
from app.models.dashboard import DashboardSummary, LiveApp, RecentActivity
from app.models.deployment import DeploymentStatus
from app.services.base import BaseService
from app.services.store import deployment_store, incident_store, session_store


def _relative_time(dt: datetime | None) -> str | None:
    if not dt:
        return None
    now = datetime.now(timezone.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    delta = now - dt
    seconds = int(delta.total_seconds())
    if seconds < 60:
        return "just now"
    if seconds < 3600:
        return f"{seconds // 60}m ago"
    if seconds < 86400:
        return f"{seconds // 3600}h ago"
    return f"{seconds // 86400}d ago"


def _empty_summary() -> DashboardSummary:
    """Honest empty state — never invent acme/demo KPIs."""
    return DashboardSummary(is_demo_baseline=False)


class DashboardService(BaseService):
    name = "dashboard"

    def build_summary(self) -> DashboardSummary:
        sessions = session_store.list_all()
        deployments = deployment_store.list_all()
        incidents = incident_store.list_all()

        if not sessions and not deployments and not incidents:
            return _empty_summary()

        repo_urls = {s.repo_url for s in sessions if s.repo_url}
        connected_repos = len(repo_urls)

        total = len(deployments)
        active = sum(1 for d in deployments if d.status == DeploymentStatus.IN_PROGRESS)
        succeeded = sum(1 for d in deployments if d.status == DeploymentStatus.SUCCEEDED)
        success_rate = round((succeeded / total) * 100, 1) if total else 0.0

        project_ids = {d.zerops_project_id for d in deployments if d.zerops_project_id}
        settings = get_settings()
        if settings.zerops_project_id:
            project_ids.add(settings.zerops_project_id)
        if settings.zerops_deploy_project_id:
            project_ids.add(settings.zerops_deploy_project_id)
        environments = len(project_ids)

        service_names: set[str] = set()
        for d in deployments:
            if d.service_hostnames:
                service_names.update(v for v in d.service_hostnames.values() if v)
            elif d.config and d.config.services:
                service_names.update(d.config.services)
        zerops_services = len(service_names)

        healthy_count = sum(
            1
            for d in deployments
            if d.status == DeploymentStatus.SUCCEEDED and d.stage.value == "complete"
        )
        services_total = zerops_services
        services_healthy_count = min(healthy_count, services_total) if services_total else 0

        open_incidents = sum(1 for i in incidents if i.status != IncidentStatus.RESOLVED)
        critical_incidents = sum(
            1
            for i in incidents
            if i.severity == IncidentSeverity.CRITICAL and i.status != IncidentStatus.RESOLVED
        )

        scores = [d.score for d in deployments if d.score]
        if scores:
            dims = ["security", "performance", "scalability", "reliability", "observability"]
            avg_scores = [
                sum(getattr(s, dim) for s in scores) / len(scores) for dim in dims
            ]
            deployment_readiness_score = round(sum(avg_scores) / len(avg_scores), 1)
        else:
            deployment_readiness_score = 0.0

        plans = [d.plan for d in deployments if d.plan]
        estimated_monthly_cost_usd = (
            round(sum(p.estimated_cost_usd_month for p in plans), 2) if plans else 0.0
        )

        build_times = [p.estimated_build_minutes for p in plans if p.estimated_build_minutes]
        avg_build_time = round(sum(build_times) / len(build_times), 1) if build_times else 0.0

        live_apps: list[LiveApp] = []
        for d in sorted(deployments, key=lambda x: x.updated_at, reverse=True):
            if not d.live_url:
                continue
            name = d.repo_slug or f"deploy-{str(d.id)[:8]}"
            env = "sandbox" if (
                d.zerops_project_id
                and settings.zerops_deploy_project_id
                and d.zerops_project_id == settings.zerops_deploy_project_id
            ) else "platform"
            live_apps.append(LiveApp(name=name, url=d.live_url, environment=env))

        last_deploy = max((d.updated_at for d in deployments), default=None)
        last_deploy_relative = _relative_time(last_deploy)

        resolved = [i for i in incidents if i.resolved_at and i.detected_at]
        if resolved:
            mttr = sum((i.resolved_at - i.detected_at).total_seconds() for i in resolved) / len(
                resolved
            )
            mttr_minutes = round(mttr / 60, 1)
        else:
            mttr_minutes = 0.0

        frameworks = [
            s.stack.framework for s in sessions if s.stack and s.stack.framework
        ]
        stack_mix = dict(Counter(frameworks))
        top_framework = max(stack_mix, key=stack_mix.get) if stack_mix else None

        recent_activity: list[RecentActivity] = []
        for s in sorted(sessions, key=lambda x: x.updated_at, reverse=True)[:3]:
            if s.repo_url:
                recent_activity.append(
                    RecentActivity(
                        id=str(s.id),
                        message=f"Repository analyzed: {s.repo_url}",
                        occurred_at=s.updated_at,
                        category="analyze",
                    )
                )
        for d in sorted(deployments, key=lambda x: x.updated_at, reverse=True)[:5]:
            slug = d.repo_slug or str(d.id)[:8]
            recent_activity.append(
                RecentActivity(
                    id=str(d.id),
                    message=f"Deploy {d.status.value} ({slug}) — stage {d.stage.value}",
                    occurred_at=d.updated_at,
                    category="deploy",
                )
            )
        for i in sorted(incidents, key=lambda x: x.detected_at, reverse=True)[:3]:
            recent_activity.append(
                RecentActivity(
                    id=str(i.id),
                    message=i.title,
                    occurred_at=i.detected_at,
                    category="incident",
                )
            )
        recent_activity.sort(key=lambda x: x.occurred_at, reverse=True)
        recent_activity = recent_activity[:8]

        return DashboardSummary(
            connected_repos=connected_repos,
            total_deployments=total,
            active_deployments=active,
            success_rate_percent=success_rate,
            environments=environments,
            zerops_services=zerops_services,
            services_healthy=f"{services_healthy_count}/{services_total}",
            services_healthy_count=services_healthy_count,
            services_total=services_total,
            open_incidents=open_incidents,
            critical_incidents=critical_incidents,
            deployment_readiness_score=deployment_readiness_score,
            estimated_monthly_cost_usd=estimated_monthly_cost_usd,
            avg_build_time_minutes=avg_build_time,
            live_apps=live_apps,
            last_deploy_at=last_deploy,
            last_deploy_relative=last_deploy_relative,
            mttr_minutes=mttr_minutes,
            top_framework=top_framework,
            stack_mix=stack_mix,
            recent_activity=recent_activity,
            is_demo_baseline=False,
        )
