"""Terminal audit repository."""

from uuid import UUID

from sqlalchemy import select

from app.models.hosting import TerminalAuditLog
from app.repositories.base import BaseRepository


class TerminalAuditRepository(BaseRepository[TerminalAuditLog]):
    model = TerminalAuditLog

    async def list_recent(self, *, limit: int = 50) -> list[TerminalAuditLog]:
        stmt = select(TerminalAuditLog).order_by(TerminalAuditLog.executed_at.desc()).limit(limit)
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def list_for_user(self, user_id: UUID, *, limit: int = 50) -> list[TerminalAuditLog]:
        stmt = (
            select(TerminalAuditLog)
            .where(TerminalAuditLog.user_id == user_id)
            .order_by(TerminalAuditLog.executed_at.desc())
            .limit(limit)
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())
