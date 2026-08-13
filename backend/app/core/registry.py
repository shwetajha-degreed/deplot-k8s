"""
Pluggable registries for services and agents.

Add new capabilities by registering implementations — no changes to orchestrator or main.py.
"""

from __future__ import annotations

from typing import Any, Callable, Generic, TypeVar

T = TypeVar("T")


class Registry(Generic[T]):
    def __init__(self, name: str) -> None:
        self._name = name
        self._items: dict[str, T] = {}

    def register(self, key: str, item: T) -> T:
        if key in self._items:
            raise ValueError(f"{self._name} '{key}' is already registered")
        self._items[key] = item
        return item

    def register_factory(self, key: str, factory: Callable[[], T]) -> None:
        self.register(key, factory())

    def get(self, key: str) -> T:
        if key not in self._items:
            raise KeyError(f"{self._name} '{key}' not found. Registered: {list(self._items)}")
        return self._items[key]

    def optional(self, key: str) -> T | None:
        return self._items.get(key)

    def all(self) -> dict[str, T]:
        return dict(self._items)

    def keys(self) -> list[str]:
        return list(self._items.keys())


service_registry: Registry[Any] = Registry("service")
agent_registry: Registry[Any] = Registry("agent")
