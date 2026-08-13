"""Register all services and import agents for side-effect registration."""

from app.config import Settings, get_settings
from app.core.registry import service_registry
from app.services.domain import AnalysisService, PlannerService, YamlGeneratorService
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

    service_registry.register("github", GitHubService(settings))
    service_registry.register("analysis", AnalysisService())
    service_registry.register("planner", PlannerService())
    service_registry.register(
        "yaml_generator",
        YamlGeneratorService(settings.templates_dir, search_heavy=settings.search_heavy_stack),
    )
    service_registry.register("kubernetes", KubernetesService(settings))
    service_registry.register("observability", ObservabilityService(settings))
    service_registry.register("aiops", AIOpsService(settings))
    service_registry.register("scoring", DeploymentScoreService(settings))
    service_registry.register("dashboard", DashboardService())

    import app.agents.implementations  # noqa: F401


def get_service(name: str):
    return service_registry.get(name)
