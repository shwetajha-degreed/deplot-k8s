from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, Field, computed_field


class DeploymentStage(StrEnum):
    QUEUED = "queued"
    BUILDING = "building"
    INSTALLING = "installing"
    UPLOADING = "uploading"
    CREATING_RUNTIME = "creating_runtime"
    PROVISIONING_DB = "provisioning_db"
    READINESS_CHECK = "readiness_check"
    COMPLETE = "complete"
    FAILED = "failed"


class DeploymentStatus(StrEnum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class K8sConfig(BaseModel):
    manifests: list[dict[str, Any]] = Field(default_factory=list)
    namespace: str = ""
    services: list[str] = Field(default_factory=list)


class DeploymentPlanService(BaseModel):
    name: str
    type: str
    estimated_ram_gb: float = 0.5
    estimated_cpu: float = 1.0
    estimated_disk_gb: float = 1.0
    cpu_mode: str = "shared"
    estimated_cost_usd_month: float = 0.0


class DeploymentPlan(BaseModel):
    services: list[DeploymentPlanService] = Field(default_factory=list)
    estimated_cost_usd_month: float = 0.0
    estimated_build_minutes: int = 5
    project_core_usd_month: float = 0.0
    pricing_source: str = "k8s_estimate"
    pricing_note: str | None = None


class DeploymentScore(BaseModel):
    security: float = 0.0
    performance: float = 0.0
    scalability: float = 0.0
    reliability: float = 0.0
    observability: float = 0.0
    recommendations: list[str] = Field(default_factory=list)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def overall(self) -> float:
        return round(
            (
                self.security
                + self.performance
                + self.scalability
                + self.reliability
                + self.observability
            )
            / 5,
            1,
        )


class DeploymentStatusResponse(BaseModel):
    deployment_id: UUID
    status: DeploymentStatus
    stage: DeploymentStage
    live_url: str | None = None
    service_urls: dict[str, str] = Field(default_factory=dict)
    service_hostnames: dict[str, str] = Field(default_factory=dict)
    routing_checklist: list[str] = Field(default_factory=list)
    pipeline_state: str | None = None
    message: str | None = None
    demo_mode: bool = False
    failure_phase: str | None = None
    failure_summary: str | None = None
    retry_from: str | None = None
    deploy_ui_stage_index: int | None = None


class Deployment(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    session_id: UUID
    namespace: str | None = None
    live_url: str | None = None
    demo_mode: bool = False
    repo_slug: str | None = None
    service_hostnames: dict[str, str] = Field(default_factory=dict)
    service_urls: dict[str, str] = Field(default_factory=dict)
    routing_checklist: list[str] = Field(default_factory=list)
    pipeline_state: str | None = None
    k8s_message: str | None = None
    failure_phase: str | None = None
    failure_summary: str | None = None
    stage: DeploymentStage = DeploymentStage.QUEUED
    status: DeploymentStatus = DeploymentStatus.PENDING
    plan: DeploymentPlan | None = None
    config: K8sConfig | None = None
    score: DeploymentScore | None = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    heal_status: str | None = None
    heal_history: list[dict] = Field(default_factory=list)


class DeployRequest(BaseModel):
    session_id: UUID
    demo_mode: bool = False


class DeployResponse(BaseModel):
    deployment_id: UUID
    status: DeploymentStatus
    stage: DeploymentStage


class RetryDeployRequest(BaseModel):
    from_phase: str = "pipeline"  # import | pipeline
