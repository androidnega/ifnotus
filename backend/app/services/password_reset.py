"""Password reset request / confirm."""

from __future__ import annotations

import hashlib
import secrets
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.exceptions import AppException
from app.core.logging import get_logger
from app.core.security import hash_password
from app.models.password_reset import PasswordResetToken
from app.models.user import User
from app.services.platform.delivery import MessageDelivery

logger = get_logger(__name__)

RESET_TTL_MINUTES = 60
GENERIC_OK = "If an account exists for that email, a reset link has been sent."


class PasswordResetService:
    def __init__(self, settings: Settings, session: AsyncSession) -> None:
        self._settings = settings
        self._session = session

    @staticmethod
    def _hash_token(raw: str) -> str:
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    async def request_reset(self, email: str, *, ip: str | None = None) -> str:
        """Always return a generic message (do not leak whether the email exists)."""
        email_norm = email.strip().lower()
        result = await self._session.execute(
            select(User).where(User.email == email_norm, User.deleted_at.is_(None))
        )
        user = result.scalar_one_or_none()
        if user is None or not user.is_active:
            return GENERIC_OK

        # Invalidate outstanding tokens for this user
        await self._session.execute(
            update(PasswordResetToken)
            .where(
                PasswordResetToken.user_id == user.id,
                PasswordResetToken.used_at.is_(None),
            )
            .values(used_at=datetime.now(UTC))
        )

        raw = secrets.token_urlsafe(32)
        row = PasswordResetToken(
            user_id=user.id,
            token_hash=self._hash_token(raw),
            expires_at=datetime.now(UTC) + timedelta(minutes=RESET_TTL_MINUTES),
            requested_ip=ip,
        )
        self._session.add(row)
        await self._session.flush()

        base = (self._settings.customer_portal_url or "https://ifnotus.space").rstrip("/")
        link = f"{base}/reset-password?token={raw}"
        delivery = MessageDelivery(self._settings)
        result_mail = delivery.send_email(
            to=user.email,
            subject="IFNOTUS password reset",
            body=(
                "We received a request to reset your IFNOTUS password.\n\n"
                f"Open this link within {RESET_TTL_MINUTES} minutes:\n{link}\n\n"
                "If you did not request this, you can ignore this email.\n"
            ),
        )
        if not result_mail.get("ok") and not result_mail.get("skipped"):
            logger.warning("password_reset_email_failed", user_id=str(user.id), result=result_mail)
        elif result_mail.get("skipped"):
            # Dev / no SMTP: still allow ops to find token in logs (never in production responses)
            logger.info(
                "password_reset_issued_no_smtp",
                user_id=str(user.id),
                hint="Configure SMTP_HOST to email reset links",
            )
        return GENERIC_OK

    async def confirm_reset(self, token: str, new_password: str) -> str:
        raw = (token or "").strip()
        if len(raw) < 20:
            raise AppException("Invalid or expired reset token.")
        if len(new_password) < 8:
            raise AppException("Password must be at least 8 characters.")

        digest = self._hash_token(raw)
        result = await self._session.execute(
            select(PasswordResetToken).where(PasswordResetToken.token_hash == digest)
        )
        row = result.scalar_one_or_none()
        now = datetime.now(UTC)
        if row is None or row.used_at is not None:
            raise AppException("Invalid or expired reset token.")
        expires = row.expires_at
        if expires.tzinfo is None:
            expires = expires.replace(tzinfo=UTC)
        if expires < now:
            raise AppException("Invalid or expired reset token.")

        user = await self._session.get(User, row.user_id)
        if user is None or not user.is_active:
            raise AppException("Invalid or expired reset token.")

        user.hashed_password = hash_password(new_password)
        row.used_at = now
        # Invalidate any other open tokens
        await self._session.execute(
            update(PasswordResetToken)
            .where(
                PasswordResetToken.user_id == user.id,
                PasswordResetToken.used_at.is_(None),
                PasswordResetToken.id != row.id,
            )
            .values(used_at=now)
        )
        await self._session.flush()
        logger.info("password_reset_completed", user_id=str(user.id))
        return "Password updated. You can sign in with your new password."
