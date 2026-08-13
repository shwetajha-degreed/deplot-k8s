"""Register all services and import agents for side-effect registration."""

from app.config import Settings, get_settings
from app.core.registry import service_registry
from app.services.build.kaniko import KanikoBuildService
from app.services.deps.postgres import PostgresProvisioner
from app.services.deps.redis import RedisProvisioner
from app.services.domain import AnalysisService, PlannerService, YamlGeneratorService
from app.services.gemini import GeminiClient
from app.services.github import GitHubService
from app.services.dashboard import DashboardService
from app.services.k8s import KubernetesService
from app.services.operations import AIOpsService, ObservabilityService
from app.services.scoring import DeploymentScoreService
from app.services.store import init_stores


def bootstrap(settings: Settings | None = None) -> None:
    settings = settings or get_settings()

    if service_registry.keys():
        return

    init_stores(settings.database_url)

    gemini = GeminiClient(settings)
    service_registry.register("gemini", gemini)
    service_registry.register("github", GitHubService(settings))
    service_registry.register("analysis", AnalysisService())
    service_registry.register("planner", PlannerService())
    service_registry.register(
        "yaml_generator",
        YamlGeneratorService(
            prompts_dir=settings.prompts_dir,
            gemini=gemini,
            registry_prefix=settings.acr_registry,
            gateway_ns=settings.gateway_namespace,
            gateway_name=settings.gateway_name,
            base_domain=settings.base_domain,
        ),
    )
    k8s = KubernetesService(settings)
    service_registry.register("kubernetes", k8s)
    service_registry.register("kaniko_build", KanikoBuildService(settings, k8s))
    service_registry.register("deps_postgres", PostgresProvisioner(k8s))
    service_registry.register("deps_redis", RedisProvisioner(k8s))
    service_registry.register("observability", ObservabilityService(settings))
    service_registry.register("aiops", AIOpsService(settings))
    service_registry.register("scoring", DeploymentScoreService(settings))
    service_registry.register("dashboard", DashboardService())

    import app.agents.implementations  # noqa: F401


def get_service(name: str):
    return service_registry.get(name)
