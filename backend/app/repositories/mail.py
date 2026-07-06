"""Mail repository."""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.hosting import MailAlias, Mailbox
from app.repositories.base import BaseRepository


class MailboxRepository(BaseRepository[Mailbox]):
    model = Mailbox

    async def list_for_domain(self, domain_id: UUID) -> list[Mailbox]:
        stmt = select(Mailbox).where(Mailbox.domain_id == domain_id).order_by(Mailbox.local_part)
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def get_by_local(self, domain_id: UUID, local_part: str) -> Mailbox | None:
        stmt = select(Mailbox).where(
            Mailbox.domain_id == domain_id,
            Mailbox.local_part == local_part.lower(),
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()


class MailAliasRepository(BaseRepository[MailAlias]):
    model = MailAlias

    async def list_for_domain(self, domain_id: UUID) -> list[MailAlias]:
        stmt = select(MailAlias).where(MailAlias.domain_id == domain_id).order_by(MailAlias.source_local)
        result = await self._session.execute(stmt)
        return list(result.scalars().all())
