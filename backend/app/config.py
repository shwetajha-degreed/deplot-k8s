from functools import lru_cache
from pathlib import Path

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# Repo root: monorepo parent locally, /var/www when prompts/ is co-deployed on Zerops
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

    # Zerops GUI forbids custom env keys starting with ZEROPS_ — use DEPLOT_* /
    # PLATFORM_* / DEPLOY_* there. Local .env may still use ZEROPS_*.
    zerops_api_token: str = Field(
        default="",
        validation_alias=AliasChoices("DEPLOT_API_TOKEN", "ZEROPS_API_TOKEN", "zerops_api_token"),
    )
    zerops_project_id: str = Field(
        default="",
        validation_alias=AliasChoices(
            "PLATFORM_PROJECT_ID", "ZEROPS_PROJECT_ID", "zerops_project_id"
        ),
    )
    zerops_deploy_project_id: str = Field(
        default="",
        validation_alias=AliasChoices(
            "DEPLOY_PROJECT_ID", "ZEROPS_DEPLOY_PROJECT_ID", "zerops_deploy_project_id"
        ),
    )
    zerops_api_base: str = "https://api.app-prg1.zerops.io/api/rest/public"
    zcli_path: str = ""
    search_heavy_stack: bool = True
    zerops_project_core: str = Field(
        default="lightweight",
        validation_alias=AliasChoices(
            "DEPLOT_PROJECT_CORE", "ZEROPS_PROJECT_CORE", "zerops_project_core"
        ),
        description="lightweight (free) or serious ($10/mo) — Zerops project core tier for cost estimates",
    )

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

    @property
    def zerops_target_project_id(self) -> str:
        """Project used for wizard deploys (customer/showcase repos)."""
        return self.zerops_deploy_project_id or self.zerops_project_id

    @property
    def deploy_project_isolated(self) -> bool:
        """True when deploy sandbox is a separate project from the Deplot platform."""
        return bool(
            self.zerops_deploy_project_id
            and self.zerops_project_id
            and self.zerops_deploy_project_id != self.zerops_project_id
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()
