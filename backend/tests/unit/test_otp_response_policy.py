"""Phone OTP response policy (PHASE 3 hardened)."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.schemas.platform import CustomerPhoneOtpRequest
from app.services.platform.customers import CustomerService
from app.core.config import Environment


@pytest.mark.asyncio
async def test_request_otp_exposes_debug_code_in_dev_mode(test_settings) -> None:
    test_settings.dev_auth_bypass = True
    test_settings.environment = Environment.DEVELOPMENT
    svc = CustomerService(test_settings, MagicMock())
    challenge = SimpleNamespace(challenge_id="ch_1", code="123456", phone="+233541000000")

    with (
        patch("app.services.platform.phone_otp.assert_can_request", new=AsyncMock()),
        patch("app.services.platform.phone_otp.create_challenge", new=AsyncMock(return_value=challenge)),
        patch(
            "app.services.platform.delivery.MessageDelivery.send_sms",
            return_value={"ok": True},
        ),
    ):
        resp = await svc.request_phone_otp(CustomerPhoneOtpRequest(phone="+233541000000"))

    assert resp.sms_sent is True
    assert resp.debug_code == "123456"


@pytest.mark.asyncio
async def test_request_otp_hides_debug_code_when_sms_ok_and_debug_false(
    production_like_settings,
) -> None:
    svc = CustomerService(production_like_settings, MagicMock())
    challenge = SimpleNamespace(challenge_id="ch_2", code="654321", phone="+233541000001")

    with (
        patch("app.services.platform.phone_otp.assert_can_request", new=AsyncMock()),
        patch("app.services.platform.phone_otp.create_challenge", new=AsyncMock(return_value=challenge)),
        patch(
            "app.services.platform.delivery.MessageDelivery.send_sms",
            return_value={"ok": True},
        ),
    ):
        resp = await svc.request_phone_otp(CustomerPhoneOtpRequest(phone="+233541000001"))

    assert resp.sms_sent is True
    assert resp.debug_code is None


@pytest.mark.asyncio
async def test_production_never_returns_otp_when_sms_fails(production_like_settings) -> None:
    svc = CustomerService(production_like_settings, MagicMock())
    challenge = SimpleNamespace(challenge_id="ch_3", code="999888", phone="+233541000002")

    with (
        patch("app.services.platform.phone_otp.assert_can_request", new=AsyncMock()),
        patch("app.services.platform.phone_otp.create_challenge", new=AsyncMock(return_value=challenge)),
        patch(
            "app.services.platform.delivery.MessageDelivery.send_sms",
            return_value={"ok": False},
        ),
    ):
        resp = await svc.request_phone_otp(CustomerPhoneOtpRequest(phone="+233541000002"))

    assert resp.sms_sent is False
    assert resp.debug_code is None
    assert "could not deliver" in resp.message.lower() or "try again" in resp.message.lower()


def test_otp_module_exports_abuse_controls() -> None:
    from app.services.platform import phone_otp

    assert phone_otp.MAX_ATTEMPTS == 5
    assert phone_otp.RESEND_COOLDOWN_SECONDS == 45
    assert callable(phone_otp.assert_can_request)
