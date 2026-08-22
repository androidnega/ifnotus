"""Development-mode helpers — auth bypass only during active non-production development."""

from __future__ import annotations

from app.core.config import Environment, Settings


def dev_auth_bypass_allowed(settings: Settings) -> bool:
    """Allow OTP/admin auth shortcuts only while development is explicitly in progress.

    Never enabled when ``environment=production`` — even if DEBUG or DEV_AUTH_BYPASS is set.
    """
    if settings.environment == Environment.PRODUCTION:
        return False
    return bool(getattr(settings, "dev_auth_bypass", False))


def dev_show_otp_code(settings: Settings) -> bool:
    """Expose OTP debug_code in API responses during active development only."""
    return dev_auth_bypass_allowed(settings)
