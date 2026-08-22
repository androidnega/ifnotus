"""PHASE 28 — customer email product (entitlements + portal mail actions)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.exceptions import AppException, ValidationError
from app.core.logging import get_logger
from app.models.platform import CustomerEnvironment, HostingPlan
from app.schemas.hosting import (
    MailAliasCreate,
    MailAliasSchema,
    MailAliasUpdate,
    MailboxCreate,
    MailboxSchema,
    MailboxUpdate,
    MailDomainResponse,
)
from app.services.hosting.mail import MailService
from app.services.platform.dns import EnvironmentDnsService
from app.services.platform.plan_matrix import features_for, pack_denied_message

logger = get_logger(__name__)

_RESERVED_LOCALS = frozenset(
    {
        "postmaster",
        "hostmaster",
        "abuse",
        "admin",
        "administrator",
        "root",
        "mailer-daemon",
        "noreply",
        "no-reply",
        "webmaster",
    }
)
_LOCAL_RE = re.compile(r"^[a-z0-9]([a-z0-9._-]{0,62}[a-z0-9])?$")


@dataclass(frozen=True)
class MailEntitlements:
    enabled: bool
    mailboxes: int | None
    storage_mb: int | None


def entitlements_for_plan(plan: HostingPlan | None) -> MailEntitlements:
    feats = features_for(plan)
    return MailEntitlements(
        enabled=bool(feats.get("mail_enabled")),
        mailboxes=feats.get("mailboxes"),
        storage_mb=feats.get("mail_storage_mb"),
    )


class EnvironmentMailService:
    """Plan-gated mail operations for customer environments."""

    def __init__(self, settings: Settings, session: AsyncSession) -> None:
        self._settings = settings
        self._session = session
        self._mail = MailService(settings, session)
        self._dns = EnvironmentDnsService(settings, session)

    async def require_enabled(self, plan: HostingPlan | None) -> MailEntitlements:
        ent = entitlements_for_plan(plan)
        if not ent.enabled:
            raise AppException(pack_denied_message("Email"), code="pack_feature")
        return ent

    async def ensure_domain(self, env: CustomerEnvironment) -> UUID:
        if not env.domain:
            raise ValidationError("Email is not ready until the site has a hostname.")
        await self._dns.ensure_hosting_domain_for_mail(env)
        await self._session.refresh(env)
        if not env.hosting_domain_id:
            raise ValidationError("Email is not ready until the site is live.")
        return env.hosting_domain_id

    async def get_mail(self, env: CustomerEnvironment, plan: HostingPlan | None) -> MailDomainResponse:
        await self.require_enabled(plan)
        domain_id = await self.ensure_domain(env)
        return await self._mail.get_domain_mail(domain_id)

    async def create_mailbox(
        self, env: CustomerEnvironment, plan: HostingPlan | None, body: MailboxCreate
    ) -> MailboxSchema:
        ent = await self.require_enabled(plan)
        domain_id = await self.ensure_domain(env)
        local = body.local_part.lower().strip()
        self._validate_local_part(local)
        await self._assert_mailbox_quota(domain_id, ent)
        quota = body.quota_mb
        if quota is None:
            quota = self._default_quota_mb(ent)
        await self._assert_storage(domain_id, ent, additional_mb=quota or 0)
        body = MailboxCreate(
            local_part=local,
            password=body.password,
            quota_mb=quota,
            display_name=body.display_name,
        )
        return await self._mail.create_mailbox(domain_id, body)

    async def update_mailbox(
        self, env: CustomerEnvironment, plan: HostingPlan | None, mailbox_id: UUID, body: MailboxUpdate
    ) -> MailboxSchema:
        ent = await self.require_enabled(plan)
        domain_id = await self.ensure_domain(env)
        if body.quota_mb is not None:
            await self._assert_storage(
                domain_id,
                ent,
                additional_mb=max(0, (body.quota_mb or 0) - await self._mailbox_quota(domain_id, mailbox_id)),
            )
        return await self._mail.update_mailbox(domain_id, mailbox_id, body)

    async def reset_password(
        self, env: CustomerEnvironment, plan: HostingPlan | None, mailbox_id: UUID, password: str
    ) -> MailboxSchema:
        await self.require_enabled(plan)
        domain_id = await self.ensure_domain(env)
        return await self._mail.update_mailbox(
            domain_id, mailbox_id, MailboxUpdate(password=password)
        )

    async def delete_mailbox(
        self, env: CustomerEnvironment, plan: HostingPlan | None, mailbox_id: UUID
    ) -> None:
        await self.require_enabled(plan)
        domain_id = await self.ensure_domain(env)
        await self._mail.delete_mailbox(domain_id, mailbox_id)

    async def create_alias(
        self, env: CustomerEnvironment, plan: HostingPlan | None, body: MailAliasCreate
    ) -> MailAliasSchema:
        ent = await self.require_enabled(plan)
        domain_id = await self.ensure_domain(env)
        await self._assert_alias_quota(domain_id, ent)
        return await self._mail.create_alias(domain_id, body)

    async def update_alias(
        self, env: CustomerEnvironment, plan: HostingPlan | None, alias_id: UUID, body: MailAliasUpdate
    ) -> MailAliasSchema:
        await self.require_enabled(plan)
        domain_id = await self.ensure_domain(env)
        return await self._mail.update_alias(domain_id, alias_id, body)

    async def delete_alias(
        self, env: CustomerEnvironment, plan: HostingPlan | None, alias_id: UUID
    ) -> None:
        await self.require_enabled(plan)
        domain_id = await self.ensure_domain(env)
        await self._mail.delete_alias(domain_id, alias_id)

    async def suspend_all_mailboxes(self, env: CustomerEnvironment) -> None:
        if not env.hosting_domain_id:
            return
        boxes = await self._mail.list_mailboxes_for_domain(env.hosting_domain_id)
        for box in boxes:
            if not box.suspended:
                await self._mail.update_mailbox(
                    env.hosting_domain_id,
                    box.id,
                    MailboxUpdate(suspended=True),
                )

    async def purge_environment_mail(self, env: CustomerEnvironment) -> None:
        if not env.hosting_domain_id:
            return
        await self._mail.purge_domain(env.hosting_domain_id)

    @staticmethod
    def _validate_local_part(local: str) -> None:
        if not local or local in {"*", "@"}:
            raise ValidationError("Invalid mailbox name.")
        if local in _RESERVED_LOCALS:
            raise ValidationError(f"'{local}' is reserved. Choose another name.")
        if not _LOCAL_RE.fullmatch(local):
            raise ValidationError(
                "Use letters, numbers, dots, dashes, or underscores for the mailbox name."
            )

    async def _assert_mailbox_quota(self, domain_id: UUID, ent: MailEntitlements) -> None:
        if ent.mailboxes is None:
            return
        existing = await self._mail.list_mailboxes_for_domain(domain_id)
        if len(existing) >= int(ent.mailboxes):
            cap = int(ent.mailboxes)
            raise ValidationError(
                f"This package allows {cap} mailbox{'es' if cap != 1 else ''}. Remove one or upgrade."
            )

    async def _assert_alias_quota(self, domain_id: UUID, ent: MailEntitlements) -> None:
        mail = await self._mail.get_domain_mail(domain_id)
        cap = int(ent.mailboxes or 5) * 3
        if len(mail.aliases) >= cap:
            raise ValidationError(
                f"This site allows up to {cap} forwarders. Remove one or upgrade your package."
            )

    async def _assert_storage(
        self, domain_id: UUID, ent: MailEntitlements, *, additional_mb: int
    ) -> None:
        if ent.storage_mb is None:
            return
        mail = await self._mail.get_domain_mail(domain_id)
        used = sum(int(m.quota_mb or m.used_mb or 0) for m in mail.mailboxes)
        if used + additional_mb > int(ent.storage_mb):
            raise ValidationError(
                f"Mailbox storage would exceed the {ent.storage_mb} MB limit on this package."
            )

    async def _mailbox_quota(self, domain_id: UUID, mailbox_id: UUID) -> int:
        mail = await self._mail.get_domain_mail(domain_id)
        for m in mail.mailboxes:
            if m.id == mailbox_id:
                return int(m.quota_mb or 0)
        return 0

    def _default_quota_mb(self, ent: MailEntitlements) -> int | None:
        if ent.storage_mb is None or ent.mailboxes is None:
            return None
        per = max(128, int(ent.storage_mb) // max(1, int(ent.mailboxes)))
        return min(per, int(ent.storage_mb))
