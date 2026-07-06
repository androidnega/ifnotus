"""Future module interfaces — deployment, backup, SSL, domain, email."""

from __future__ import annotations

from typing import Protocol

from app.schemas.applications import DeploymentRecordSchema
from app.services.applications.config import ApplicationDefinition


class DeploymentModule(Protocol):
    """Future deployment automation module."""

    async def list_deployments(self, app: ApplicationDefinition) -> list[DeploymentRecordSchema]: ...


class BackupModule(Protocol):
    """Future backup module."""

    async def list_backups(self, app: ApplicationDefinition) -> list: ...


class SSLModule(Protocol):
    """Future SSL management module."""

    async def provision(self, app: ApplicationDefinition, domain: str) -> None: ...


class DomainModule(Protocol):
    """Future domain management module."""

    async def list_domains(self, app: ApplicationDefinition) -> list[str]: ...


class EmailModule(Protocol):
    """Future email administration module."""

    async def list_mailboxes(self, app: ApplicationDefinition) -> list: ...


class ApplicationModules:
    """Container for optional future modules."""

    def __init__(
        self,
        deployment: DeploymentModule | None = None,
        backup: BackupModule | None = None,
        ssl: SSLModule | None = None,
        domain: DomainModule | None = None,
        email: EmailModule | None = None,
    ) -> None:
        self.deployment = deployment
        self.backup = backup
        self.ssl = ssl
        self.domain = domain
        self.email = email
