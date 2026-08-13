"""Pod event streaming + failure classification helpers."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import Any

from kubernetes import client, watch


FailureReason = str

KNOWN_REASONS: tuple[FailureReason, ...] = (
    "CrashLoopBackOff",
    "OOMKilled",
    "ImagePullBackOff",
    "ErrImagePull",
    "CreateContainerConfigError",
    "PendingPVC",
    "FailedScheduling",
    "FailedMount",
)


def classify_pod(pod: Any) -> FailureReason | None:
    """Return a canonical failure reason for a pod, or ``None`` if healthy."""
    status = getattr(pod, "status", None)
    if status is None:
        return None

    phase = getattr(status, "phase", None)
    for container_status in list(getattr(status, "container_statuses", None) or []):
        waiting = getattr(container_status.state, "waiting", None) if container_status.state else None
        terminated = (
            getattr(container_status.state, "terminated", None) if container_status.state else None
        )
        if waiting and waiting.reason in {
            "CrashLoopBackOff",
            "ImagePullBackOff",
            "ErrImagePull",
            "CreateContainerConfigError",
        }:
            return waiting.reason
        if terminated and terminated.reason == "OOMKilled":
            return "OOMKilled"

    if phase == "Pending":
        for cond in list(getattr(status, "conditions", None) or []):
            if cond.type == "PodScheduled" and cond.status != "True":
                # Unbound PVC is the most common blocker on scheduled=false.
                if cond.reason == "Unschedulable" and "pvc" in (cond.message or "").lower():
                    return "PendingPVC"
                return cond.reason or "FailedScheduling"
    return None


def classify_event(event: Any) -> FailureReason | None:
    reason = getattr(event, "reason", None)
    if not reason:
        return None
    if reason in KNOWN_REASONS:
        return reason
    if reason in {"BackOff", "Failed"} and getattr(event, "type", "") == "Warning":
        return reason
    return None


async def stream_events(
    core_v1: client.CoreV1Api,
    namespace: str,
    *,
    timeout_seconds: int = 0,
) -> AsyncIterator[dict[str, Any]]:
    """Yield core/v1 Event objects for ``namespace`` as plain dicts.

    ``timeout_seconds=0`` streams indefinitely until the consumer stops iterating.
    Runs the blocking ``watch.Watch`` loop off-thread and hands items across an
    ``asyncio.Queue`` so callers stay fully async.
    """
    queue: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue(maxsize=64)
    loop = asyncio.get_running_loop()
    stop = asyncio.Event()

    def _run() -> None:
        w = watch.Watch()
        try:
            kwargs: dict[str, Any] = {"namespace": namespace}
            if timeout_seconds:
                kwargs["timeout_seconds"] = timeout_seconds
            for raw in w.stream(core_v1.list_namespaced_event, **kwargs):
                if stop.is_set():
                    break
                obj = raw.get("object")
                item = {
                    "type": raw.get("type"),
                    "reason": getattr(obj, "reason", None),
                    "message": getattr(obj, "message", None),
                    "involved_object": _involved(obj),
                    "count": getattr(obj, "count", None),
                    "classification": classify_event(obj),
                }
                asyncio.run_coroutine_threadsafe(queue.put(item), loop).result()
        finally:
            asyncio.run_coroutine_threadsafe(queue.put(None), loop)

    task = loop.run_in_executor(None, _run)
    try:
        while True:
            item = await queue.get()
            if item is None:
                return
            yield item
    finally:
        stop.set()
        # Best-effort: the underlying watch respects timeout_seconds; drain task.
        await asyncio.shield(asyncio.wrap_future(task)) if not task.done() else None


def _involved(obj: Any) -> dict[str, str] | None:
    io = getattr(obj, "involved_object", None)
    if io is None:
        return None
    return {
        "kind": getattr(io, "kind", "") or "",
        "name": getattr(io, "name", "") or "",
        "namespace": getattr(io, "namespace", "") or "",
    }
