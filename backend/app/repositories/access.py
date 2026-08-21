"""Repositories for access attempts, IP blacklist, firewall, and action audit."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import Select, delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.access import (
    AccessAttempt,
    BlockedAction,
    FirewallRule,
    IpBlacklist,
    SystemActionLog,
)


class AccessAttemptRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, attempt: AccessAttempt) -> AccessAttempt:
        self._session.add(attempt)
        await self._session.flush()
        return attempt

    async def list_recent(self, *, limit: int = 100) -> list[AccessAttempt]:
        stmt: Select[tuple[AccessAttempt]] = (
            select(AccessAttempt).order_by(AccessAttempt.attempted_at.desc()).limit(limit)
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def list_for_ip(self, ip: str, *, limit: int = 20) -> list[AccessAttempt]:
        stmt = (
            select(AccessAttempt)
            .where(AccessAttempt.ip_address == ip)
            .order_by(AccessAttempt.attempted_at.desc())
            .limit(limit)
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def clear_all(self) -> int:
        result = await self._session.execute(delete(AccessAttempt))
        await self._session.flush()
        return int(result.rowcount or 0)


class IpBlacklistRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_ip(self, ip: str) -> IpBlacklist | None:
        stmt = select(IpBlacklist).where(IpBlacklist.ip_address == ip)
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_id(self, entry_id: UUID) -> IpBlacklist | None:
        stmt = select(IpBlacklist).where(IpBlacklist.id == entry_id)
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_active(self) -> list[IpBlacklist]:
        stmt = (
            select(IpBlacklist)
            .where(IpBlacklist.is_active.is_(True))
            .order_by(IpBlacklist.blocked_at.desc())
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def list_all(self, *, limit: int = 100) -> list[IpBlacklist]:
        stmt = select(IpBlacklist).order_by(IpBlacklist.blocked_at.desc()).limit(limit)
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def upsert_block(
        self,
        *,
        ip: str,
        reason: str,
        failed_attempt_count: int,
        blocked_until: datetime | None,
        fingerprint: str | None,
        user_agent: str | None,
    ) -> IpBlacklist:
        entry = await self.get_by_ip(ip)
        if entry is None:
            entry = IpBlacklist(
                ip_address=ip,
                reason=reason,
                failed_attempt_count=failed_attempt_count,
                blocked_until=blocked_until,
                is_active=True,
                last_device_fingerprint=fingerprint,
                last_user_agent=user_agent,
            )
            self._session.add(entry)
        else:
            from datetime import UTC

            entry.reason = reason
            entry.failed_attempt_count = failed_attempt_count
            entry.blocked_until = blocked_until
            entry.is_active = True
            entry.unlocked_at = None
            entry.unlocked_by_user_id = None
            entry.unlock_note = None
            entry.last_device_fingerprint = fingerprint
            entry.last_user_agent = user_agent
            entry.blocked_at = datetime.now(UTC)
        await self._session.flush()
        return entry

    async def unlock(
        self,
        entry: IpBlacklist,
        *,
        unlocked_by: UUID | None,
        note: str | None,
    ) -> IpBlacklist:
        from datetime import UTC

        entry.is_active = False
        entry.unlocked_at = datetime.now(UTC)
        entry.unlocked_by_user_id = unlocked_by
        entry.unlock_note = note
        await self._session.flush()
        return entry


class FirewallRuleRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_all(self) -> list[FirewallRule]:
        stmt = select(FirewallRule).order_by(FirewallRule.created_at.desc())
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def list_enabled(self) -> list[FirewallRule]:
        stmt = select(FirewallRule).where(FirewallRule.enabled.is_(True))
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def create(self, rule: FirewallRule) -> FirewallRule:
        self._session.add(rule)
        await self._session.flush()
        return rule

    async def get(self, rule_id: UUID) -> FirewallRule | None:
        result = await self._session.execute(select(FirewallRule).where(FirewallRule.id == rule_id))
        return result.scalar_one_or_none()

    async def delete(self, rule: FirewallRule) -> None:
        await self._session.delete(rule)
        await self._session.flush()


class BlockedActionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_all(self) -> list[BlockedAction]:
        stmt = select(BlockedAction).order_by(BlockedAction.action_key.asc())
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def list_enabled_keys(self) -> set[str]:
        stmt = select(BlockedAction.action_key).where(BlockedAction.enabled.is_(True))
        result = await self._session.execute(stmt)
        return {row[0] for row in result.all()}

    async def get_by_key(self, action_key: str) -> BlockedAction | None:
        result = await self._session.execute(
            select(BlockedAction).where(BlockedAction.action_key == action_key)
        )
        return result.scalar_one_or_none()

    async def upsert(
        self,
        *,
        action_key: str,
        label: str | None,
        reason: str | None,
        enabled: bool,
        created_by: UUID | None,
    ) -> BlockedAction:
        entry = await self.get_by_key(action_key)
        if entry is None:
            entry = BlockedAction(
                action_key=action_key,
                label=label,
                reason=reason,
                enabled=enabled,
                created_by_user_id=created_by,
            )
            self._session.add(entry)
        else:
            entry.label = label or entry.label
            entry.reason = reason
            entry.enabled = enabled
        await self._session.flush()
        return entry

    async def delete_by_key(self, action_key: str) -> int:
        result = await self._session.execute(
            delete(BlockedAction).where(BlockedAction.action_key == action_key)
        )
        return int(result.rowcount or 0)


class SystemActionLogRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, log: SystemActionLog) -> SystemActionLog:
        self._session.add(log)
        await self._session.flush()
        return log

    async def list_recent(self, *, limit: int = 200) -> list[SystemActionLog]:
        stmt = select(SystemActionLog).order_by(SystemActionLog.occurred_at.desc()).limit(limit)
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def clear_all(self) -> int:
        result = await self._session.execute(delete(SystemActionLog))
        await self._session.flush()
        return int(result.rowcount or 0)
