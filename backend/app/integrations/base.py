"""Integration base interface."""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import StrEnum


class IntegrationStatus(StrEnum):
    """Integration connection status."""

    CONNECTED = "connected"
    DISCONNECTED = "disconnected"
    ERROR = "error"
    NOT_CONFIGURED = "not_configured"


@dataclass
class IntegrationHealth:
    """Integration health snapshot."""

    name: str
    status: IntegrationStatus
    message: str | None = None


class IntegrationBase(ABC):
    """Base class for external system integrations."""

    name: str

    @abstractmethod
    async def connect(self) -> None:
        """Establish connection to the external system."""
        ...

    @abstractmethod
    async def disconnect(self) -> None:
        """Close connection to the external system."""
        ...

    @abstractmethod
    async def health_check(self) -> IntegrationHealth:
        """Return current integration health."""
        ...
