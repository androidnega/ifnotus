"""PHASE 38M — OTP / HTTP limiter fallback when Redis is unavailable."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.config import Environment
from app.core.exceptions import AppException, ValidationError
from app.services.platform import phone_otp
from app.utils import limit_store
from app.utils.rate_limit import RateLimitMiddleware


@pytest.fixture(autouse=True)
def _clean_limit_store(tmp_path, monkeypatch):
    path = tmp_path / "limit-store.json"
    monkeypatch.setattr(limit_store, "_DEFAULT_PATH", path)
    monkeypatch.setattr(limit_store, "_FALLBACK_PATH", path)
    otp_path = tmp_path / "phone-otp.json"
    monkeypatch.setattr(phone_otp, "DEFAULT_PATH", otp_path)
    monkeypatch.setattr(phone_otp, "FALLBACK_PATH", otp_path)
    yield


def _prod_settings():
    s = MagicMock()
    s.environment = Environment.PRODUCTION
    return s


@pytest.mark.asyncio
async def test_assert_can_request_uses_file_cooldown_when_redis_down() -> None:
    phone = "+233541000099"
    with patch("app.services.platform.phone_otp._redis", new=AsyncMock(return_value=None)):
        await phone_otp.assert_can_request(phone, settings=_prod_settings())
        with pytest.raises(ValidationError, match="wait"):
            await phone_otp.assert_can_request(phone, settings=_prod_settings())


@pytest.mark.asyncio
async def test_create_challenge_uses_file_when_redis_down_in_production() -> None:
    with patch("app.services.platform.phone_otp._redis", new=AsyncMock(return_value=None)):
        ch = await phone_otp.create_challenge("+233541000100", settings=_prod_settings())
        assert ch.challenge_id
        loaded = await phone_otp.get_challenge(ch.challenge_id)
        assert loaded is not None
        assert loaded.phone == "+233541000100"


@pytest.mark.asyncio
async def test_bump_attempts_tracks_in_file_when_redis_down() -> None:
    cid = "test-challenge-id"
    with patch("app.services.platform.phone_otp._redis", new=AsyncMock(return_value=None)):
        counts = [await phone_otp._bump_attempts(cid) for _ in range(3)]
        assert counts == [1, 2, 3]


@pytest.mark.asyncio
async def test_consume_challenge_blocks_after_max_attempts_without_redis() -> None:
    from app.core.exceptions import AuthenticationError

    ch = phone_otp.PhoneOtpChallenge(
        challenge_id="max-att",
        phone="+233541000101",
        code="123456",
        created_at="2099-01-01T00:00:00+00:00",
        expires_at="2099-01-01T01:00:00+00:00",
    )
    with (
        patch("app.services.platform.phone_otp._redis", new=AsyncMock(return_value=None)),
        patch("app.services.platform.phone_otp.get_challenge", new=AsyncMock(return_value=ch)),
        patch("app.services.platform.phone_otp._persist", new=AsyncMock()),
        patch("app.services.platform.phone_otp._bump_attempts", new=AsyncMock(return_value=6)),
    ):
        with pytest.raises(AuthenticationError, match="Too many attempts"):
            await phone_otp.consume_challenge("max-att", "000000")


@pytest.mark.asyncio
async def test_rate_limit_middleware_fail_closed_for_otp_when_stores_unavailable() -> None:
    mw = RateLimitMiddleware(app=MagicMock())
    settings = MagicMock()
    settings.environment = Environment.PRODUCTION
    settings.rate_limit_enabled = True
    request = MagicMock()
    request.url.path = "/api/v1/customers/phone/request-otp"
    request.method = "POST"
    request.app.state.container.config.return_value = settings
    request.app.state.container.redis_client.side_effect = RuntimeError("redis down")

    with patch("app.utils.rate_limit.limit_store.incr", return_value=(False, 1)):
        allowed = await mw._consume(
            request,
            settings,
            ip="1.2.3.4",
            bucket="/api/v1/customers/phone/request-otp",
            limit=8,
            window=60,
        )
        assert allowed is False


@pytest.mark.asyncio
async def test_rate_limit_middleware_uses_file_fallback_when_redis_down() -> None:
    mw = RateLimitMiddleware(app=MagicMock())
    settings = MagicMock()
    settings.environment = Environment.PRODUCTION
    settings.rate_limit_enabled = True
    request = MagicMock()
    request.url.path = "/api/v1/customers/phone/verify-otp"
    request.method = "POST"
    request.app.state.container.config.return_value = settings
    request.app.state.container.redis_client.side_effect = RuntimeError("redis down")

    allowed = await mw._consume(
        request,
        settings,
        ip="9.9.9.9",
        bucket="/api/v1/customers/phone/verify-otp",
        limit=20,
        window=60,
    )
    assert allowed is True
