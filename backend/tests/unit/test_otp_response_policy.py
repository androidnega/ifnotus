"""Phone OTP response policy regression (PHASE 0 — documents current behavior).

PHASE 3 will harden production so debug_code is never returned when
settings.debug is false. These tests lock today's contract so purchase-entry
regressions are visible before that fix.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.schemas.platform import CustomerPhoneOtpRequest
from app.services.platform.customers import CustomerService


@pytest.mark.asyncio
async def test_request_otp_exposes_debug_code_when_debug_true(test_settings) -> None:
    test_settings.debug = True
    svc = CustomerService(test_settings, MagicMock())
    challenge = SimpleNamespace(challenge_id="ch_1", code="123456", phone="+233541000000")

    with (
        patch("app.services.platform.phone_otp.create_challenge", new=AsyncMock(return_value=challenge)),
        patch(
            "app.services.platform.delivery.MessageDelivery.send_sms",
            return_value={"ok": True},
        ),
    ):
        resp = await svc.request_phone_otp(CustomerPhoneOtpRequest(phone="+233541000000"))

    assert resp.sms_sent is True
    assert resp.debug_code == "123456"
    assert resp.challenge_id == "ch_1"


@pytest.mark.asyncio
async def test_request_otp_hides_debug_code_when_sms_ok_and_debug_false(
    production_like_settings,
) -> None:
    svc = CustomerService(production_like_settings, MagicMock())
    challenge = SimpleNamespace(challenge_id="ch_2", code="654321", phone="+233541000001")

    with (
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
async def test_request_otp_currently_exposes_code_when_sms_fails_even_if_not_debug(
    production_like_settings,
) -> None:
    """Known P0 baseline: show_debug = debug OR not sms_sent.

    PHASE 3 must change this so production never returns debug_code.
    """
    svc = CustomerService(production_like_settings, MagicMock())
    challenge = SimpleNamespace(challenge_id="ch_3", code="999888", phone="+233541000002")

    with (
        patch("app.services.platform.phone_otp.create_challenge", new=AsyncMock(return_value=challenge)),
        patch(
            "app.services.platform.delivery.MessageDelivery.send_sms",
            return_value={"ok": False},
        ),
    ):
        resp = await svc.request_phone_otp(CustomerPhoneOtpRequest(phone="+233541000002"))

    assert resp.sms_sent is False
    assert resp.debug_code == "999888"


def test_otp_module_exports_abuse_controls() -> None:
    from app.services.platform import phone_otp

    assert phone_otp.MAX_ATTEMPTS == 5
    assert phone_otp.RESEND_COOLDOWN_SECONDS == 45
    assert phone_otp.OTP_TTL_MINUTES == 10
    assert phone_otp.CODE_LENGTH == 6
