from datetime import datetime, timedelta
from uuid import UUID

from app.config import Settings
from app.models.aiops import Diagnosis, Incident, IncidentSeverity, IncidentStatus, Remediation, RemediationStep
from app.models.deployment import DeploymentStage, DeploymentStatus
from app.models.observability import ObservabilitySnapshot, ServiceHealth, ServiceMetrics, TimelineEvent
from app.services.base import BaseService
from app.services.gemini import GeminiClient
from app.services.store import deployment_store, incident_store
from app.services.timeline import list_ops_timeline, record_ops_event
from app.services.zerops import ZeropsService, hostnames_for_slug


class ObservabilityService(BaseService):
    name = "observability"

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._zerops = ZeropsService(settings)

    async def get_snapshot(self, deployment_id: UUID) -> ObservabilitySnapshot:
        deployment = deployment_store.get(deployment_id)
        incidents = [
            i
            for i in incident_store.list_all()
            if i.deployment_id == deployment_id and i.status != IncidentStatus.RESOLVED
        ]
        has_open = bool(incidents)

        if deployment and deployment.demo_mode:
            return self._demo_snapshot(deployment_id, has_open, incidents)

        if deployment and deployment.service_hostnames:
            return await self._real_snapshot(deployment, incidents, has_open)

        return ObservabilitySnapshot(
            deployment_id=deployment_id,
            metrics=[],
            health=[],
            timeline=list_ops_timeline(deployment_id) if deployment else [],
            log_summary="No Zerops service hostnames yet — complete a live deploy first.",
            checked_at=datetime.utcnow(),
        )

    async def _real_snapshot(self, deployment, incidents, has_open) -> ObservabilitySnapshot:
        metrics: list[ServiceMetrics] = []
        health: list[ServiceHealth] = []
        log_lines: list[str] = []
        project_id = deployment.zerops_project_id

        role_map = {
            "frontend": deployment.service_hostnames.get("frontend", ""),
            "api": deployment.service_hostnames.get("api", ""),
            "database": deployment.service_hostnames.get("database", ""),
            "cache": deployment.service_hostnames.get("cache", ""),
            "search": deployment.service_hostnames.get("search", ""),
        }

        for role, hostname in role_map.items():
            if not hostname:
                continue

            role_logs: list[str] = []
            raw_metrics = await self._zerops.fetch_metrics(hostname, project_id=project_id)
            cpu, mem = self._parse_metrics(raw_metrics)
            if cpu is not None or mem is not None:
                metrics.append(
                    ServiceMetrics(
                        service=role,
                        cpu_percent=cpu if cpu is not None else 0.0,
                        memory_mb=mem if mem is not None else 0.0,
                    )
                )
            if role in ("frontend", "api"):
                role_logs = await self._zerops.fetch_logs(hostname, tail=50, project_id=project_id)
                log_lines.extend(role_logs)

            health.append(
                await self._probe_service_health(
                    role=role,
                    hostname=hostname,
                    project_id=project_id,
                    incidents=incidents,
                    logs=role_logs,
                    deployment_status=deployment.status,
                )
            )

        timeline = self._build_timeline(deployment.id, has_open, incidents, real=True)
        log_summary = await self._summarize_logs(log_lines, has_open, incidents)
        checked_at = datetime.utcnow()

        return ObservabilitySnapshot(
            deployment_id=deployment.id,
            metrics=metrics,
            health=health,
            timeline=timeline,
            log_summary=log_summary,
            checked_at=checked_at,
        )

    async def _probe_service_health(
        self,
        *,
        role: str,
        hostname: str,
        project_id: str | None,
        incidents: list,
        logs: list[str],
        deployment_status: DeploymentStatus,
    ) -> ServiceHealth:
        pipeline_state: str | None = None
        log_text = " ".join(logs).lower()
        error_signals = (
            "error",
            "exception",
            "failed",
            "traceback",
            "p1001",
            "cannot connect",
            "refused",
        )
        has_log_errors = any(token in log_text for token in error_signals)

        if role in ("frontend", "api"):
            pipe = await self._zerops.get_pipeline_status(hostname, project_id)
            stage = pipe.get("stage", DeploymentStage.BUILDING)
            pipeline_state = str(pipe.get("state", "unknown"))

            if stage == DeploymentStage.FAILED or pipeline_state == "failed":
                status, ready = "critical", False
            elif stage == DeploymentStage.COMPLETE and not has_log_errors:
                status, ready = "healthy", True
            elif stage == DeploymentStage.COMPLETE and has_log_errors:
                status, ready = "degraded", False
            elif stage in (
                DeploymentStage.BUILDING,
                DeploymentStage.INSTALLING,
                DeploymentStage.UPLOADING,
                DeploymentStage.CREATING_RUNTIME,
                DeploymentStage.PROVISIONING_DB,
                DeploymentStage.READINESS_CHECK,
            ):
                status, ready = "degraded", False
            else:
                status, ready = "unknown", False
        else:
            info = await self._zerops.get_service_info(hostname, project_id)
            pipeline_state = str(info.get("state", "unknown"))
            if not info.get("found"):
                status, ready = "unknown", False
            elif pipeline_state in ("failed", "error", "stopped"):
                status, ready = "critical", False
            else:
                status, ready = "healthy", True

        if deployment_status == DeploymentStatus.FAILED and role in ("frontend", "api"):
            status, ready = "critical", False

        for incident in incidents:
            affected = incident.affected_service or "api"
            if affected != role and not (affected == "api" and role == "api"):
                continue
            if status == "healthy" and has_log_errors:
                status, ready = "degraded", False
            elif status in ("healthy", "degraded", "unknown") and pipeline_state in (
                "failed",
                "unknown",
            ):
                status, ready = "critical", False
            elif status == "healthy" and deployment_status == DeploymentStatus.FAILED:
                status, ready = "critical", False

        return ServiceHealth(
            service=role,
            hostname=hostname,
            status=status,
            readiness_ok=ready,
            pipeline_state=pipeline_state,
            last_checked_at=datetime.utcnow(),
        )

    async def _summarize_logs(self, lines: list[str], has_open: bool, incidents) -> str:
        if not lines:
            if has_open and incidents and incidents[0].diagnosis:
                return incidents[0].diagnosis.log_summary or incidents[0].title
            return "No recent log lines from Zerops."
        tail = " ".join(lines[-5:])
        if len(tail) > 400:
            tail = tail[:400] + "..."
        return tail

    @staticmethod
    def _parse_metrics(raw: list[dict]) -> tuple[float | None, float | None]:
        if not raw:
            return None, None
        item = raw[0]
        cpu_raw = item.get("cpu") or item.get("cpuPercent") or item.get("cpu_percent")
        mem_raw = item.get("memory") or item.get("memoryMb") or item.get("memory_mb")
        cpu = float(cpu_raw) if cpu_raw is not None else None
        mem = float(mem_raw) if mem_raw is not None else None
        return cpu, mem

    def _demo_snapshot(self, deployment_id, has_open, incidents) -> ObservabilitySnapshot:
        service_defs = [
            ("frontend", 8.2, 192.0),
            ("api", 45.0 if has_open else 14.0, 384.0 if has_open else 256.0),
            ("database", 22.0 if has_open else 18.0, 512.0),
            ("cache", 5.0, 64.0),
            ("search", 10.0, 128.0),
        ]
        metrics = [
            ServiceMetrics(service=s, cpu_percent=cpu, memory_mb=mem)
            for s, cpu, mem in service_defs
        ]
        slug = "demo"
        names = hostnames_for_slug(slug)
        health: list[ServiceHealth] = []
        for service, _, _ in service_defs:
            if not has_open:
                status, ready = "healthy", True
            elif service == "api":
                status, ready = "critical", False
            elif service in ("database", "search"):
                status, ready = "degraded", False
            else:
                status, ready = "healthy", True
            health.append(
                ServiceHealth(
                    service=service,
                    hostname=names.get(service),
                    status=status,
                    readiness_ok=ready,
                    pipeline_state="simulated",
                    last_checked_at=datetime.utcnow(),
                )
            )
        timeline = self._build_timeline(deployment_id, has_open, incidents, real=False)
        log_summary = (
            "Migration failed: api cannot connect — DATABASE_URL missing from environment."
            if has_open
            else "All services healthy. Readiness checks passing. No errors in recent logs."
        )
        return ObservabilitySnapshot(
            deployment_id=deployment_id,
            metrics=metrics,
            health=health,
            timeline=timeline,
            log_summary=log_summary,
            checked_at=datetime.utcnow(),
        )

    def _build_timeline(self, deployment_id: UUID, has_open: bool, incidents: list, *, real: bool) -> list[TimelineEvent]:
        persisted = list_ops_timeline(deployment_id)
        if persisted:
            return persisted

        # Live path: never invent timeline events — only persisted ops events.
        if real:
            return []

        now = datetime.utcnow()
        events = [
            TimelineEvent(
                deployment_id=deployment_id,
                source="deploy",
                event_type="import_started",
                message="Build pipeline initialized",
                service="platform",
                occurred_at=now - timedelta(minutes=8),
            ),
        ]
        if has_open:
            events.append(
                TimelineEvent(
                    deployment_id=deployment_id,
                    source="runtime",
                    event_type="error",
                    message=incidents[0].title if incidents else "Deployment failure detected",
                    service=incidents[0].affected_service if incidents else "api",
                    occurred_at=now - timedelta(minutes=2),
                )
            )
        else:
            events.append(
                TimelineEvent(
                    deployment_id=deployment_id,
                    source="readiness",
                    event_type="check_passed",
                    message="Services provisioned — enable public routing if URLs return 502",
                    service="api",
                    occurred_at=now - timedelta(minutes=1),
                )
            )
        return events

    async def append_event(self, event: TimelineEvent) -> TimelineEvent:
        return event


class AIOpsService(BaseService):
    name = "aiops"

    DEMO_DIAGNOSIS = Diagnosis(
        root_cause="Prisma migration failed",
        reason="DATABASE_URL environment variable is missing",
        impact="Backend cannot connect to PostgreSQL — API readiness check fails",
        confidence=0.96,
        suggested_fix="Set DATABASE_URL in Zerops api service environment variables",
        log_summary="Error: P1001 — Can't reach database server at postgres:5432",
    )

    DEMO_RUNBOOK = [
        "Open Zerops project → api service → Environment variables",
        "Add DATABASE_URL referencing the postgres service (${postgres_hostname})",
        "Redeploy the api service and wait for readiness check to pass",
    ]

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._zerops = ZeropsService(settings)
        self._gemini = GeminiClient(settings)

    async def create_incident(
        self,
        deployment_id: UUID,
        title: str,
        *,
        demo_mode: bool = False,
        affected_service: str = "api",
        repo_slug: str | None = None,
    ) -> Incident:
        slug = repo_slug or "demo"
        postgres_host = f"{slug}-postgres"
        incident = Incident(
            deployment_id=deployment_id,
            title=title,
            severity=IncidentSeverity.CRITICAL,
            affected_service=affected_service,
        )
        if demo_mode:
            incident.diagnosis = self.DEMO_DIAGNOSIS
            incident.runbook = self.DEMO_RUNBOOK
            incident.status = IncidentStatus.DIAGNOSED
            incident.suggested_remediation = Remediation(
                description="Add DATABASE_URL to api service env",
                env_changes={
                    "DATABASE_URL": f"postgresql://${{{postgres_host}_hostname}}/deplot",
                },
                yaml_diff=f"+ envSecrets:\n+   DATABASE_URL: postgresql://${{{postgres_host}_hostname}}/deplot",
            )
        incident_store.save(incident)
        record_ops_event(
            deployment_id,
            source="runtime",
            event_type="incident",
            message=title,
            service=affected_service,
        )
        return incident

    async def create_incident_from_failure(
        self,
        deployment_id: UUID,
        *,
        title: str,
        logs: list[str],
        stack_summary: str,
        yaml_excerpt: str,
        affected_service: str = "api",
    ) -> Incident:
        incident = Incident(
            deployment_id=deployment_id,
            title=title,
            severity=IncidentSeverity.CRITICAL,
            affected_service=affected_service,
        )
        report = await self._gemini.analyze_logs(
            logs=logs,
            stack_summary=stack_summary,
            yaml_excerpt=yaml_excerpt,
        )
        if report:
            incident.diagnosis = Diagnosis(
                root_cause=report.get("root_cause", title),
                reason=report.get("reason", "See logs"),
                impact=report.get("impact", "Service unavailable"),
                confidence=float(report.get("confidence", 0.7)),
                suggested_fix=report.get("suggested_fix", "Review logs and redeploy"),
                log_summary=report.get("log_summary"),
            )
            incident.runbook = report.get("runbook") or []
            env_changes = report.get("env_changes") or {}
            incident.suggested_remediation = Remediation(
                description=report.get("suggested_fix", "Apply suggested environment changes"),
                env_changes=env_changes if isinstance(env_changes, dict) else {},
                yaml_diff=report.get("yaml_diff"),
            )
        else:
            incident.diagnosis = Diagnosis(
                root_cause=title,
                reason="Zerops import or pipeline failed",
                impact="Target services may not be running",
                confidence=0.75,
                suggested_fix="Check Zerops GUI pipeline logs and enable public routing",
                log_summary="\n".join(logs[-3:]) if logs else None,
            )
            incident.runbook = [
                "Open Zerops project and inspect pipeline for failed service",
                "Enable subdomain access on web and api routing pages",
                "Redeploy after fixing build or env configuration",
            ]
        incident.status = IncidentStatus.DIAGNOSED
        incident_store.save(incident)
        record_ops_event(
            deployment_id,
            source="runtime",
            event_type="incident",
            message=title,
            service=affected_service,
        )
        return incident

    async def list_incidents(self, deployment_id: UUID) -> list[Incident]:
        return [i for i in incident_store.list_all() if i.deployment_id == deployment_id]

    async def get_incident(self, incident_id: UUID) -> Incident | None:
        return incident_store.get(incident_id)

    async def diagnose(self, incident, report=None):
        if report:
            incident.diagnosis = report.diagnosis
            incident.runbook = report.runbook
            incident.suggested_remediation = report.remediation
        incident.status = IncidentStatus.DIAGNOSED
        incident_store.save(incident)
        return incident

    async def start_remediation(self, incident_id: UUID) -> Incident | None:
        incident = incident_store.get(incident_id)
        if not incident:
            return None
        incident.status = IncidentStatus.REMEDIATING
        incident.remediation_error = None
        incident.remediation_steps = []
        incident_store.save(incident)
        return incident

    def _append_step(self, incident: Incident, name: str, status: str, message: str | None = None) -> None:
        incident.remediation_steps.append(RemediationStep(name=name, status=status, message=message))
        incident_store.save(incident)

    def _resolve_env_for_zerops(self, env_changes: dict[str, str], deployment) -> dict[str, str]:
        slug = deployment.repo_slug or "app"
        hostnames = deployment.service_hostnames or hostnames_for_slug(slug)
        postgres = hostnames.get("database", f"{slug}-postgres")
        cache = hostnames.get("cache", f"{slug}-cache")
        search = hostnames.get("search", f"{slug}-search")

        resolved: dict[str, str] = {}
        for key, raw in env_changes.items():
            value = raw
            upper = key.upper()
            if upper == "DATABASE_URL" and (
                "user:pass" in value or "@postgres" in value or "postgres:5432" in value
            ):
                value = f"postgresql://${{{postgres}_hostname}}/deplot"
            elif upper == "REDIS_URL" and "cache" not in value:
                value = f"redis://${{{cache}_hostname}}:6379"
            elif upper.startswith("TYPESENSE_") and "search" not in value and upper == "TYPESENSE_HOST":
                value = f"${{{search}_hostname}}"
            resolved[key] = value
        return resolved

    async def execute_remediation(self, incident_id: UUID) -> Incident | None:
        from app.models.deployment import DeploymentStage, DeploymentStatus

        incident = incident_store.get(incident_id)
        if not incident:
            return None

        deployment = deployment_store.get(incident.deployment_id)
        if not deployment:
            incident.remediation_error = "Deployment not found"
            incident_store.save(incident)
            return incident

        await self.start_remediation(incident_id)
        record_ops_event(
            incident.deployment_id,
            source="aiops",
            event_type="remediation_started",
            message=f"Self-heal started for incident: {incident.title}",
            service=incident.affected_service,
        )
        remediation = incident.suggested_remediation

        if deployment.demo_mode:
            self._append_step(incident, "Apply env patch", "running", "Simulated env update")
            self._append_step(
                incident,
                "Apply env patch",
                "succeeded",
                f"Applied {len(remediation.env_changes)} variable(s)" if remediation else "DATABASE_URL set",
            )
            self._append_step(incident, "Redeploy api", "running")
            self._append_step(incident, "Redeploy api", "succeeded", "Simulated redeploy")
            self._append_step(incident, "Readiness check", "running")
            self._append_step(incident, "Readiness check", "succeeded", "All probes passing")

            deployment.status = DeploymentStatus.SUCCEEDED
            deployment.stage = DeploymentStage.COMPLETE
            deployment.pipeline_state = "healed"
            deployment_store.save(deployment)
            resolved = await self.resolve(incident_id)
            if resolved:
                record_ops_event(
                    incident.deployment_id,
                    source="aiops",
                    event_type="remediation_succeeded",
                    message="Self-heal complete — services healthy",
                    service=incident.affected_service,
                )
            return resolved

        if not remediation or not remediation.env_changes:
            incident.remediation_error = "No environment changes suggested for this incident"
            incident.status = IncidentStatus.DIAGNOSED
            incident_store.save(incident)
            return incident

        slug = deployment.repo_slug or "app"
        affected = incident.affected_service or "api"
        hostname = deployment.service_hostnames.get(affected) or f"{slug}-{affected}"
        project_id = deployment.zerops_project_id
        env_changes = self._resolve_env_for_zerops(remediation.env_changes, deployment)

        self._append_step(
            incident,
            "Apply env patch",
            "running",
            f"Patching {len(env_changes)} variable(s) on {hostname}",
        )
        apply_result = await self._zerops.apply_env_changes(
            hostname,
            env_changes,
            project_id,
            trigger_redeploy=True,
        )
        if not apply_result.get("ok"):
            self._append_step(
                incident,
                "Apply env patch",
                "failed",
                apply_result.get("error") or apply_result.get("stderr") or "Import failed",
            )
            incident.remediation_error = apply_result.get("error") or "Failed to apply environment changes"
            incident.status = IncidentStatus.DIAGNOSED
            incident_store.save(incident)
            record_ops_event(
                incident.deployment_id,
                source="aiops",
                event_type="remediation_failed",
                message=incident.remediation_error,
                service=incident.affected_service,
            )
            return incident

        self._append_step(
            incident,
            "Apply env patch",
            "succeeded",
            ", ".join(f"{k}={v[:40]}..." if len(v) > 40 else f"{k}={v}" for k, v in env_changes.items()),
        )
        self._append_step(incident, "Redeploy api", "running", f"Waiting for {hostname} pipeline")

        wait_result = await self._zerops.wait_for_pipeline(hostname, project_id)
        if wait_result.get("ok"):
            self._append_step(incident, "Redeploy api", "succeeded", str(wait_result.get("state", "ready")))
            self._append_step(incident, "Readiness check", "succeeded", "Pipeline complete")

            deployment.status = DeploymentStatus.SUCCEEDED
            deployment.stage = DeploymentStage.COMPLETE
            deployment.pipeline_state = "healed"
            deployment_store.save(deployment)
            resolved = await self.resolve(incident_id)
            if resolved:
                record_ops_event(
                    incident.deployment_id,
                    source="aiops",
                    event_type="remediation_succeeded",
                    message="Env patched on Zerops, redeployed, readiness passing",
                    service=incident.affected_service,
                )
            return resolved

        self._append_step(
            incident,
            "Redeploy api",
            "failed",
            wait_result.get("error") or str(wait_result.get("state", "failed")),
        )
        incident.remediation_error = wait_result.get("error") or "Service did not become healthy after redeploy"
        incident.status = IncidentStatus.DIAGNOSED
        deployment.status = DeploymentStatus.FAILED
        deployment.stage = wait_result.get("stage", DeploymentStage.FAILED)
        deployment.pipeline_state = str(wait_result.get("state", "failed"))
        deployment_store.save(deployment)
        incident_store.save(incident)
        record_ops_event(
            incident.deployment_id,
            source="aiops",
            event_type="remediation_failed",
            message=incident.remediation_error,
            service=incident.affected_service,
        )
        return incident

    async def resolve(self, incident_id: UUID) -> Incident | None:
        incident = incident_store.get(incident_id)
        if not incident:
            return None
        incident.status = IncidentStatus.RESOLVED
        incident.resolved_at = datetime.utcnow()
        incident_store.save(incident)
        return incident

    async def resolve_all_for_deployment(self, deployment_id: UUID) -> int:
        count = 0
        for incident in await self.list_incidents(deployment_id):
            if incident.status != IncidentStatus.RESOLVED:
                await self.resolve(incident.id)
                count += 1
        return count
