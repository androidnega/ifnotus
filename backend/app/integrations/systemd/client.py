"""Systemd integration skeleton."""

from app.integrations.base import IntegrationBase, IntegrationHealth, IntegrationStatus


class SystemdIntegration(IntegrationBase):
    """Systemd service manager integration."""

    name = "systemd"

    async def connect(self) -> None:
        pass

    async def disconnect(self) -> None:
        pass

    async def health_check(self) -> IntegrationHealth:
        return IntegrationHealth(name=self.name, status=IntegrationStatus.NOT_CONFIGURED)
