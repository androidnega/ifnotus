"""Customer control-panel and service access URLs according to IFNOTUS routing standard.

Routing Standard:
1. Customer fPanel Canonical: https://fpanel.{domain}
2. Convenience Shortcut: https://{domain}/fpanel & https://{domain}/cpanel -> 302 -> https://fpanel.{domain}
3. Customer Webmail Canonical: https://webmail.{domain}
4. Convenience Shortcuts: https://{domain}/webmail & https://{domain}/mail -> 302 -> https://webmail.{domain}
5. Mail Server: mail.{domain}
6. Staff Control Plane: https://fpanel.ifnotus.space/login
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

STAFF_PANEL_HOST = "fpanel.ifnotus.space"
LEGACY_STAFF_PANEL_HOST = "cpanel.ifnotus.space"
PLATFORM_APEX = "ifnotus.space"


def is_platform_hostname(domain: str | None, *, settings: object | None = None) -> bool:
    """True for control-plane and managed student/project hostnames."""
    host = (domain or "").lower().rstrip(".")
    if not host:
        return False
    if host.startswith("www."):
        host = host[4:]
    if host in {PLATFORM_APEX, STAFF_PANEL_HOST, LEGACY_STAFF_PANEL_HOST, "mail.ifnotus.space", "api.ifnotus.space"}:
        return True
    if host.endswith(".customers.ifnotus.space"):
        return False
    if host.endswith(".ifnotus.space"):
        return True
    active = resolve_student_zone(settings)
    legacy = resolve_legacy_student_zone(settings)
    for zone in {active, legacy, STUDENT_ZONE, LEGACY_STUDENT_ZONE}:
        if zone and zone != PLATFORM_APEX and (host == zone or host.endswith(f".{zone}")):
            return True
    return is_student_hostname(host, settings=settings)


def control_panel_hostname(domain: str | None, *, settings: object | None = None) -> str | None:
    """Canonical customer fPanel hostname: fpanel.<domain> (e.g. fpanel.yalleydadzie.online).
    Customer subdomains (e.g. blog.yalleydadzie.online) remain managed through fpanel.<primary-domain>.
    """
    host = (domain or "").lower().rstrip(".")
    if host.startswith("www."):
        host = host[4:]
    if not host or "." not in host:
        return None
    if host in {STAFF_PANEL_HOST, LEGACY_STAFF_PANEL_HOST}:
        return STAFF_PANEL_HOST
    if host in {PLATFORM_APEX, "mail.ifnotus.space", "api.ifnotus.space"}:
        return STAFF_PANEL_HOST
    if host.startswith("fpanel."):
        return host
    if host.startswith("cpanel."):
        host = host[len("cpanel.") :]
        return f"fpanel.{host}"
    if host.endswith(".customers.ifnotus.space"):
        return f"fpanel.{host}"
    if is_student_hostname(host, settings=settings):
        # Student hostnames stay on student subdomain
        return host

    parts = host.split(".")
    if len(parts) > 2:
        two_level_tlds = {"co.uk", "org.uk", "me.uk", "com.gh", "org.gh", "edu.gh", "gov.gh", "net.gh", "com.ng", "co.za"}
        suffix2 = ".".join(parts[-2:])
        if suffix2 in two_level_tlds and len(parts) > 3:
            primary = ".".join(parts[-3:])
            return f"fpanel.{primary}"
        elif suffix2 not in two_level_tlds:
            primary = ".".join(parts[-2:])
            return f"fpanel.{primary}"

    return f"fpanel.{host}"


def webmail_hostname(domain: str | None, *, settings: object | None = None) -> str | None:
    """Canonical webmail hostname: webmail.<domain> (e.g. webmail.yalleydadzie.online).
    Subdomains use webmail on the primary domain.
    """
    host = (domain or "").lower().rstrip(".")
    if host.startswith("www."):
        host = host[4:]
    if not host or "." not in host:
        return None
    if host in {PLATFORM_APEX, STAFF_PANEL_HOST, LEGACY_STAFF_PANEL_HOST, "mail.ifnotus.space"}:
        return "mail.ifnotus.space"
    if host.startswith("webmail."):
        return host
    if host.startswith("fpanel."):
        host = host[len("fpanel.") :]
    elif host.startswith("cpanel."):
        host = host[len("cpanel.") :]
    if host.endswith(".customers.ifnotus.space"):
        return f"webmail.{host}"

    parts = host.split(".")
    if len(parts) > 2:
        two_level_tlds = {"co.uk", "org.uk", "me.uk", "com.gh", "org.gh", "edu.gh", "gov.gh", "net.gh", "com.ng", "co.za"}
        suffix2 = ".".join(parts[-2:])
        if suffix2 in two_level_tlds and len(parts) > 3:
            primary = ".".join(parts[-3:])
            return f"webmail.{primary}"
        elif suffix2 not in two_level_tlds:
            primary = ".".join(parts[-2:])
            return f"webmail.{primary}"

    return f"webmail.{host}"


def mail_server_hostname(domain: str | None, *, settings: object | None = None) -> str | None:
    """Mail client incoming/outgoing server hostname: mail.<domain>."""
    host = (domain or "").lower().rstrip(".")
    if host.startswith("www."):
        host = host[4:]
    if not host or "." not in host:
        return None
    if host in {PLATFORM_APEX, STAFF_PANEL_HOST, LEGACY_STAFF_PANEL_HOST, "mail.ifnotus.space"}:
        return "mail.ifnotus.space"
    if host.startswith("mail."):
        return host
    if host.startswith("fpanel.") or host.startswith("cpanel.") or host.startswith("webmail."):
        host = host.split(".", 1)[1]
    return f"mail.{host}"


def site_fpanel_url(domain: str | None, *, tab: str | None = None) -> str | None:
    """Canonical customer hosting panel: https://fpanel.{domain}/ (clean paths, no UUID in URL)."""
    host = (domain or "").lower().rstrip(".")
    if host.startswith("www."):
        host = host[4:]
    if not host or "." not in host:
        return None
    fpanel_host = control_panel_hostname(host)
    if not fpanel_host:
        return None
    base = f"https://{fpanel_host}"
    if tab and tab != "overview":
        clean_tab = tab.lstrip("/")
        return f"{base}/{clean_tab}"
    return f"{base}/"


def site_cpanel_url(domain: str | None, *, tab: str | None = None) -> str | None:
    """Alias for site_fpanel_url (Phase brand transition)."""
    return site_fpanel_url(domain, tab=tab)


def site_fpanel_shortcut_url(domain: str | None) -> str | None:
    """Convenience shortcut: https://{domain}/fpanel (which 302 redirects to fpanel.{domain})."""
    host = (domain or "").lower().rstrip(".")
    if host.startswith("www."):
        host = host[4:]
    if not host or "." not in host:
        return None
    if host.startswith("fpanel."):
        host = host[len("fpanel.") :]
    elif host.startswith("cpanel."):
        host = host[len("cpanel.") :]
    return f"https://{host}/fpanel"


def site_cpanel_shortcut_url(domain: str | None) -> str | None:
    """Convenience shortcut: https://{domain}/cpanel (which 302 redirects to fpanel.{domain})."""
    return site_fpanel_shortcut_url(domain)


def site_webmail_url(domain: str | None) -> str | None:
    """Canonical webmail entry: https://webmail.{domain}."""
    host = (domain or "").lower().rstrip(".")
    if host.startswith("www."):
        host = host[4:]
    if not host or "." not in host:
        return None
    wm_host = webmail_hostname(host)
    return f"https://{wm_host}" if wm_host else "https://mail.ifnotus.space/"


def site_mail_url(domain: str | None) -> str | None:
    """Webmail shortcut: https://{domain}/webmail or https://{domain}/mail."""
    return site_webmail_url(domain)


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
    """Portal SSO handoff redirect URL."""
    from app.services.platform.host_routing import sanitize_panel_hostname

    base = (portal_base or "https://ifnotus.space").rstrip("/")
    host = sanitize_panel_hostname(hostname)
    if not host:
        return f"{base}/account"
    cpanel = control_panel_hostname(host) or host
    url = f"https://{cpanel}/"
    if tab and tab != "overview":
        url = f"https://{cpanel}/{tab.lstrip('/')}"
    return url
