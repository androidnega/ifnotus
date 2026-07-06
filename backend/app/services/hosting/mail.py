"""Mail account management service."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.exceptions import ConflictError, NotFoundError
from app.core.security import hash_password
from app.models.hosting import MailAlias, Mailbox
from app.repositories.domain import DomainRepository
from app.repositories.mail import MailAliasRepository, MailboxRepository
from app.schemas.hosting import (
    MailAliasCreate,
    MailAliasSchema,
    MailboxCreate,
    MailboxSchema,
    MailboxUpdate,
    MailDomainResponse,
)
from app.services.hosting.domains import DomainService


class MailService:
    def __init__(self, settings: Settings, session: AsyncSession) -> None:
        self._settings = settings
        self._domains = DomainRepository(session)
        self._mailboxes = MailboxRepository(session)
        self._aliases = MailAliasRepository(session)
        self._domain_service = DomainService(settings, session)

    async def get_domain_mail(self, domain_id: UUID) -> MailDomainResponse:
        domain = await self._domains.get_by_id(domain_id)
        if domain is None:
            raise NotFoundError("Domain not found.")
        domain_schema = await self._domain_service.get_domain(domain_id)
        mailboxes = await self._mailboxes.list_for_domain(domain_id)
        aliases = await self._aliases.list_for_domain(domain_id)
        return MailDomainResponse(
            timestamp=datetime.now(UTC),
            domain=domain_schema,
            mailboxes=[self._map_mailbox(m, domain.name) for m in mailboxes],
            aliases=[self._map_alias(a, domain.name) for a in aliases],
            webmail_url=self._settings.webmail_url,
            mail_config_path=str(self._config_path(domain.name)),
        )

    async def create_mailbox(self, domain_id: UUID, body: MailboxCreate) -> MailboxSchema:
        domain = await self._domains.get_by_id(domain_id)
        if domain is None:
            raise NotFoundError("Domain not found.")
        local = body.local_part.lower().strip()
        existing = await self._mailboxes.get_by_local(domain_id, local)
        if existing:
            raise ConflictError(f"Mailbox '{local}@{domain.name}' already exists.")

        mailbox = Mailbox(
            domain_id=domain_id,
            local_part=local,
            hashed_password=hash_password(body.password),
            quota_mb=body.quota_mb,
            display_name=body.display_name,
        )
        await self._mailboxes.create(mailbox)
        await self._sync_mail_config(domain_id)
        return self._map_mailbox(mailbox, domain.name)

    async def update_mailbox(
        self, domain_id: UUID, mailbox_id: UUID, body: MailboxUpdate
    ) -> MailboxSchema:
        domain = await self._domains.get_by_id(domain_id)
        if domain is None:
            raise NotFoundError("Domain not found.")
        mailbox = await self._mailboxes.get_by_id(mailbox_id)
        if mailbox is None or mailbox.domain_id != domain_id:
            raise NotFoundError("Mailbox not found.")
        if body.password:
            mailbox.hashed_password = hash_password(body.password)
        if body.quota_mb is not None:
            mailbox.quota_mb = body.quota_mb
        if body.suspended is not None:
            mailbox.suspended = body.suspended
        if body.display_name is not None:
            mailbox.display_name = body.display_name
        await self._mailboxes.update(mailbox)
        await self._sync_mail_config(domain_id)
        return self._map_mailbox(mailbox, domain.name)

    async def delete_mailbox(self, domain_id: UUID, mailbox_id: UUID) -> None:
        mailbox = await self._mailboxes.get_by_id(mailbox_id)
        if mailbox is None or mailbox.domain_id != domain_id:
            raise NotFoundError("Mailbox not found.")
        await self._mailboxes.delete(mailbox)
        await self._sync_mail_config(domain_id)

    async def create_alias(self, domain_id: UUID, body: MailAliasCreate) -> MailAliasSchema:
        domain = await self._domains.get_by_id(domain_id)
        if domain is None:
            raise NotFoundError("Domain not found.")
        alias = MailAlias(
            domain_id=domain_id,
            source_local=body.source_local.lower().strip(),
            destination=body.destination.strip(),
        )
        await self._aliases.create(alias)
        await self._sync_mail_config(domain_id)
        return self._map_alias(alias, domain.name)

    async def delete_alias(self, domain_id: UUID, alias_id: UUID) -> None:
        alias = await self._aliases.get_by_id(alias_id)
        if alias is None or alias.domain_id != domain_id:
            raise NotFoundError("Alias not found.")
        await self._aliases.delete(alias)
        await self._sync_mail_config(domain_id)

    async def _sync_mail_config(self, domain_id: UUID) -> None:
        """Write mail config snapshot for external MTA integration."""
        domain = await self._domains.get_by_id(domain_id)
        if domain is None:
            return
        mailboxes = await self._mailboxes.list_for_domain(domain_id)
        aliases = await self._aliases.list_for_domain(domain_id)
        config_dir = self._config_dir()
        config_dir.mkdir(parents=True, exist_ok=True)
        payload = {
            "domain": domain.name,
            "mailboxes": [
                {
                    "email": f"{m.local_part}@{domain.name}",
                    "suspended": m.suspended,
                    "quota_mb": m.quota_mb,
                }
                for m in mailboxes
            ],
            "aliases": [
                {
                    "source": f"{a.source_local}@{domain.name}",
                    "destination": a.destination,
                    "enabled": a.enabled,
                }
                for a in aliases
            ],
            "updated_at": datetime.now(UTC).isoformat(),
        }
        (config_dir / f"{domain.name}.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def _config_dir(self) -> Path:
        config_dir = Path(self._settings.mail_config_dir)
        if not config_dir.is_absolute():
            config_dir = Path.cwd() / config_dir
        return config_dir

    def _config_path(self, domain_name: str) -> Path:
        return self._config_dir() / f"{domain_name}.json"

    @staticmethod
    def _map_mailbox(mailbox: Mailbox, domain_name: str) -> MailboxSchema:
        return MailboxSchema(
            id=mailbox.id,
            domain_id=mailbox.domain_id,
            email=f"{mailbox.local_part}@{domain_name}",
            local_part=mailbox.local_part,
            quota_mb=mailbox.quota_mb,
            suspended=mailbox.suspended,
            display_name=mailbox.display_name,
            created_at=mailbox.created_at,
        )

    @staticmethod
    def _map_alias(alias: MailAlias, domain_name: str) -> MailAliasSchema:
        return MailAliasSchema(
            id=alias.id,
            domain_id=alias.domain_id,
            source_local=alias.source_local,
            source_email=f"{alias.source_local}@{domain_name}",
            destination=alias.destination,
            enabled=alias.enabled,
            created_at=alias.created_at,
        )
