"""Computed deployment readiness score from validation, health, and incidents."""

from __future__ import annotations

from uuid import UUID

from app.config import Settings
from app.models.aiops import IncidentStatus
from app.models.deployment import DeploymentScore, DeploymentStatus
from app.models.observability import ObservabilitySnapshot
from app.services.base import BaseService
from app.services.gemini import GeminiClient
from app.services.operations import AIOpsService, ObservabilityService
from app.services.store import deployment_store, incident_store, session_store


def _clamp(value: float) -> float:
    return round(max(0.0, min(10.0, value)), 1)


class DeploymentScoreService(BaseService):
    name = "scoring"

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._observability = ObservabilityService(settings)
        self._aiops = AIOpsService(settings)
        self._gemini = GeminiClient(settings)

    async def compute(self, deployment_id: UUID) -> DeploymentScore:
        deployment = deployment_store.get(deployment_id)
        if not deployment:
            return DeploymentScore(recommendations=["Deployment not found"])

        session = session_store.get(deployment.session_id)
        stack = session.stack if session else None

        validation = None
        if stack:
            from app.bootstrap import get_service

            yaml_svc = get_service("yaml_generator")
            config = yaml_svc.generate(stack, session.repo_url if session else None)
            validation = yaml_svc.validate(stack, config)

        observability = await self._observability.get_snapshot(deployment_id)
        incidents = await self._aiops.list_incidents(deployment_id)
        all_incidents = [
            i for i in incident_store.list_all() if i.deployment_id == deployment_id
        ]

        open_incidents = [i for i in incidents if i.status != IncidentStatus.RESOLVED]
        resolved_incidents = [i for i in all_incidents if i.status == IncidentStatus.RESOLVED]

        security = self._score_security(deployment, validation)
        performance = self._score_performance(deployment, observability, open_incidents)
        scalability = self._score_scalability(deployment, stack)
        reliability = self._score_reliability(
            deployment, observability, open_incidents, resolved_incidents
        )
        observability_score = self._score_observability(deployment, observability, open_incidents)

        recommendations = self._build_recommendations(
            deployment,
            validation,
            observability,
            open_incidents,
            resolved_incidents,
        )

        if self._gemini.enabled:
            enhanced = await self._gemini.enhance_score_recommendations(
                security=security,
                performance=performance,
                scalability=scalability,
                reliability=reliability,
                observability=observability_score,
                gaps=recommendations[:8],
                stack_summary=self._stack_summary(stack),
            )
            if enhanced:
                recommendations = self._merge_recommendations(recommendations, enhanced)

        return DeploymentScore(
            security=security,
            performance=performance,
            scalability=scalability,
            reliability=reliability,
            observability=observability_score,
            recommendations=recommendations[:10],
        )

    @staticmethod
    def _stack_summary(stack) -> str:
        if not stack:
            return "unknown"
        parts = [
            f"framework={stack.framework}",
            f"db={stack.database}",
            f"cache={stack.cache}",
            f"search={stack.search}",
        ]
        return ", ".join(p for p in parts if p.split("=")[-1] not in ("None", ""))

    def _score_security(self, deployment, validation) -> float:
        score = 9.0
        if validation:
            errors = sum(1 for i in validation.issues if i.severity == "error")
            warnings = sum(1 for i in validation.issues if i.severity == "warning")
            score -= errors * 1.0
            score -= warnings * 0.35
        if deployment.config:
            import_yaml = deployment.config.import_yaml
            if "envSecrets" not in import_yaml and "postgresql" in import_yaml.lower():
                score -= 0.4
            if "readinessCheck" in import_yaml or "readiness" in import_yaml:
                score += 0.3
        return _clamp(score)

    def _score_performance(
        self, deployment, observability: ObservabilitySnapshot, open_incidents
    ) -> float:
        score = 8.5
        api_health = next((h for h in observability.health if h.service == "api"), None)
        api_metrics = next((m for m in observability.metrics if m.service == "api"), None)

        if api_health:
            if api_health.status == "critical":
                score -= 2.0
            elif api_health.status == "degraded":
                score -= 1.0
            elif api_health.status == "healthy" and api_health.readiness_ok:
                score += 0.5

        if api_metrics:
            if api_metrics.cpu_percent > 70:
                score -= 1.0
            elif api_metrics.cpu_percent > 50:
                score -= 0.5
            elif api_metrics.cpu_percent < 25:
                score += 0.3

        if open_incidents:
            score -= min(1.5, len(open_incidents) * 0.6)

        if deployment.status == DeploymentStatus.FAILED:
            score -= 1.0

        return _clamp(score)

    def _score_scalability(self, deployment, stack) -> float:
        score = 7.5
        service_count = len(deployment.config.services) if deployment.config else 0
        if deployment.plan:
            service_count = max(service_count, len(deployment.plan.services))

        score += min(2.0, service_count * 0.35)
        if service_count >= 5:
            score += 0.5
        elif service_count <= 2:
            score -= 0.5

        if stack and stack.cache and stack.search:
            score += 0.4

        return _clamp(score)

    def _score_reliability(
        self,
        deployment,
        observability: ObservabilitySnapshot,
        open_incidents,
        resolved_incidents,
    ) -> float:
        score = 8.0

        if deployment.status == DeploymentStatus.FAILED:
            score -= 2.5
        elif deployment.status == DeploymentStatus.IN_PROGRESS:
            score -= 0.4

        if open_incidents:
            score -= min(2.5, len(open_incidents) * 1.2)

        for h in observability.health:
            if h.status == "critical":
                score -= 0.6
            elif h.status == "degraded":
                score -= 0.3
            elif h.status == "unknown":
                score -= 0.15

        healthy = all(h.status == "healthy" for h in observability.health if h.service)
        if healthy and deployment.status == DeploymentStatus.SUCCEEDED:
            score += 1.2

        if resolved_incidents and not open_incidents:
            score += 0.8

        runtime_ready = [
            h for h in observability.health if h.service in ("api", "frontend") and h.readiness_ok
        ]
        if len(runtime_ready) >= 2:
            score += 0.4

        return _clamp(score)

    def _score_observability(
        self,
        deployment,
        observability: ObservabilitySnapshot,
        open_incidents,
    ) -> float:
        score = 7.5

        if observability.checked_at:
            score += 0.3
        if observability.metrics:
            score += 0.4
        if observability.log_summary and len(observability.log_summary) > 20:
            score += 0.3
        if observability.timeline:
            score += 0.2

        if deployment.service_urls:
            score += 0.8
        elif deployment.routing_checklist and not deployment.demo_mode:
            score -= 0.6

        unknown = sum(1 for h in observability.health if h.status == "unknown")
        score -= unknown * 0.25

        if open_incidents:
            score -= min(1.0, len(open_incidents) * 0.4)

        if healthy_count := sum(1 for h in observability.health if h.status == "healthy"):
            if healthy_count >= 4:
                score += 0.5

        return _clamp(score)

    def _build_recommendations(
        self,
        deployment,
        validation,
        observability: ObservabilitySnapshot,
        open_incidents,
        resolved_incidents,
    ) -> list[str]:
        recs: list[str] = []

        if validation:
            for issue in validation.issues:
                if issue.severity in ("error", "warning"):
                    recs.append(issue.message)

        for item in deployment.routing_checklist or []:
            if not deployment.service_urls:
                recs.append(item)

        for inc in open_incidents:
            if inc.diagnosis and inc.diagnosis.suggested_fix:
                recs.append(inc.diagnosis.suggested_fix)
            else:
                recs.append(f"Resolve incident: {inc.title}")

        for h in observability.health:
            if h.status == "critical":
                recs.append(f"Critical: {h.service} ({h.hostname or 'service'}) — check Zerops pipeline")
            elif h.status == "degraded":
                recs.append(f"Degraded: {h.service} — review logs and readiness probes")
            elif h.status == "unknown" and h.hostname:
                recs.append(f"Confirm {h.hostname} finished provisioning in Zerops")

        if deployment.status != DeploymentStatus.SUCCEEDED and not open_incidents:
            recs.append("Wait for deployment pipeline to complete before production traffic")

        if resolved_incidents and not open_incidents:
            recs.append("Post-remediation: re-run score after next deploy to confirm stability")

        if not recs:
            recs.append("Production readiness looks good — enable autoscaling before high traffic")
            recs.append("Schedule periodic log review and readiness probe checks")

        seen: set[str] = set()
        unique: list[str] = []
        for r in recs:
            key = r.strip().lower()
            if key not in seen:
                seen.add(key)
                unique.append(r.strip())
        return unique

    @staticmethod
    def _merge_recommendations(base: list[str], extra: list[str]) -> list[str]:
        seen = {b.strip().lower() for b in base}
        merged = list(base)
        for item in extra:
            key = item.strip().lower()
            if key and key not in seen:
                seen.add(key)
                merged.append(item.strip())
        return merged
