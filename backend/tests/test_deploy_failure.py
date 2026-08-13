"""Tests for deployment failure classification."""

from app.models.deployment import DeploymentStage
from app.services.deploy_failure import (
    classify_import_failure,
    classify_pipeline_failure,
    retry_from_phase,
    stage_to_ui_index,
)


def test_classify_import_not_found() -> None:
    phase, summary = classify_import_failure(
        {"stderr": '{"error":{"code":"notFound","message":"Not Found"}}', "ok": False}
    )
    assert phase == "import"
    assert "Not Found" in summary or "DEPLOY_PROJECT_ID" in summary


def test_classify_pipeline_readiness() -> None:
    phase, summary = classify_pipeline_failure(
        DeploymentStage.READINESS_CHECK,
        ["readiness check failed on /api/v1/health"],
    )
    assert phase == "readiness"
    assert "Readiness" in summary


def test_stage_to_ui_index_import_failure() -> None:
    assert stage_to_ui_index(DeploymentStage.FAILED, failure_phase="import") == 0


def test_retry_from_phase() -> None:
    assert retry_from_phase("import") == "import"
    assert retry_from_phase("build") == "pipeline"
