from functools import lru_cache
from pathlib import Path

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# Repo root: monorepo parent locally, /var/www when prompts/ is co-deployed
_backend_root = Path(__file__).resolve().parents[1]
if (_backend_root / "prompts").exists():
    REPO_ROOT = _backend_root
elif (_backend_root.parent / "prompts").exists():
    REPO_ROOT = _backend_root.parent
else:
    REPO_ROOT = _backend_root.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(".env", str(REPO_ROOT / ".env")),
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )

    app_name: str = "Deplot AI"
    app_version: str = "0.1.0"
    debug: bool = False
    api_prefix: str = "/api/v1"

    cors_origins: str = "http://localhost:3000,http://127.0.0.1:3000"

    database_url: str = "postgresql+asyncpg://deplot:deplot@localhost:5432/deplot"
    redis_url: str = "redis://localhost:6379/0"

    gemini_api_key: str = ""
    gemini_model: str = "gemini-2.0-flash"
    github_token: str = ""

    # Azure / AKS target platform
    aks_cluster_name: str = Field(
        default="DGCUSUSSBXAKS01",
        validation_alias=AliasChoices("AKS_CLUSTER_NAME", "aks_cluster_name"),
    )
    acr_registry: str = Field(
        default="dgscucorecr01.azurecr.io",
        validation_alias=AliasChoices("ACR_REGISTRY", "acr_registry"),
    )
    azure_workload_identity_client_id: str = Field(
        default="",
        validation_alias=AliasChoices(
            "AZURE_WORKLOAD_IDENTITY_CLIENT_ID", "azure_workload_identity_client_id"
        ),
    )
    build_namespace: str = "deplot-builds"
    gateway_namespace: str = "internal-gateway"
    gateway_name: str = "internal-gateway"
    # Actual listener name on the shared internal-gateway:
    # https-degreed-com serves *.internal.sbx.degreed.com
    # https-degreed-app serves *.internal.sbx.degreed.app
    gateway_section_name: str = "https-degreed-com"
    base_domain: str = Field(
        default="internal.sbx.degreed.com",
        validation_alias=AliasChoices("BASE_DOMAIN", "base_domain"),
    )
    deplot_namespace: str = "deplot-system"
    kubeconfig_path: str = Field(
        default="",
        description="Path to kubeconfig for local dev. Empty = try in-cluster config first.",
    )
    search_heavy_stack: bool = True

    prompts_dir: Path = REPO_ROOT / "prompts"
    templates_dir: Path = REPO_ROOT / "templates"

    demo_mode_enabled: bool = True
    ai_agents_enabled: bool = True
    observability_poll_interval_seconds: int = 30
    remediation_timeout_seconds: int = 180
    remediation_poll_interval_seconds: int = 5

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    def hostname_for(self, app_slug: str, namespace: str) -> str:
        return f"{app_slug}-{namespace}.{self.base_domain}"


@lru_cache
def get_settings() -> Settings:
    return Settings()
