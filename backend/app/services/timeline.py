"""Record and build ops timeline events."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from app.models.observability import TimelineEvent
from app.services.store import ops_timeline_store


def record_ops_event(
    deployment_id: UUID,
    *,
    source: str,
    event_type: str,
    message: str,
    service: str | None = None,
    metadata: dict | None = None,
) -> TimelineEvent:
    event = TimelineEvent(
        deployment_id=deployment_id,
        source=source,
        event_type=event_type,
        message=message,
        service=service,
        occurred_at=datetime.utcnow(),
        metadata=metadata or {},
    )
    return ops_timeline_store.append(event)


def list_ops_timeline(deployment_id: UUID) -> list[TimelineEvent]:
    return ops_timeline_store.list_for(deployment_id)
