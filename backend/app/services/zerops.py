"""Real Zerops integration via zcli and REST API."""

from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
import subprocess
import time
from pathlib import Path

import httpx

from app.models.deployment import DeploymentStage, ZeropsConfig
from app.services.base import BaseService


def repo_slug_from_url(repo_url: str | None) -> str:
    if not repo_url:
        return "app"
    path = repo_url.rstrip("/").replace(".git", "")
    name = Path(path).name.lower()
    slug = re.sub(r"[^a-z0-9-]", "", name.replace("_", "-"))
    return (slug[:20] if slug else "app")


def hostnames_for_slug(slug: str) -> dict[str, str]:
    return {
        "database": f"{slug}-postgres",
        "cache": f"{slug}-cache",
        "search": f"{slug}-search",
        "api": f"{slug}-api",
        "frontend": f"{slug}-web",
    }


class ZeropsService(BaseService):
    name = "zerops"

    STAGE_MAP = {
        "waiting": DeploymentStage.QUEUED,
        "running": DeploymentStage.BUILDING,
        "building": DeploymentStage.BUILDING,
        "installing": DeploymentStage.INSTALLING,
        "uploading": DeploymentStage.UPLOADING,
        "creating": DeploymentStage.CREATING_RUNTIME,
        "ready": DeploymentStage.COMPLETE,
        "failed": DeploymentStage.FAILED,
        "success": DeploymentStage.COMPLETE,
    }

    def __init__(self, settings) -> None:
        self._settings = settings

    def _zcli_path(self) -> str | None:
        if self._settings.zcli_path and Path(self._settings.zcli_path).exists():
            return self._settings.zcli_path
        candidates = [
            Path.home() / ".local" / "bin" / "zcli",
            Path.home() / ".zerops" / "bin" / "zcli",
            Path.home() / ".zerops" / "bin" / "zcli.exe",
            Path("/usr/local/bin/zcli"),
            Path("/opt/homebrew/bin/zcli"),
        ]
        for path in candidates:
            if path.exists():
                return str(path)
        return shutil.which("zcli")

    def _zcli_env(self) -> dict[str, str]:
        env = os.environ.copy()
        local_bin = str(Path.home() / ".local" / "bin")
        env["PATH"] = env.get("PATH", "") + os.pathsep + local_bin
        if self._settings.zerops_api_token:
            env["ZEROPS_TOKEN"] = self._settings.zerops_api_token
        return env

    def _api_headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        if self._settings.zerops_api_token:
            headers["Authorization"] = f"Bearer {self._settings.zerops_api_token}"
        return headers

    def _run_zcli(self, args: list[str], *, input_text: str | None = None) -> dict:
        """Cross-platform zcli runner (avoids uvloop asyncio subprocess issues)."""
        zcli = self._zcli_path()
        if not zcli:
            return {
                "ok": False,
                "returncode": 127,
                "stdout": "",
                "stderr": "zcli not found — install via: curl -L https://zerops.io/zcli/install.sh | sh",
                "error": "zcli not found",
            }
        try:
            completed = subprocess.run(
                [zcli, *args],
                input=input_text,
                capture_output=True,
                text=True,
                env=self._zcli_env(),
                timeout=180,
                check=False,
            )
        except FileNotFoundError:
            return {
                "ok": False,
                "returncode": 127,
                "stdout": "",
                "stderr": f"zcli binary missing at {zcli}",
                "error": "zcli not found",
            }
        except subprocess.TimeoutExpired:
            return {
                "ok": False,
                "returncode": 124,
                "stdout": "",
                "stderr": "zcli timed out",
                "error": "zcli timed out",
            }
        return {
            "ok": completed.returncode == 0,
            "returncode": completed.returncode,
            "stdout": completed.stdout or "",
            "stderr": completed.stderr or "",
        }

    async def import_services(self, import_yaml: str, project_id: str) -> dict:
        """Run zcli project service-import with YAML on stdin."""
        result = await asyncio.to_thread(
            self._run_zcli,
            ["project", "service-import", "-", "-P", project_id],
            input_text=import_yaml,
        )
        result["project_id"] = project_id
        return result

    async def deploy(
        self,
        config: ZeropsConfig,
        *,
        demo_mode: bool = False,
        project_id: str | None = None,
        repo_slug: str | None = None,
    ) -> dict:
        pid = project_id or self._settings.zerops_target_project_id
        if demo_mode:
            return {
                "simulated": True,
                "project_id": pid or "demo-project",
                "repo_slug": repo_slug or "demo",
            }
        if not pid:
            return {
                "ok": False,
                "error": "DEPLOY_PROJECT_ID not configured (set on api service; Zerops forbids ZEROPS_ prefix)",
                "simulated": True,
            }
        if not self._settings.zerops_api_token:
            return {
                "ok": False,
                "error": "DEPLOT_API_TOKEN not configured (set on api service; Zerops forbids ZEROPS_ prefix)",
                "simulated": True,
            }

        result = await self.import_services(config.import_yaml, pid)
        result["simulated"] = False
        result["repo_slug"] = repo_slug
        result["routing_checklist"] = self._routing_checklist(repo_slug or "app")
        return result

    def _routing_checklist(self, slug: str) -> list[str]:
        return [
            f"Enable Zerops subdomain access for {slug}-web (port 3000)",
            f"Enable Zerops subdomain access for {slug}-api (port 8000)",
            "Managed services (postgres, valkey, typesense) use private network only",
        ]

    async def trigger_redeploy(self, service_hostname: str, project_id: str | None = None) -> dict:
        """Trigger service redeploy via zcli if available."""
        pid = project_id or self._settings.zerops_target_project_id
        return await asyncio.to_thread(
            self._run_zcli,
            ["service", "deploy", service_hostname, "-P", pid or ""],
        )

    async def get_pipeline_status(
        self, service_hostname: str, project_id: str | None = None
    ) -> dict:
        pid = project_id or self._settings.zerops_target_project_id
        if not pid or not self._settings.zerops_api_token:
            return {"state": "unknown", "stage": DeploymentStage.BUILDING}

        url = f"{self._settings.zerops_api_base}/projects/{pid}/services/{service_hostname}/deployments"
        try:
            async with httpx.AsyncClient(timeout=20.0) as client:
                resp = await client.get(url, headers=self._api_headers())
                if resp.status_code == 404:
                    return {"state": "provisioning", "stage": DeploymentStage.PROVISIONING_DB}
                resp.raise_for_status()
                data = resp.json()
                if isinstance(data, list) and data:
                    latest = data[0]
                elif isinstance(data, dict):
                    latest = data
                else:
                    return {"state": "building", "stage": DeploymentStage.BUILDING}
                raw_state = str(latest.get("status") or latest.get("state") or "running").lower()
                stage = self.STAGE_MAP.get(raw_state, DeploymentStage.BUILDING)
                return {"state": raw_state, "stage": stage, "raw": latest}
        except Exception as exc:
            return {"state": "unknown", "stage": DeploymentStage.BUILDING, "error": str(exc)}

    async def get_service_urls(
        self, service_hostnames: dict[str, str], project_id: str | None = None
    ) -> dict[str, str]:
        """Best-effort public URLs for runtime services."""
        pid = project_id or self._settings.zerops_target_project_id
        urls: dict[str, str] = {}
        if not pid:
            return urls

        for role, hostname in service_hostnames.items():
            if role not in ("web", "api", "frontend"):
                continue
            url = await self._fetch_service_url(hostname, pid)
            if url:
                urls[role] = url
        return urls

    async def _fetch_service_url(self, hostname: str, project_id: str) -> str | None:
        url = f"{self._settings.zerops_api_base}/projects/{project_id}/services/{hostname}"
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.get(url, headers=self._api_headers())
                if resp.status_code != 200:
                    return None
                data = resp.json()
                for key in ("publicUrl", "public_url", "url", "subdomain"):
                    val = data.get(key)
                    if isinstance(val, str) and val.startswith("http"):
                        return val
                ports = data.get("ports") or data.get("httpPorts") or []
                for p in ports:
                    if isinstance(p, dict) and p.get("publicUrl"):
                        return str(p["publicUrl"])
        except Exception:
            pass
        port = "3000" if "web" in hostname else "8000"
        return f"https://{hostname}-{port}.prg1.zerops.app"

    async def fetch_logs(
        self, service_hostname: str, tail: int = 200, project_id: str | None = None
    ) -> list[str]:
        pid = project_id or self._settings.zerops_target_project_id
        if not pid or not self._settings.zerops_api_token:
            return []

        url = f"{self._settings.zerops_api_base}/projects/{pid}/services/{service_hostname}/logs"
        try:
            async with httpx.AsyncClient(timeout=25.0) as client:
                resp = await client.get(
                    url,
                    headers=self._api_headers(),
                    params={"limit": tail},
                )
                if resp.status_code != 200:
                    return self._parse_log_text(resp.text)
                data = resp.json()
                if isinstance(data, list):
                    return [str(line) for line in data[-tail:]]
                if isinstance(data, dict):
                    lines = data.get("lines") or data.get("logs") or []
                    return [str(line) for line in lines[-tail:]]
        except Exception:
            pass
        return []

    @staticmethod
    def _parse_log_text(text: str) -> list[str]:
        if not text.strip():
            return []
        try:
            data = json.loads(text)
            if isinstance(data, list):
                return [str(x) for x in data]
        except json.JSONDecodeError:
            pass
        return text.strip().splitlines()[-200:]

    async def fetch_metrics(self, service_hostname: str, project_id: str | None = None) -> list[dict]:
        pid = project_id or self._settings.zerops_target_project_id
        if not pid or not self._settings.zerops_api_token:
            return []
        url = f"{self._settings.zerops_api_base}/projects/{pid}/services/{service_hostname}/statistics"
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.get(url, headers=self._api_headers())
                if resp.status_code == 200:
                    data = resp.json()
                    if isinstance(data, list):
                        return data
                    if isinstance(data, dict):
                        return [data]
        except Exception:
            pass
        return []

    @staticmethod
    def _yaml_quote(value: str) -> str:
        escaped = value.replace("'", "''")
        return f"'{escaped}'"

    def build_env_patch_yaml(self, service_hostname: str, env_changes: dict[str, str]) -> str:
        """Minimal import YAML to patch envSecrets on an existing service."""
        lines = ["services:", f"  - hostname: {service_hostname}", "    envSecrets:"]
        for key, value in env_changes.items():
            lines.append(f"      {key}: {self._yaml_quote(value)}")
        return "\n".join(lines) + "\n"

    async def apply_env_changes(
        self,
        service_hostname: str,
        env_changes: dict[str, str],
        project_id: str | None = None,
        *,
        trigger_redeploy: bool = True,
    ) -> dict:
        """Apply env secrets via zcli project service-import patch YAML."""
        pid = project_id or self._settings.zerops_target_project_id
        if not pid:
            return {
                "ok": False,
                "error": "DEPLOY_PROJECT_ID not configured (set on api service; Zerops forbids ZEROPS_ prefix)",
            }
        if not env_changes:
            return {"ok": False, "error": "No environment changes to apply"}

        patch_yaml = self.build_env_patch_yaml(service_hostname, env_changes)
        result = await self.import_services(patch_yaml, pid)
        result["patch_yaml"] = patch_yaml
        result["service_hostname"] = service_hostname

        if trigger_redeploy and result.get("ok"):
            redeploy = await self.trigger_redeploy(service_hostname, pid)
            result["redeploy"] = redeploy
            if not redeploy.get("ok"):
                result["ok"] = False
                result["error"] = redeploy.get("stderr") or "Redeploy failed after env patch"
        return result

    async def wait_for_pipeline(
        self,
        service_hostname: str,
        project_id: str | None = None,
        *,
        timeout_seconds: int | None = None,
        poll_interval: float | None = None,
    ) -> dict:
        """Poll deployment pipeline until complete, failed, or timeout."""
        pid = project_id or self._settings.zerops_target_project_id
        timeout = timeout_seconds or self._settings.remediation_timeout_seconds
        interval = poll_interval or float(self._settings.remediation_poll_interval_seconds)
        deadline = time.monotonic() + timeout
        last: dict = {}

        while time.monotonic() < deadline:
            last = await self.get_pipeline_status(service_hostname, pid)
            stage = last.get("stage")
            if stage == DeploymentStage.COMPLETE:
                return {"ok": True, "stage": stage, "state": last.get("state"), "raw": last}
            if stage == DeploymentStage.FAILED:
                return {"ok": False, "stage": stage, "state": last.get("state"), "raw": last}
            await asyncio.sleep(interval)

        return {
            "ok": False,
            "error": f"Timed out after {timeout}s waiting for {service_hostname}",
            "stage": last.get("stage", DeploymentStage.BUILDING),
            "state": last.get("state"),
        }

    async def get_service_info(
        self, service_hostname: str, project_id: str | None = None
    ) -> dict:
        """Fetch service metadata from Zerops REST API."""
        pid = project_id or self._settings.zerops_target_project_id
        if not pid or not self._settings.zerops_api_token:
            return {"found": False}

        url = f"{self._settings.zerops_api_base}/projects/{pid}/services/{service_hostname}"
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.get(url, headers=self._api_headers())
                if resp.status_code == 404:
                    return {"found": False, "state": "provisioning"}
                if resp.status_code != 200:
                    return {"found": False, "state": "unknown", "status_code": resp.status_code}
                data = resp.json()
                if isinstance(data, dict):
                    state = str(
                        data.get("status") or data.get("state") or data.get("serviceStatus") or "running"
                    ).lower()
                    return {"found": True, "state": state, "raw": data}
        except Exception as exc:
            return {"found": False, "error": str(exc)}
        return {"found": False}
