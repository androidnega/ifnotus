"""Domain repository."""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.hosting import Domain
from app.repositories.base import BaseRepository


class DomainRepository(BaseRepository[Domain]):
    model = Domain

    async def get_by_name(self, name: str) -> Domain | None:
        stmt = select(Domain).where(Domain.name == name.lower())
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_all(self) -> list[Domain]:
        stmt = select(Domain).order_by(Domain.name)
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def list_by_parent(self, parent_id: UUID) -> list[Domain]:
        stmt = select(Domain).where(Domain.parent_domain_id == parent_id)
        result = await self._session.execute(stmt)
        return list(result.scalars().all())
