"""Watch Deployments post-apply and drive AI-assisted heal cycles."""

from __future__ import annotations

import asyncio
import time
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from kubernetes.client.rest import ApiException

from app.config import Settings
from app.models.deployment import DeploymentStage, DeploymentStatus
from app.services.base import BaseService
from app.services.gemini import GeminiClient
from app.services.k8s.client import KubernetesService
from app.services.k8s.events import classify_pod
from app.services.operations import AIOpsService
from app.services.store import deployment_store
from app.services.timeline import record_ops_event


_CRASH_WAITING_REASONS: frozenset[str] = frozenset(
    {"CrashLoopBackOff", "ImagePullBackOff", "ErrImagePull"}
)


class HealLoopService(BaseService):
    name = "heal_loop"

    MAX_ATTEMPTS = 3
    HEAL_CONFIDENCE_THRESHOLD = 0.6
    AVAILABLE_HOLD_SECONDS = 60
    WATCH_INTERVAL_SECONDS = 5
    WATCH_TIMEOUT_SECONDS = 600

    def __init__(
        self,
        settings: Settings,
        *,
        k8s: KubernetesService,
        gemini: GeminiClient,
        aiops: AIOpsService,
    ) -> None:
        self._settings = settings
        self._k8s = k8s
        self._gemini = gemini
        self._aiops = aiops

    async def watch_and_heal(
        self,
        deployment_id: UUID,
        namespace: str,
        deployment_names: list[str],
    ) -> None:
        try:
            await self._watch_and_heal(deployment_id, namespace, deployment_names)
        except Exception as exc:  # top-level guard: never propagate into fire-and-forget task
            try:
                record_ops_event(
                    deployment_id,
                    source="heal",
                    event_type="loop_crashed",
                    message=f"heal loop crashed: {exc!r}"[:500],
                    service="platform",
                )
            except Exception:
                pass

    async def _watch_and_heal(
        self,
        deployment_id: UUID,
        namespace: str,
        deployment_names: list[str],
    ) -> None:
        if not deployment_names:
            return

        deadline = time.monotonic() + self.WATCH_TIMEOUT_SECONDS
        heal_attempts: dict[str, int] = {name: 0 for name in deployment_names}
        # WHY: monotonic snapshot when *all* deployments become healthy; any
        # transition back to not-healthy resets by setting it to None. Prevents
        # a jittery deploy from prematurely being called stable.
        healthy_since: float | None = None
        exhausted_reported = False

        while time.monotonic() < deadline:
            states: dict[str, str] = {}
            for name in deployment_names:
                states[name] = await self._state_for(namespace, name)

            all_healthy = all(s == "healthy" for s in states.values())
            any_failed = any(s == "failed" for s in states.values())

            if all_healthy:
                if healthy_since is None:
                    healthy_since = time.monotonic()
                elif time.monotonic() - healthy_since >= self.AVAILABLE_HOLD_SECONDS:
                    self._finalize_stable(deployment_id)
                    return
            else:
                healthy_since = None

            if any_failed:
                for name, state in states.items():
                    if state != "failed":
                        continue
                    if heal_attempts[name] >= self.MAX_ATTEMPTS:
                        if not exhausted_reported:
                            await self._finalize_exhausted(
                                deployment_id, namespace, name
                            )
                            exhausted_reported = True
                        continue
                    heal_attempts[name] += 1
                    await self._attempt_heal(
                        deployment_id, namespace, name, heal_attempts[name]
                    )

                if exhausted_reported:
                    return

            await asyncio.sleep(self.WATCH_INTERVAL_SECONDS)

        self._finalize_watch_timeout(deployment_id)

    # ---------------------------------------------------------------- state ---

    async def _state_for(self, namespace: str, name: str) -> str:
        try:
            dep = await asyncio.to_thread(
                self._k8s._apps().read_namespaced_deployment_status,
                name=name,
                namespace=namespace,
            )
        except ApiException:
            return "provisioning"

        status = getattr(dep, "status", None)
        spec = getattr(dep, "spec", None)
        desired = (getattr(spec, "replicas", None) if spec else None) or 1
        available = (getattr(status, "available_replicas", None) if status else None) or 0
        conditions = list((getattr(status, "conditions", None) if status else None) or [])

        available_true = any(
            c.type == "Available" and c.status == "True" for c in conditions
        )
        if available >= desired and available_true and desired > 0:
            return "healthy"

        for cond in conditions:
            if (
                cond.type == "Progressing"
                and getattr(cond, "reason", None) == "ProgressDeadlineExceeded"
            ):
                return "failed"

        pods = await self._k8s._list_deployment_pods(namespace, name)
        for pod in pods:
            phase = getattr(pod.status, "phase", None) if pod.status else None
            if phase != "Running" and classify_pod(pod) is not None:
                return "failed"
            if self._pod_stuck_waiting(pod):
                return "failed"

        return "provisioning"

    @staticmethod
    def _pod_stuck_waiting(pod: Any) -> bool:
        # WHY: CrashLoop/ImagePull can flap; require the container to have been
        # waiting >=90s (based on lastTerminationState.finishedAt) before we
        # commit to "failed" and burn a heal attempt.
        status = getattr(pod, "status", None)
        if status is None:
            return False
        now = datetime.now(timezone.utc)
        for cs in list(getattr(status, "container_statuses", None) or []):
            state = getattr(cs, "state", None)
            waiting = getattr(state, "waiting", None) if state else None
            if not waiting or waiting.reason not in _CRASH_WAITING_REASONS:
                continue
            last = getattr(cs, "last_state", None)
            terminated = getattr(last, "terminated", None) if last else None
            finished = getattr(terminated, "finished_at", None) if terminated else None
            if finished is None:
                continue
            if finished.tzinfo is None:
                finished = finished.replace(tzinfo=timezone.utc)
            if (now - finished).total_seconds() >= 90:
                return True
        return False

    # -------------------------------------------------------------- attempts --

    async def _attempt_heal(
        self,
        deployment_id: UUID,
        namespace: str,
        name: str,
        attempt: int,
    ) -> dict[str, Any]:
        deployment = deployment_store.get(deployment_id)
        if deployment is None:
            return {"applied": False, "reason": "deployment_missing"}

        deployment.heal_status = "healing"
        deployment_store.save(deployment)

        logs = await self._k8s.fetch_logs(namespace, name, tail_lines=200)
        stack_summary, yaml_excerpt = self._context_from_deployment(deployment)

        record_ops_event(
            deployment_id,
            source="heal",
            event_type="attempt_started",
            message=f"attempt {attempt}/{self.MAX_ATTEMPTS} on {name}",
            service=name,
        )

        diagnosis = await self._gemini.analyze_logs(
            logs=logs, stack_summary=stack_summary, yaml_excerpt=yaml_excerpt
        )

        confidence = float((diagnosis or {}).get("confidence", 0.0))
        env_changes = (diagnosis or {}).get("env_changes") or {}
        if (
            not diagnosis
            or confidence < self.HEAL_CONFIDENCE_THRESHOLD
            or not isinstance(env_changes, dict)
            or not env_changes
        ):
            outcome = (
                "abandoned_no_env"
                if diagnosis and not env_changes
                else "abandoned_low_confidence"
            )
            record_ops_event(
                deployment_id,
                source="heal",
                event_type="diagnosis_low_confidence",
                message=f"attempt {attempt} on {name}: confidence={confidence:.2f}"
                        f" env_changes={bool(env_changes)}",
                service=name,
            )
            await self._aiops.create_incident_from_failure(
                deployment_id,
                title=f"Heal skipped — {outcome} on {name}",
                logs=logs,
                stack_summary=stack_summary,
                yaml_excerpt=yaml_excerpt,
                affected_service=name,
            )
            self._append_history(
                deployment_id,
                attempt=attempt,
                deployment_name=name,
                applied=False,
                env_changes={},
                diagnosis=diagnosis,
                outcome=outcome,
            )
            return {"applied": False, "reason": outcome, "diagnosis": diagnosis}

        await self._k8s.apply_env_changes(name, namespace, env_changes)
        await self._k8s.trigger_redeploy(name, namespace)

        suggested = (diagnosis.get("suggested_fix") or "")[:200]
        record_ops_event(
            deployment_id,
            source="heal",
            event_type="patch_applied",
            message=f"attempt {attempt}: {suggested}",
            service=name,
        )
        self._append_history(
            deployment_id,
            attempt=attempt,
            deployment_name=name,
            applied=True,
            env_changes=env_changes,
            diagnosis=diagnosis,
            outcome="patched",
        )
        return {
            "applied": True,
            "attempt": attempt,
            "env_changes": env_changes,
            "diagnosis": diagnosis,
        }

    # ------------------------------------------------------------- finalize --

    def _finalize_stable(self, deployment_id: UUID) -> None:
        deployment = deployment_store.get(deployment_id)
        if deployment is None:
            return
        deployment.status = DeploymentStatus.SUCCEEDED
        deployment.stage = DeploymentStage.COMPLETE
        deployment.heal_status = "stable"
        deployment.updated_at = datetime.utcnow()
        deployment_store.save(deployment)
        record_ops_event(
            deployment_id,
            source="heal",
            event_type="stable",
            message=f"Deployment healthy for >={self.AVAILABLE_HOLD_SECONDS}s",
            service="platform",
        )

    async def _finalize_exhausted(
        self, deployment_id: UUID, namespace: str, name: str
    ) -> None:
        deployment = deployment_store.get(deployment_id)
        if deployment is None:
            return
        deployment.status = DeploymentStatus.FAILED
        deployment.stage = DeploymentStage.FAILED
        deployment.heal_status = "exhausted"
        deployment.updated_at = datetime.utcnow()
        deployment_store.save(deployment)
        logs = await self._k8s.fetch_logs(namespace, name, tail_lines=200)
        stack_summary, yaml_excerpt = self._context_from_deployment(deployment)
        await self._aiops.create_incident_from_failure(
            deployment_id,
            title="Heal loop exhausted after 3 attempts",
            logs=logs,
            stack_summary=stack_summary,
            yaml_excerpt=yaml_excerpt,
            affected_service=name,
        )
        record_ops_event(
            deployment_id,
            source="heal",
            event_type="exhausted",
            message=f"Heal loop exhausted on {name}",
            service=name,
        )

    def _finalize_watch_timeout(self, deployment_id: UUID) -> None:
        deployment = deployment_store.get(deployment_id)
        if deployment is None:
            return
        deployment.heal_status = "watch_timeout"
        deployment.updated_at = datetime.utcnow()
        deployment_store.save(deployment)
        record_ops_event(
            deployment_id,
            source="heal",
            event_type="watch_timeout",
            message=f"Heal watch expired after {self.WATCH_TIMEOUT_SECONDS}s",
            service="platform",
        )

    # ---------------------------------------------------------------- utils --

    def _append_history(
        self,
        deployment_id: UUID,
        *,
        attempt: int,
        deployment_name: str,
        applied: bool,
        env_changes: dict[str, str],
        diagnosis: dict | None,
        outcome: str,
    ) -> None:
        deployment = deployment_store.get(deployment_id)
        if deployment is None:
            return
        trimmed = {
            "root_cause": (diagnosis or {}).get("root_cause", ""),
            "confidence": float((diagnosis or {}).get("confidence", 0.0)),
            "suggested_fix": (diagnosis or {}).get("suggested_fix", ""),
        }
        deployment.heal_history.append(
            {
                "attempt": attempt,
                "deployment_name": deployment_name,
                "timestamp": datetime.utcnow().isoformat(),
                "applied": applied,
                "env_changes": dict(env_changes),
                "diagnosis": trimmed,
                "outcome": outcome,
            }
        )
        deployment.updated_at = datetime.utcnow()
        deployment_store.save(deployment)

    @staticmethod
    def _context_from_deployment(deployment) -> tuple[str, str]:
        stack_bits: list[str] = []
        if deployment.repo_slug:
            stack_bits.append(f"slug={deployment.repo_slug}")
        if deployment.namespace:
            stack_bits.append(f"ns={deployment.namespace}")
        stack_summary = ", ".join(stack_bits) or "unknown"
        yaml_excerpt = ""
        if deployment.config and deployment.config.manifests:
            yaml_excerpt = str(deployment.config.manifests)[:3000]
        return stack_summary, yaml_excerpt
