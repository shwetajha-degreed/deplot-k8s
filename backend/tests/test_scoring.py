"""Unit tests for computed deployment score."""

from uuid import uuid4

from app.models.deployment import Deployment, DeploymentStatus, DeploymentStage
from app.models.observability import ObservabilitySnapshot, ServiceHealth, ServiceMetrics
from app.services.scoring import DeploymentScoreService, _clamp
from app.config import get_settings


def test_clamp_bounds() -> None:
    assert _clamp(11.0) == 10.0
    assert _clamp(-1.0) == 0.0
    assert _clamp(7.456) == 7.5


def test_score_reliability_improves_when_healthy() -> None:
    svc = DeploymentScoreService(get_settings())
    obs_unhealthy = ObservabilitySnapshot(
        deployment_id=uuid4(),
        health=[
            ServiceHealth(service="api", status="critical", readiness_ok=False),
            ServiceHealth(service="frontend", status="healthy", readiness_ok=True),
        ],
        metrics=[ServiceMetrics(service="api", cpu_percent=55, memory_mb=384)],
    )
    obs_healthy = ObservabilitySnapshot(
        deployment_id=uuid4(),
        health=[
            ServiceHealth(service="api", status="healthy", readiness_ok=True),
            ServiceHealth(service="frontend", status="healthy", readiness_ok=True),
        ],
        metrics=[ServiceMetrics(service="api", cpu_percent=14, memory_mb=256)],
    )
    deployment = Deployment(
        session_id=uuid4(),
        status=DeploymentStatus.SUCCEEDED,
        stage=DeploymentStage.COMPLETE,
    )
    bad = svc._score_reliability(deployment, obs_unhealthy, open_incidents=[object()], resolved_incidents=[])
    good = svc._score_reliability(deployment, obs_healthy, open_incidents=[], resolved_incidents=[object()])
    assert good > bad
