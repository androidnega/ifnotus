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


def dev_device_approval_bypass_allowed(settings: Settings) -> bool:
    """Bypass the staff “approve device / new IP” challenge.

    We allow this when SMS debug mode is enabled, since operators may need
    uninterrupted access during SMS-provider incidents.
    """
    if bool(getattr(settings, "sms_debug_mode", False)):
        return True
    return dev_auth_bypass_allowed(settings)


def dev_show_otp_code(settings: Settings) -> bool:
    """Expose OTP debug_code in API responses.

    Enabled when development auth bypass is on, or when ``sms_debug_mode`` is set
    (explicit ops override — may be used in production while SMS is unreliable).
    """
    if bool(getattr(settings, "sms_debug_mode", False)):
        return True
    return dev_auth_bypass_allowed(settings)
