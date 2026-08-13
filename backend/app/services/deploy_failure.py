"""Deployment failure classification and retry phase helpers."""

from __future__ import annotations

import json
import re

from app.models.deployment import DeploymentStage


def _combined_error_text(*parts: str | None) -> str:
    return " ".join(p for p in parts if p).strip()


def parse_log_error(log_line: str) -> str | None:
    """Extract a human message from JSON log lines (e.g. Zerops notFound)."""
    text = log_line.strip()
    if not text:
        return None
    if text.startswith("{"):
        try:
            data = json.loads(text)
            err = data.get("error")
            if isinstance(err, dict):
                msg = err.get("message") or err.get("code")
                if msg:
                    return str(msg)
            message = data.get("message")
            if message:
                return str(message)
        except json.JSONDecodeError:
            pass
    return text[:500] if len(text) > 500 else text


def classify_import_failure(result: dict) -> tuple[str, str]:
    """Return (failure_phase, failure_summary) for a failed zcli import."""
    stderr = str(result.get("stderr") or "")
    stdout = str(result.get("stdout") or "")
    error = str(result.get("error") or "")
    combined = _combined_error_text(stderr, stdout, error).lower()

    if "not found" in combined or "notfound" in combined:
        return (
            "import",
            "Zerops returned Not Found during service import. Confirm DEPLOY_PROJECT_ID "
            "points to an existing project and your API token can access it.",
        )
    if "unauthorized" in combined or "forbidden" in combined or "401" in combined:
        return (
            "import",
            "Zerops rejected the import — verify DEPLOT_API_TOKEN / ZEROPS_API_TOKEN is valid.",
        )
    if "zcli not found" in combined:
        return (
            "import",
            "zcli is not installed on the API host — install zcli or run Deplot backend locally.",
        )
    if "deploy_project_id" in combined or "not configured" in combined:
        return (
            "import",
            "Deploy project is not configured. Set DEPLOY_PROJECT_ID on the api service.",
        )

    parsed = parse_log_error(stderr) or parse_log_error(stdout) or error
    summary = parsed or "Zerops service import failed — inspect stderr in the build log."
    return "import", summary[:1000]


def classify_pipeline_failure(stage: DeploymentStage, logs: list[str]) -> tuple[str, str]:
    """Return (failure_phase, failure_summary) for a failed build/readiness pipeline."""
    log_text = "\n".join(logs[-20:]).lower()
    if stage in (DeploymentStage.READINESS_CHECK, DeploymentStage.FAILED):
        if "readiness" in log_text or "health" in log_text or "probe" in log_text:
            return (
                "readiness",
                "Readiness check failed — the service built but is not passing HTTP health probes.",
            )
        return (
            "readiness",
            "Deployment pipeline failed during readiness or runtime startup.",
        )
    if stage in (DeploymentStage.PROVISIONING_DB, DeploymentStage.CREATING_RUNTIME):
        return (
            "provisioning",
            "Managed services or runtime containers failed to provision on Zerops.",
        )
    if "prisma" in log_text or "migration" in log_text or "database" in log_text:
        return (
            "build",
            "Build or startup failed — likely database connection or migration issue.",
        )
    return "build", "Zerops build pipeline failed — review build logs for the failing service."


def stage_to_ui_index(stage: DeploymentStage, *, failure_phase: str | None = None) -> int:
    """Map backend stage to wizard deploy checklist index (0–6)."""
    if failure_phase == "import":
        return 0
    mapping = {
        DeploymentStage.QUEUED: 0,
        DeploymentStage.BUILDING: 0,
        DeploymentStage.INSTALLING: 1,
        DeploymentStage.UPLOADING: 2,
        DeploymentStage.CREATING_RUNTIME: 3,
        DeploymentStage.PROVISIONING_DB: 4,
        DeploymentStage.READINESS_CHECK: 5,
        DeploymentStage.COMPLETE: 6,
        DeploymentStage.FAILED: 5,
    }
    return mapping.get(stage, 0)


def retry_phase_label(phase: str) -> str:
    labels = {
        "import": "Re-run Zerops service import",
        "build": "Retry build pipeline",
        "provisioning": "Retry provisioning",
        "readiness": "Retry readiness check",
        "pipeline": "Redeploy web + api pipelines",
    }
    return labels.get(phase, "Retry deployment")


def retry_from_phase(failure_phase: str | None) -> str:
    """Best retry action for a failure phase."""
    if failure_phase == "import":
        return "import"
    return "pipeline"
