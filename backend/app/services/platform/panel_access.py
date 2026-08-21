"""Customer control-panel shortcut URLs (cPanel-style cpanel.domain → /account)."""

from __future__ import annotations

from app.services.platform.student_hostname import (
    LEGACY_STUDENT_ZONE,
    STUDENT_ZONE,
    is_student_hostname,
    resolve_legacy_student_zone,
    resolve_student_zone,
)


def is_platform_hostname(domain: str | None, *, settings: object | None = None) -> bool:
    """True for control-plane and managed student/project hostnames.

    Custom customer domains are False so they can use cpanel.<domain>.
    """
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
    """Return cpanel.<domain> for custom domains.

    Platform / student hostnames cannot use cpanel.sub.<zone> reliably when the
    wildcard cert only covers one label — those sites use /cpanel on the site.
    """
    host = (domain or "").lower().rstrip(".")
    if not host or "." not in host:
        return None
    if is_platform_hostname(host, settings=settings):
        return None
    if host.startswith("cpanel."):
        return host
    if host.startswith("www."):
        host = host[4:]
    return f"cpanel.{host}"


def control_panel_url(domain: str | None, portal_base: str = "https://ifnotus.space") -> str:
    """Best URL to open the IFNOTUS customer dashboard for this site."""
    base = (portal_base or "https://ifnotus.space").rstrip("/")
    account = f"{base}/account"
    host = (domain or "").lower().rstrip(".")
    if not host:
        return account
    cpanel = control_panel_hostname(host)
    if cpanel:
        return f"https://{cpanel}/"
    # Student / platform hostname: path on their own HTTPS site
    return f"https://{host}/cpanel"
