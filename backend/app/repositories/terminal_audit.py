"""Terminal audit repository."""

from uuid import UUID

from sqlalchemy import delete, select

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

    async def clear_all(self) -> int:
        """Delete all terminal audit rows. Returns number of rows removed."""
        result = await self._session.execute(delete(TerminalAuditLog))
        await self._session.flush()
        return int(result.rowcount or 0)