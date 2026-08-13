from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, Field, HttpUrl, field_validator


class SessionStatus(StrEnum):
    PENDING = "pending"
    ANALYZING = "analyzing"
    READY = "ready"
    FAILED = "failed"


class StackDetection(BaseModel):
    language: str | None = None
    framework: str | None = None
    runtime: str | None = None
    package_manager: str | None = None
    database: str | None = None
    cache: str | None = None
    search: str | None = None
    has_frontend: bool = False
    has_backend: bool = False
    has_workers: bool = False
    backend_framework: str | None = None
    backend_runtime: str | None = None
    monorepo_frontend_path: str | None = None
    monorepo_backend_path: str | None = None
    repo_slug: str | None = None
    detected_env_vars: list[str] = Field(default_factory=list)
    confidence: float = 0.0
    raw_signals: dict[str, Any] = Field(default_factory=dict)
    analysis_summary: str | None = None


class ArchitectureNode(BaseModel):
    id: str
    label: str
    type: str  # frontend | api | database | cache | worker | storage
    technology: str | None = None
    hostname: str | None = None
    health: str = "unknown"  # healthy | degraded | critical | unknown


class ArchitectureEdge(BaseModel):
    source: str
    target: str
    label: str | None = None


class ArchitectureGraph(BaseModel):
    nodes: list[ArchitectureNode] = Field(default_factory=list)
    edges: list[ArchitectureEdge] = Field(default_factory=list)


class ValidationIssue(BaseModel):
    severity: str  # error | warning | info
    code: str
    message: str
    field: str | None = None


class ValidationReport(BaseModel):
    passed: bool
    issues: list[ValidationIssue] = Field(default_factory=list)


class AnalyzeRequest(BaseModel):
    repo_url: HttpUrl | None = None
    demo_mode: bool = False

    @field_validator("repo_url", mode="before")
    @classmethod
    def clean_repo_url(cls, value: object) -> object:
        if value is None:
            return value
        text = str(value).strip().rstrip(".,;")
        return text or None


class AnalyzeResponse(BaseModel):
    session_id: UUID
    status: SessionStatus
    stack: StackDetection | None = None


class AnalysisSession(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    repo_url: str | None = None
    status: SessionStatus = SessionStatus.PENDING
    stack: StackDetection | None = None
    architecture: ArchitectureGraph | None = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
