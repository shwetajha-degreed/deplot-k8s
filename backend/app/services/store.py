"""PostgreSQL persistence with in-memory fallback."""

from __future__ import annotations

import json
import logging
from typing import Generic, TypeVar
from uuid import UUID

from pydantic import BaseModel

from app.models.aiops import Incident
from app.models.analysis import AnalysisSession
from app.models.deployment import Deployment
from app.models.observability import TimelineEvent

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)


class InMemoryStore(Generic[T]):
    def __init__(self) -> None:
        self._items: dict[UUID, T] = {}

    def save(self, item: T) -> T:
        item_id = getattr(item, "id")
        self._items[item_id] = item
        return item

    def get(self, item_id: UUID) -> T | None:
        return self._items.get(item_id)

    def list_all(self) -> list[T]:
        return list(self._items.values())

    def delete(self, item_id: UUID) -> bool:
        return self._items.pop(item_id, None) is not None


class PostgresStore(Generic[T]):
    """JSON blob store per entity type — minimal persistence for prototype."""

    def __init__(self, table: str, model_cls: type[T], database_url: str) -> None:
        self._table = table
        self._model_cls = model_cls
        self._url = database_url.replace("postgresql+asyncpg://", "postgresql://")
        self._ready = False
        self._fallback = InMemoryStore[T]()
        self._init_db()

    def _init_db(self) -> None:
        try:
            import psycopg2

            conn = psycopg2.connect(self._url)
            conn.autocommit = True
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    CREATE TABLE IF NOT EXISTS {self._table} (
                        id UUID PRIMARY KEY,
                        payload JSONB NOT NULL,
                        updated_at TIMESTAMPTZ DEFAULT NOW()
                    )
                    """
                )
            conn.close()
            self._ready = True
            logger.info("Postgres store ready: %s", self._table)
        except Exception as exc:
            logger.warning("Postgres unavailable for %s: %s — using memory", self._table, exc)
            self._ready = False

    def save(self, item: T) -> T:
        if not self._ready:
            return self._fallback.save(item)
        try:
            import psycopg2
            from psycopg2.extras import Json

            conn = psycopg2.connect(self._url)
            with conn:
                with conn.cursor() as cur:
                    cur.execute(
                        f"""
                        INSERT INTO {self._table} (id, payload, updated_at)
                        VALUES (%s, %s, NOW())
                        ON CONFLICT (id) DO UPDATE SET payload = EXCLUDED.payload, updated_at = NOW()
                        """,
                        (str(item.id), Json(json.loads(item.model_dump_json(mode="json")))),
                    )
            conn.close()
            return item
        except Exception as exc:
            logger.warning("Postgres save failed: %s", exc)
            return self._fallback.save(item)

    def get(self, item_id: UUID) -> T | None:
        if not self._ready:
            return self._fallback.get(item_id)
        try:
            import psycopg2

            conn = psycopg2.connect(self._url)
            with conn.cursor() as cur:
                cur.execute(f"SELECT payload FROM {self._table} WHERE id = %s", (str(item_id),))
                row = cur.fetchone()
            conn.close()
            if row:
                return self._model_cls.model_validate(row[0])
        except Exception as exc:
            logger.warning("Postgres get failed: %s", exc)
        return self._fallback.get(item_id)

    def list_all(self) -> list[T]:
        if not self._ready:
            return self._fallback.list_all()
        try:
            import psycopg2

            conn = psycopg2.connect(self._url)
            with conn.cursor() as cur:
                cur.execute(f"SELECT payload FROM {self._table} ORDER BY updated_at DESC")
                rows = cur.fetchall()
            conn.close()
            return [self._model_cls.model_validate(r[0]) for r in rows]
        except Exception as exc:
            logger.warning("Postgres list failed: %s", exc)
        return self._fallback.list_all()

    def delete(self, item_id: UUID) -> bool:
        if not self._ready:
            return self._fallback.delete(item_id)
        try:
            import psycopg2

            conn = psycopg2.connect(self._url)
            with conn:
                with conn.cursor() as cur:
                    cur.execute(f"DELETE FROM {self._table} WHERE id = %s", (str(item_id),))
                    deleted = cur.rowcount > 0
            conn.close()
            return deleted
        except Exception:
            return self._fallback.delete(item_id)


class StoreProxy(Generic[T]):
    """Forwards to a swappable backend so `from ... import session_store`
    keeps working after init_stores() upgrades from memory to Postgres.

    Without this proxy, every caller that did `from app.services.store
    import session_store` captured a local reference to the initial
    InMemoryStore at import time. When init_stores() later rebound the
    module-level name to a PostgresStore, those callers kept writing to
    the in-memory instance — so sessions vanished on backend restart.
    """

    def __init__(self, backend: InMemoryStore[T] | PostgresStore[T]) -> None:
        self._backend: InMemoryStore[T] | PostgresStore[T] = backend

    def _swap(self, backend: InMemoryStore[T] | PostgresStore[T]) -> None:
        self._backend = backend

    def save(self, item: T) -> T:
        return self._backend.save(item)

    def get(self, item_id: UUID) -> T | None:
        return self._backend.get(item_id)

    def list_all(self) -> list[T]:
        return self._backend.list_all()

    def delete(self, item_id: UUID) -> bool:
        return self._backend.delete(item_id)


def init_stores(database_url: str) -> None:
    """Upgrade the module-level proxies from memory to Postgres-backed.

    Safe to call multiple times; each call rebinds the proxies' backends.
    All existing importers of session_store / deployment_store /
    incident_store see the upgrade immediately because they hold the
    proxy, not the underlying backend.
    """
    session_store._swap(PostgresStore("deplot_sessions", AnalysisSession, database_url))
    deployment_store._swap(PostgresStore("deplot_deployments", Deployment, database_url))
    incident_store._swap(PostgresStore("deplot_incidents", Incident, database_url))


# Default in-memory until bootstrap calls init_stores. These are the
# module-level names every caller imports; init_stores() mutates their
# backend rather than rebinding the name.
session_store: StoreProxy[AnalysisSession] = StoreProxy(InMemoryStore())
deployment_store: StoreProxy[Deployment] = StoreProxy(InMemoryStore())
incident_store: StoreProxy[Incident] = StoreProxy(InMemoryStore())


class OpsTimelineStore:
    """In-memory ops timeline per deployment (deploy → incident → heal → score)."""

    def __init__(self) -> None:
        self._events: dict[UUID, list[TimelineEvent]] = {}

    def append(self, event: TimelineEvent) -> TimelineEvent:
        bucket = self._events.setdefault(event.deployment_id, [])
        bucket.append(event)
        bucket.sort(key=lambda e: e.occurred_at)
        return event

    def list_for(self, deployment_id: UUID) -> list[TimelineEvent]:
        return list(self._events.get(deployment_id, []))


ops_timeline_store = OpsTimelineStore()
