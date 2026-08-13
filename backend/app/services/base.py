"""Base service interface — extend for new domain services."""

from abc import ABC


class BaseService(ABC):
    name: str = "base"
