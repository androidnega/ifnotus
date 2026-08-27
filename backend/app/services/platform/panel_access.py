"""Customer control-panel shortcut URLs.

Tenant sites always use path-based entry:
  https://{domain}/cpanel
  https://{domain}/mail

Only the IFNOTUS staff/admin surface uses cpanel.ifnotus.space.
"""

from __future__ import annotations

from urllib.parse import quote

from app.services.platform.student_hostname import (
    LEGACY_STUDENT_ZONE,
    STUDENT_ZONE,
    is_student_hostname,
    resolve_legacy_student_zone,
    resolve_student_zone,
)

STAFF_PANEL_HOST = "cpanel.ifnotus.space"


def is_platform_hostname(domain: str | None, *, settings: object | None = None) -> bool:
    """True for control-plane and managed student/project hostnames."""
    host = (domain or "").lower().rstrip(".")
    if not host:
        return False
    if host == "ifnotus.space" or host.endswith(".ifnotus.space"):
        return True
    active = resolve_student_zone(settings)
    legacy = resolve_legacy_student_zone(settings)
    for zone in {active, legacy, STUDENT_ZONE, LEGACY_STUDENT_ZONE}:
        if host == zone or host.endswith(f".{zone}"):
            return True
    return is_student_hostname(host, settings=settings)


def control_panel_hostname(domain: str | None, *, settings: object | None = None) -> str | None:
    """Legacy helper — tenant panels no longer use cpanel.<domain>.

    Always returns None so callers fall through to path-based /cpanel.
    Staff panel remains cpanel.ifnotus.space (handled separately in the SPA).
    """
    _ = domain, settings
    return None


def site_cpanel_url(domain: str | None) -> str | None:
    """Public tenant panel entry: https://{domain}/cpanel."""
    host = (domain or "").lower().rstrip(".")
    if host.startswith("www."):
        host = host[4:]
    if not host or "." not in host:
        return None
    if host in {"ifnotus.space", STAFF_PANEL_HOST, "mail.ifnotus.space"}:
        return None
    if host.startswith("cpanel.") and host != STAFF_PANEL_HOST:
        host = host[len("cpanel.") :]
    return f"https://{host}/cpanel"


def site_mail_url(domain: str | None) -> str | None:
    """Public tenant webmail entry: https://{domain}/mail (except mail.ifnotus.space)."""
    host = (domain or "").lower().rstrip(".")
    if host.startswith("www."):
        host = host[4:]
    if not host or "." not in host:
        return None
    if host in {"ifnotus.space", STAFF_PANEL_HOST}:
        return "https://mail.ifnotus.space/"
    if host.startswith("cpanel.") and host != STAFF_PANEL_HOST:
        host = host[len("cpanel.") :]
    return f"https://{host}/mail"


def control_panel_url(domain: str | None, portal_base: str = "https://ifnotus.space") -> str:
    """Best URL to open the tenant Hosting Panel for this site."""
    base = (portal_base or "https://ifnotus.space").rstrip("/")
    url = site_cpanel_url(domain)
    return url or f"{base}/account"


def panel_sso_url(
    hostname: str,
    portal_base: str = "https://ifnotus.space",
    *,
    tab: str | None = None,
) -> str:
    """Portal SSO handoff used by nginx /cpanel → API redirect (no redirect loop)."""
    base = (portal_base or "https://ifnotus.space").rstrip("/")
    host = (hostname or "").strip().lower().rstrip(".")
    if host.startswith("www."):
        host = host[4:]
    if not host:
        return f"{base}/account"
    q = f"host={quote(host)}"
    if tab:
        q = f"{q}&tab={quote(tab)}"
    return f"{base}/go/hosting?{q}"
