from app.agents.base import AgentContext, BaseAgent
from app.agents.orchestrator import register_agent
from app.models.aiops import AIOpsReport, Diagnosis, Remediation
from app.models.analysis import ArchitectureGraph, StackDetection, ValidationReport
from app.models.deployment import DeploymentPlan, DeploymentScore, ZeropsConfig
from app.services.domain import AnalysisService, PlannerService, YamlGeneratorService
from app.services.gemini import GeminiClient
@register_agent
class RepositoryAnalyzerAgent(BaseAgent[StackDetection]):
    name = "repository_analyzer"
    prompt_file = "repository_analyzer.md"

    async def run(self, context: AgentContext) -> StackDetection:
        files = context.payload.get("files", {})
        service = AnalysisService()
        stack = service.detect_stack(files)
        gemini = GeminiClient(self._settings)
        if gemini.enabled:
            stack = await service.enrich_with_llm(stack, files, gemini)
        return stack


@register_agent
class InfrastructurePlannerAgent(BaseAgent[ArchitectureGraph]):
    name = "infrastructure_planner"
    prompt_file = "infrastructure_planner.md"

    async def run(self, context: AgentContext) -> ArchitectureGraph:
        stack: StackDetection = context.payload["stack"]
        service = AnalysisService()
        return service.build_architecture(stack)


@register_agent
class YamlGeneratorAgent(BaseAgent[ZeropsConfig]):
    name = "yaml_generator"
    prompt_file = "yaml_generator.md"

    async def run(self, context: AgentContext) -> ZeropsConfig:
        stack: StackDetection = context.payload["stack"]
        repo_url = context.payload.get("repo_url")
        service = YamlGeneratorService(self._settings.templates_dir, self._settings.search_heavy_stack)
        return service.generate(stack, repo_url)


@register_agent
class DeploymentValidatorAgent(BaseAgent[ValidationReport]):
    name = "deployment_validator"
    prompt_file = "deployment_validator.md"

    async def run(self, context: AgentContext) -> ValidationReport:
        stack: StackDetection = context.payload["stack"]
        config: ZeropsConfig = context.payload["config"]
        service = YamlGeneratorService(self._settings.templates_dir, self._settings.search_heavy_stack)
        return service.validate(stack, config)


@register_agent
class AIOpsAnalystAgent(BaseAgent[AIOpsReport]):
    name = "aiops_analyst"
    prompt_file = "aiops_analyst.md"

    async def run(self, context: AgentContext) -> AIOpsReport:
        logs = context.payload.get("logs") or []
        stack_summary = context.payload.get("stack_summary", "")
        yaml_excerpt = context.payload.get("yaml_excerpt", "")

        gemini = GeminiClient(self._settings)
        report = await gemini.analyze_logs(
            logs=logs,
            stack_summary=stack_summary,
            yaml_excerpt=yaml_excerpt,
        )
        if report:
            return AIOpsReport(
                diagnosis=Diagnosis(
                    root_cause=report.get("root_cause", "Deployment failure"),
                    reason=report.get("reason", ""),
                    impact=report.get("impact", ""),
                    confidence=float(report.get("confidence", 0.8)),
                    suggested_fix=report.get("suggested_fix", ""),
                    log_summary=report.get("log_summary"),
                ),
                runbook=report.get("runbook") or [],
                remediation=Remediation(
                    description=report.get("suggested_fix", "Apply fix"),
                    env_changes=report.get("env_changes") or {},
                    yaml_diff=report.get("yaml_diff"),
                ),
                observability_gaps=report.get("observability_gaps") or [],
            )

        # Demo diagnosis is only for scripted Demo Mode (create_incident). Live path stays honest.
        return AIOpsReport(
            diagnosis=Diagnosis(
                root_cause="AI diagnosis unavailable",
                reason="Gemini did not return a structured report (quota, network, or empty response)",
                impact="Manual inspection of Zerops logs is required before applying a fix",
                confidence=0.0,
                suggested_fix="Open Zerops GUI → failed service → Logs, then retry Diagnose",
                log_summary=("\n".join(logs[-3:]) if logs else "No logs available"),
            ),
            runbook=[
                "Open the deploy sandbox project in Zerops GUI",
                "Inspect pipeline and runtime logs for the failing service",
                "Retry Diagnose once Gemini quota is available",
            ],
            remediation=Remediation(
                description="Inspect Zerops logs and apply the suggested env or config fix manually",
                env_changes={},
            ),
            observability_gaps=["Enable readiness checks on all runtime services"],
        )


@register_agent
class OptimizationAdvisorAgent(BaseAgent[DeploymentScore]):
    name = "optimization_advisor"
    prompt_file = "optimization_advisor.md"

    async def run(self, context: AgentContext) -> DeploymentScore:
        from uuid import UUID

        from app.bootstrap import get_service

        deployment_id = context.payload.get("deployment_id")
        if deployment_id:
            scoring = get_service("scoring")
            return await scoring.compute(UUID(str(deployment_id)))

        return DeploymentScore(
            security=5.0,
            performance=5.0,
            scalability=5.0,
            reliability=5.0,
            observability=5.0,
            recommendations=["No deployment context — run analyze and deploy first"],
        )
