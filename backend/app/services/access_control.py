"""Access control: IP blacklist, login attempt tracing, device fingerprinting."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppException
from app.core.logging import get_logger
from app.models.access import AccessAttempt
from app.repositories.access import AccessAttemptRepository, IpBlacklistRepository

logger = get_logger(__name__)

CONSECUTIVE_FAIL_LIMIT = 3
AUTO_UNLOCK_HOURS = 24


class IpBlockedError(AppException):
    status_code = 403
    code = "ip_blocked"
    message = "Access from this IP has been blocked due to repeated failed login attempts."


@dataclass(frozen=True)
class AccessContext:
    ip_address: str
    user_agent: str | None = None
    device_fingerprint: str | None = None
    request_id: str | None = None


class AccessControlService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._attempts = AccessAttemptRepository(session)
        self._blacklist = IpBlacklistRepository(session)

    async def assert_ip_allowed(self, ctx: AccessContext) -> None:
        entry = await self._blacklist.get_by_ip(ctx.ip_address)
        if entry is None or not entry.is_active:
            return

        now = datetime.now(UTC)
        if entry.blocked_until and entry.blocked_until <= now:
            await self._blacklist.unlock(
                entry,
                unlocked_by=None,
                note="system auto-expiry",
            )
            await self._session.commit()
            logger.info("ip_auto_unlocked", ip=ctx.ip_address)
            return

        raise IpBlockedError(
            "This IP address is blacklisted. Contact an administrator to unlock access.",
            details={
                "ip_address": ctx.ip_address,
                "blocked_at": entry.blocked_at.isoformat() if entry.blocked_at else None,
                "blocked_until": entry.blocked_until.isoformat() if entry.blocked_until else None,
            },
        )

    async def record_probe(self, ctx: AccessContext) -> None:
        await self._record(
            ctx,
            event_type="access_probe",
            success=False,
            failure_reason="page_view",
            username_or_email=None,
            user_id=None,
        )

    async def record_login_success(
        self,
        ctx: AccessContext,
        *,
        username_or_email: str,
        user_id: UUID,
    ) -> None:
        await self._record(
            ctx,
            event_type="login_success",
            success=True,
            failure_reason=None,
            username_or_email=username_or_email,
            user_id=user_id,
        )

    async def record_login_failure(
        self,
        ctx: AccessContext,
        *,
        username_or_email: str,
        reason: str,
        user_id: UUID | None = None,
    ) -> None:
        await self._record(
            ctx,
            event_type="login_failure",
            success=False,
            failure_reason=reason,
            username_or_email=username_or_email,
            user_id=user_id,
        )
        await self._maybe_blacklist(ctx)

    async def _maybe_blacklist(self, ctx: AccessContext) -> None:
        recent = await self._attempts.list_for_ip(ctx.ip_address, limit=20)
        consecutive = 0
        for attempt in recent:
            if attempt.event_type != "login_failure":
                if attempt.event_type == "login_success":
                    break
                continue
            consecutive += 1
            if consecutive >= CONSECUTIVE_FAIL_LIMIT:
                break

        if consecutive < CONSECUTIVE_FAIL_LIMIT:
            return

        blocked_until = datetime.now(UTC) + timedelta(hours=AUTO_UNLOCK_HOURS)
        await self._blacklist.upsert_block(
            ip=ctx.ip_address,
            reason="consecutive_failed_logins",
            failed_attempt_count=consecutive,
            blocked_until=blocked_until,
            fingerprint=ctx.device_fingerprint,
            user_agent=ctx.user_agent,
        )
        await self._session.commit()
        logger.warning(
            "ip_blacklisted",
            ip=ctx.ip_address,
            consecutive=consecutive,
            fingerprint=ctx.device_fingerprint,
        )

    async def _record(
        self,
        ctx: AccessContext,
        *,
        event_type: str,
        success: bool,
        failure_reason: str | None,
        username_or_email: str | None,
        user_id: UUID | None,
    ) -> AccessAttempt:
        attempt = AccessAttempt(
            ip_address=ctx.ip_address,
            username_or_email=username_or_email,
            user_id=user_id,
            event_type=event_type,
            success=success,
            failure_reason=failure_reason,
            device_fingerprint=ctx.device_fingerprint,
            user_agent=(ctx.user_agent or "")[:512] or None,
            request_id=ctx.request_id,
        )
        saved = await self._attempts.create(attempt)
        await self._session.commit()
        logger.info(
            "access_trace",
            event_type=event_type,
            ip=ctx.ip_address,
            fingerprint=ctx.device_fingerprint,
            success=success,
            reason=failure_reason,
            identity=username_or_email,
        )
        return saved

    async def list_blacklist(self, *, active_only: bool = True):
        if active_only:
            return await self._blacklist.list_active()
        return await self._blacklist.list_all()

    async def unlock_ip(
        self,
        entry_id: UUID,
        *,
        unlocked_by: UUID | None,
        note: str | None = None,
    ):
        entry = await self._blacklist.get_by_id(entry_id)
        if entry is None:
            from app.core.exceptions import NotFoundError

            raise NotFoundError("Blacklist entry not found.")
        entry = await self._blacklist.unlock(
            entry,
            unlocked_by=unlocked_by,
            note=note or "unlocked by administrator",
        )
        await self._session.commit()
        return entry

    async def list_attempts(self, *, limit: int = 100):
        return await self._attempts.list_recent(limit=limit)
