from datetime import datetime
from enum import StrEnum
from uuid import UUID, uuid4

from pydantic import BaseModel, Field

from app.models.observability import TimelineEvent


class IncidentSeverity(StrEnum):
    CRITICAL = "critical"
    WARNING = "warning"
    INFO = "info"


class IncidentStatus(StrEnum):
    OPEN = "open"
    DIAGNOSED = "diagnosed"
    REMEDIATING = "remediating"
    RESOLVED = "resolved"


class Diagnosis(BaseModel):
    root_cause: str
    reason: str
    impact: str
    confidence: float = Field(ge=0.0, le=1.0)
    suggested_fix: str
    log_summary: str | None = None


class Remediation(BaseModel):
    description: str
    env_changes: dict[str, str] = Field(default_factory=dict)
    yaml_diff: str | None = None
    import_yaml_diff: str | None = None


class RemediationStep(BaseModel):
    name: str
    status: str  # pending | running | succeeded | failed
    message: str | None = None


class Incident(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    deployment_id: UUID
    severity: IncidentSeverity = IncidentSeverity.CRITICAL
    status: IncidentStatus = IncidentStatus.OPEN
    title: str
    affected_service: str | None = None
    correlated_events: list[TimelineEvent] = Field(default_factory=list)
    diagnosis: Diagnosis | None = None
    runbook: list[str] = Field(default_factory=list)
    suggested_remediation: Remediation | None = None
    remediation_steps: list[RemediationStep] = Field(default_factory=list)
    remediation_error: str | None = None
    detected_at: datetime = Field(default_factory=datetime.utcnow)
    resolved_at: datetime | None = None


class AIOpsReport(BaseModel):
    diagnosis: Diagnosis
    runbook: list[str] = Field(default_factory=list)
    remediation: Remediation | None = None
    observability_gaps: list[str] = Field(default_factory=list)
