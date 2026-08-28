"""Development-mode auth bypass policy."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.config import Environment
from app.core.dev_mode import dev_auth_bypass_allowed, dev_show_otp_code
from app.core.exceptions import AuthenticationError
from app.services.platform import phone_otp


def test_dev_bypass_blocked_in_production_even_with_flag() -> None:
    settings = MagicMock(
        environment=Environment.PRODUCTION,
        dev_auth_bypass=True,
        sms_debug_mode=False,
    )
    assert dev_auth_bypass_allowed(settings) is False
    assert dev_show_otp_code(settings) is False


def test_dev_bypass_allowed_in_development() -> None:
    settings = MagicMock(environment=Environment.DEVELOPMENT, dev_auth_bypass=True)
    assert dev_auth_bypass_allowed(settings) is True


@pytest.mark.asyncio
async def test_phone_otp_dev_accepts_any_code() -> None:
    ch = phone_otp.PhoneOtpChallenge(
        challenge_id="abc",
        phone="+233541000000",
        code="123456",
        created_at="2026-01-01T00:00:00+00:00",
        expires_at="2099-01-01T00:00:00+00:00",
    )
    settings = MagicMock(environment=Environment.DEVELOPMENT, dev_auth_bypass=True)

    with (
        patch("app.services.platform.phone_otp.get_challenge", new=AsyncMock(return_value=ch)),
        patch("app.services.platform.phone_otp._bump_attempts", new=AsyncMock(return_value=1)),
        patch("app.services.platform.phone_otp._persist", new=AsyncMock()),
        patch("app.core.config.get_settings", return_value=settings),
    ):
        consumed = await phone_otp.consume_challenge("abc", "000000")
        assert consumed.consumed is True


@pytest.mark.asyncio
async def test_phone_otp_production_rejects_wrong_code() -> None:
    ch = phone_otp.PhoneOtpChallenge(
        challenge_id="abc",
        phone="+233541000000",
        code="123456",
        created_at="2026-01-01T00:00:00+00:00",
        expires_at="2099-01-01T00:00:00+00:00",
    )
    settings = MagicMock(environment=Environment.PRODUCTION, dev_auth_bypass=False)

    with (
        patch("app.services.platform.phone_otp.get_challenge", new=AsyncMock(return_value=ch)),
        patch("app.services.platform.phone_otp._bump_attempts", new=AsyncMock(return_value=1)),
        patch("app.core.config.get_settings", return_value=settings),
        pytest.raises(AuthenticationError, match="Invalid verification code"),
    ):
        await phone_otp.consume_challenge("abc", "000000")


@pytest.mark.asyncio
async def test_admin_login_skips_ip_challenge_in_dev_mode() -> None:
    from app.schemas.auth import LoginRequest
    from app.services.auth import AuthService

    settings = MagicMock(
        environment=Environment.DEVELOPMENT,
        dev_auth_bypass=True,
        admin_lockdown_enabled=True,
    )
    user = MagicMock(
        is_active=True,
        is_superuser=True,
        roles=["admin"],
        totp_enabled=False,
        totp_secret=None,
        id="00000000-0000-0000-0000-000000000001",
        get_roles=lambda: ["admin"],
    )
    users = AsyncMock()
    users.get_by_email = AsyncMock(return_value=user)
    access = AsyncMock()
    access.assert_ip_allowed = AsyncMock()
    access._is_trusted_admin_ip = AsyncMock(return_value=False)

    svc = AuthService(settings, users, access)
    svc._issue_session = AsyncMock(return_value=MagicMock(status="ok"))

    with patch("app.services.auth.verify_password", return_value=True):
        resp = await svc.login(
            LoginRequest(email="admin@ifnotus.space", password="secretpass"),
            None,
        )

    assert resp.status == "ok"
    access._is_trusted_admin_ip.assert_not_called()
