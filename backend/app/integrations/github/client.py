"""GitHub API integration skeleton."""

from app.integrations.base import IntegrationBase, IntegrationHealth, IntegrationStatus


class GitHubIntegration(IntegrationBase):
    """GitHub API integration for deployments and webhooks."""

    name = "github"

    def __init__(self, api_url: str = "https://api.github.com", token: str | None = None) -> None:
        self._api_url = api_url
        self._token = token

    async def connect(self) -> None:
        pass

    async def disconnect(self) -> None:
        pass

    async def health_check(self) -> IntegrationHealth:
        status = IntegrationStatus.CONNECTED if self._token else IntegrationStatus.NOT_CONFIGURED
        return IntegrationHealth(name=self.name, status=status)
