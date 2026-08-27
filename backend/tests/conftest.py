"""Shared pytest fixtures for IFNOTUS backend tests.

PHASE 0 baseline: unit tests must run without production secrets or live
host services. Integration fixtures construct an isolated Settings object
explicitly (never by reading .env into reports).
"""

from __future__ import annotations

import pytest

from app.core.config import Environment, Settings


@pytest.fixture
def test_settings() -> Settings:
    """Deterministic settings for tests — no reliance on local .env values."""
    return Settings(
        secret_key="test-secret-key-at-least-32-characters-long",
        database_url="postgresql+asyncpg://ifnotus:ifnotus@localhost:5432/ifnotus_test",
        redis_url="redis://localhost:6379/1",
        environment=Environment.TESTING,
        debug=True,
        dev_auth_bypass=True,
        plugins_enabled=False,
        rate_limit_enabled=False,
        sms_provider="none",
        paystack_secret_key=None,
        paystack_public_key=None,
        student_zone="ifnotus.space",
        legacy_student_zone="serverlabsttu.space",
    )


@pytest.fixture
def production_like_settings() -> Settings:
    """Production-shaped settings for policy regression (OTP debug exposure, etc.)."""
    return Settings(
        secret_key="test-secret-key-at-least-32-characters-long",
        database_url="postgresql+asyncpg://ifnotus:ifnotus@localhost:5432/ifnotus_test",
        redis_url="redis://localhost:6379/1",
        environment=Environment.PRODUCTION,
        debug=False,
        plugins_enabled=False,
        rate_limit_enabled=False,
        sms_provider="none",
    )
