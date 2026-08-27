"""Phone OTP response policy (PHASE 3 hardened)."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch, PropertyMock

import pytest

from app.schemas.platform import CustomerPhoneOtpRequest
from app.services.platform.customers import CustomerService
from app.core.config import Environment


def _patch_otp(*, known_account: bool = False):
    existing = SimpleNamespace(id="cust-1", phone="+233541000000") if known_account else None
    return (
        patch("app.services.platform.phone_otp.assert_can_request", new=AsyncMock()),
        patch(
            "app.services.platform.customers.CustomerService._find_by_phone",
            new=AsyncMock(return_value=existing),
        ),
        patch(
            "app.services.platform.customers.CustomerService._email_for_phone",
            new=AsyncMock(return_value=None),
        ),
    )


@pytest.mark.asyncio
async def test_request_otp_exposes_debug_code_in_dev_mode(test_settings) -> None:
    test_settings.dev_auth_bypass = True
    test_settings.environment = Environment.DEVELOPMENT
    svc = CustomerService(test_settings, MagicMock())
    challenge = SimpleNamespace(challenge_id="ch_1", code="123456", phone="+233541000000")
    p1, p2, p3 = _patch_otp(known_account=True)

    with (
        p1,
        p2,
        p3,
        patch("app.services.platform.phone_otp.create_challenge", new=AsyncMock(return_value=challenge)),
        patch(
            "app.services.platform.delivery.MessageDelivery.sms_enabled",
            new_callable=PropertyMock,
            return_value=True,
        ),
        patch(
            "app.services.platform.delivery.MessageDelivery.email_enabled",
            new_callable=PropertyMock,
            return_value=False,
        ),
        patch(
            "app.services.platform.delivery.MessageDelivery.send_sms",
            return_value={"ok": True},
        ),
    ):
        resp = await svc.request_phone_otp(CustomerPhoneOtpRequest(phone="+233541000000"))

    assert resp.sms_sent is True
    assert resp.debug_code == "123456"


@pytest.mark.asyncio
async def test_request_otp_hides_debug_code_when_known_account_and_sms_ok(
    production_like_settings,
) -> None:
    svc = CustomerService(production_like_settings, MagicMock())
    challenge = SimpleNamespace(challenge_id="ch_2", code="654321", phone="+233541000001")
    p1, p2, p3 = _patch_otp(known_account=True)

    with (
        p1,
        p2,
        p3,
        patch("app.services.platform.phone_otp.create_challenge", new=AsyncMock(return_value=challenge)),
        patch(
            "app.services.platform.delivery.MessageDelivery.sms_enabled",
            new_callable=PropertyMock,
            return_value=True,
        ),
        patch(
            "app.services.platform.delivery.MessageDelivery.email_enabled",
            new_callable=PropertyMock,
            return_value=False,
        ),
        patch(
            "app.services.platform.delivery.MessageDelivery.send_sms",
            return_value={"ok": True},
        ),
    ):
        resp = await svc.request_phone_otp(CustomerPhoneOtpRequest(phone="+233541000001"))

    assert resp.sms_sent is True
    assert resp.debug_code is None


@pytest.mark.asyncio
async def test_new_phone_shows_code_without_claiming_sms(production_like_settings) -> None:
    """Unregistered numbers must show the OTP on-screen — never pretend SMS was sent."""
    svc = CustomerService(production_like_settings, MagicMock())
    challenge = SimpleNamespace(challenge_id="ch_new", code="777888", phone="+233248069639")
    send_sms = MagicMock(return_value={"ok": True})
    p1, p2, p3 = _patch_otp(known_account=False)

    with (
        p1,
        p2,
        p3,
        patch("app.services.platform.phone_otp.create_challenge", new=AsyncMock(return_value=challenge)),
        patch(
            "app.services.platform.delivery.MessageDelivery.sms_enabled",
            new_callable=PropertyMock,
            return_value=True,
        ),
        patch("app.services.platform.delivery.MessageDelivery.send_sms", send_sms),
    ):
        resp = await svc.request_phone_otp(CustomerPhoneOtpRequest(phone="0248069639"))

    send_sms.assert_not_called()
    assert resp.sms_sent is False
    assert resp.debug_code == "777888"
    assert "not linked" in resp.message.lower()
    assert "sms" not in resp.message.lower() or "shown" in resp.message.lower()


@pytest.mark.asyncio
async def test_production_never_returns_otp_when_known_account_and_sms_unconfigured(
    production_like_settings,
) -> None:
    production_like_settings.sms_debug_mode = False
    svc = CustomerService(production_like_settings, MagicMock())
    challenge = SimpleNamespace(challenge_id="ch_3", code="999888", phone="+233541000002")
    p1, p2, p3 = _patch_otp(known_account=True)

    with (
        p1,
        p2,
        p3,
        patch("app.services.platform.phone_otp.create_challenge", new=AsyncMock(return_value=challenge)),
        patch(
            "app.services.platform.delivery.MessageDelivery.sms_enabled",
            new_callable=PropertyMock,
            return_value=False,
        ),
        patch(
            "app.services.platform.delivery.MessageDelivery.email_enabled",
            new_callable=PropertyMock,
            return_value=False,
        ),
        patch(
            "app.services.platform.delivery.MessageDelivery.send_sms",
            return_value={"ok": False},
        ),
    ):
        resp = await svc.request_phone_otp(CustomerPhoneOtpRequest(phone="+233541000002"))

    assert resp.sms_sent is False
    assert resp.debug_code is None
    assert "could not deliver" in resp.message.lower() or "try again" in resp.message.lower()


@pytest.mark.asyncio
async def test_sms_debug_mode_returns_code_without_sending(production_like_settings) -> None:
    production_like_settings.sms_debug_mode = True
    svc = CustomerService(production_like_settings, MagicMock())
    challenge = SimpleNamespace(challenge_id="ch_4", code="112233", phone="+233541000003")
    send_sms = MagicMock(return_value={"ok": True})
    p1, p2, p3 = _patch_otp(known_account=True)

    with (
        p1,
        p2,
        p3,
        patch("app.services.platform.phone_otp.create_challenge", new=AsyncMock(return_value=challenge)),
        patch("app.services.platform.delivery.MessageDelivery.send_sms", send_sms),
    ):
        resp = await svc.request_phone_otp(CustomerPhoneOtpRequest(phone="+233541000003"))

    send_sms.assert_not_called()
    assert resp.sms_sent is False
    assert resp.debug_code == "112233"
    assert "debug" in resp.message.lower()


def test_otp_module_exports_abuse_controls() -> None:
    from app.services.platform import phone_otp

    assert phone_otp.MAX_ATTEMPTS == 5
    assert phone_otp.RESEND_COOLDOWN_SECONDS == 45
    assert callable(phone_otp.assert_can_request)
