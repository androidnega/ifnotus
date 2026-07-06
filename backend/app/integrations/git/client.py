"""Git integration — live repository operations."""

from __future__ import annotations

from pathlib import Path

from app.integrations.base import IntegrationBase, IntegrationHealth, IntegrationStatus
from app.services.applications.readers.git import GitReader


class GitIntegration(IntegrationBase):
    """Local Git repository integration."""

    name = "git"

    def __init__(self) -> None:
        self._reader = GitReader()

    async def connect(self) -> None:
        pass

    async def disconnect(self) -> None:
        pass

    async def health_check(self) -> IntegrationHealth:
        return IntegrationHealth(name=self.name, status=IntegrationStatus.NOT_CONFIGURED)

    async def status(self, repo_path: str | Path) -> IntegrationHealth:
        result = await self._reader.read(repo_path)
        status = IntegrationStatus.CONNECTED if result.available else IntegrationStatus.ERROR
        return IntegrationHealth(
            name=self.name,
            status=status,
            message=result.message,
        )
