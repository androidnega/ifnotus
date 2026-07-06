"""Netdata integration skeleton."""

from app.integrations.base import IntegrationBase, IntegrationHealth, IntegrationStatus


class NetdataIntegration(IntegrationBase):
    """Netdata monitoring integration."""

    name = "netdata"

    def __init__(self, base_url: str | None = None) -> None:
        self._base_url = base_url
        self._connected = False

    async def connect(self) -> None:
        self._connected = self._base_url is not None

    async def disconnect(self) -> None:
        self._connected = False

    async def health_check(self) -> IntegrationHealth:
        if not self._base_url:
            return IntegrationHealth(name=self.name, status=IntegrationStatus.NOT_CONFIGURED)
        return IntegrationHealth(
            name=self.name,
            status=IntegrationStatus.CONNECTED if self._connected else IntegrationStatus.DISCONNECTED,
        )
