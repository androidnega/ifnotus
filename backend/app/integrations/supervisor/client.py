"""Supervisor integration skeleton."""

from app.integrations.base import IntegrationBase, IntegrationHealth, IntegrationStatus


class SupervisorIntegration(IntegrationBase):
    """Supervisor process manager integration."""

    name = "supervisor"

    async def connect(self) -> None:
        pass

    async def disconnect(self) -> None:
        pass

    async def health_check(self) -> IntegrationHealth:
        return IntegrationHealth(name=self.name, status=IntegrationStatus.NOT_CONFIGURED)
