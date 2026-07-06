"""Plugin base interface."""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

from fastapi import APIRouter


@dataclass(frozen=True)
class PluginMetadata:
    """Plugin descriptor."""

    name: str
    version: str
    description: str
    author: str = "IFNOTUS"
    dependencies: tuple[str, ...] = ()


class PluginBase(ABC):
    """Base class for IFNOTUS plugins."""

    metadata: PluginMetadata

    @abstractmethod
    async def on_load(self) -> None:
        """Called when the plugin is loaded at startup."""
        ...

    @abstractmethod
    async def on_unload(self) -> None:
        """Called when the plugin is unloaded at shutdown."""
        ...

    def get_routers(self) -> list[APIRouter]:
        """Return API routers to mount — override to expose plugin endpoints."""
        return []

    def get_tasks(self) -> list[Any]:
        """Return background tasks to register — override to add worker tasks."""
        return []

    def get_services(self) -> dict[str, Any]:
        """Return named services for DI — override to register plugin services."""
        return {}
