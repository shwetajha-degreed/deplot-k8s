from datetime import datetime
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


class TimelineEvent(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    deployment_id: UUID
    source: str  # deploy | build | runtime | readiness | metric
    event_type: str
    message: str
    service: str | None = None
    occurred_at: datetime = Field(default_factory=datetime.utcnow)
    metadata: dict = Field(default_factory=dict)


class ServiceMetrics(BaseModel):
    service: str
    cpu_percent: float = 0.0
    memory_mb: float = 0.0
    disk_mb: float = 0.0


class ServiceHealth(BaseModel):
    service: str
    hostname: str | None = None
    status: str = "unknown"  # healthy | degraded | critical | unknown
    readiness_ok: bool = False
    pipeline_state: str | None = None
    last_checked_at: datetime | None = None


class ObservabilitySnapshot(BaseModel):
    deployment_id: UUID
    metrics: list[ServiceMetrics] = Field(default_factory=list)
    health: list[ServiceHealth] = Field(default_factory=list)
    timeline: list[TimelineEvent] = Field(default_factory=list)
    log_summary: str | None = None
    checked_at: datetime | None = None
