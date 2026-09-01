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
PLATFORM_APEX = "ifnotus.space"


def is_service_hostname(hostname: str | None) -> bool:
    """True for fpanel./cpanel./webmail./mail. aliases — never standalone customer website vhosts."""
    clean = (hostname or "").strip().lower().rstrip(".")
    if clean.startswith("www."):
        clean = clean[4:]
    if not clean:
        return False
    if clean in {STAFF_PANEL_HOST, "cpanel.ifnotus.space", "mail.ifnotus.space", "api.ifnotus.space"}:
        return True
    return (
        clean.startswith("fpanel.")
        or clean.startswith("cpanel.")
        or clean.startswith("webmail.")
        or clean.startswith("mail.")
    )


def is_platform_hostname(domain: str | None, *, settings: object | None = None) -> bool:
    """True for control-plane and managed student/project hostnames."""
    host = (domain or "").lower().rstrip(".")
    if not host:
        return False
    if host.startswith("www."):
        host = host[4:]
    if host in {PLATFORM_APEX, STAFF_PANEL_HOST, "mail.ifnotus.space", "api.ifnotus.space"}:
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
    """Canonical customer fPanel hostname.
    IMPORTANT: Subdomains (*.ifnotus.space, *.customers.ifnotus.space, or any multi-label subdomain)
    must NEVER have an fpanel.<subdomain> host. They use the platform control panel (fpanel.ifnotus.space).
    Only custom apex domains (e.g. yalleydadzie.online, adastrachambers.com) can have fpanel.<apex>.
    """
    host = (domain or "").lower().rstrip(".")
    if host.startswith("www."):
        host = host[4:]
    if not host or "." not in host:
        return None
    if host in {STAFF_PANEL_HOST, PLATFORM_APEX, "mail.ifnotus.space", "api.ifnotus.space"}:
        return STAFF_PANEL_HOST
    if host.startswith("fpanel."):
        return host
    if host.endswith(".ifnotus.space") or host.endswith(".serverlabsttu.space") or host.endswith(".customers.ifnotus.space"):
        return STAFF_PANEL_HOST
    if is_student_hostname(host, settings=settings) or is_platform_hostname(host, settings=settings):
        return STAFF_PANEL_HOST

    parts = host.split(".")
    if len(parts) > 2:
        two_level_tlds = {"co.uk", "org.uk", "me.uk", "com.gh", "org.gh", "edu.gh", "gov.gh", "net.gh", "com.ng", "co.za"}
        suffix2 = ".".join(parts[-2:])
        if suffix2 in two_level_tlds and len(parts) > 3:
            primary = ".".join(parts[-3:])
            return f"fpanel.{primary}"
        elif suffix2 not in two_level_tlds:
            # Multi-level subdomain under custom domain (e.g. blog.example.com -> fpanel.example.com)
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
    if host in {PLATFORM_APEX, STAFF_PANEL_HOST, "mail.ifnotus.space"}:
        return "mail.ifnotus.space"
    if host.startswith("webmail."):
        return host
    if host.startswith("fpanel."):
        host = host[len("fpanel.") :]
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


def _is_subdomain_host(host: str, *, settings: object | None = None) -> bool:
    h = (host or "").lower().rstrip(".")
    if h.startswith("www."):
        h = h[4:]
    return bool(
        h.endswith(".ifnotus.space")
        or h.endswith(".customers.ifnotus.space")
        or h.endswith(".serverlabsttu.space")
        or is_student_hostname(h, settings=settings)
    )


def customer_panel_redirect_url(
    domain: str | None,
    *,
    portal_base: str = "https://ifnotus.space",
    tab: str | None = None,
    settings: object | None = None,
) -> str | None:
    """Where /fpanel and /cpanel shortcuts send customers.

    Subdomains (*.ifnotus.space) never get fpanel.<subdomain> — they open the portal handoff.
    Custom apex domains use https://fpanel.<domain>/.
    """
    host = (domain or "").lower().rstrip(".")
    if host.startswith("www."):
        host = host[4:]
    if host.startswith("fpanel."):
        host = host[len("fpanel.") :]
    elif host.startswith("cpanel."):
        host = host[len("cpanel.") :]
    if not host or "." not in host:
        return None
    if _is_subdomain_host(host, settings=settings):
        base = (portal_base or "https://ifnotus.space").rstrip("/")
        url = f"{base}/go/hosting?host={quote(host)}"
        if tab and tab != "overview":
            url = f"{url}&tab={quote(tab.lstrip('/'))}"
        return url
    fpanel_host = control_panel_hostname(host, settings=settings)
    if not fpanel_host or fpanel_host == STAFF_PANEL_HOST:
        return None
    url = f"https://{fpanel_host}/"
    if tab and tab != "overview":
        url = f"https://{fpanel_host}/{tab.lstrip('/')}"
    return url


def site_fpanel_url(domain: str | None, *, tab: str | None = None, settings: object | None = None) -> str | None:
    """Canonical customer hosting panel entry URL."""
    return customer_panel_redirect_url(domain, tab=tab, settings=settings)


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
    settings: object | None = None,
) -> str:
    """Portal SSO handoff redirect URL."""
    from app.services.platform.host_routing import sanitize_panel_hostname

    base = (portal_base or "https://ifnotus.space").rstrip("/")
    host = sanitize_panel_hostname(hostname)
    if not host:
        return f"{base}/account"
    url = customer_panel_redirect_url(host, portal_base=portal_base, tab=tab, settings=settings)
    return url or f"{base}/account"


def find_letsencrypt_cert(hostname: str) -> tuple[str | None, str | None]:
    """Find valid/latest fullchain.pem and privkey.pem for a given hostname, supporting -0001 suffixes."""
    from pathlib import Path

    live_dir = Path("/etc/letsencrypt/live")
    if not live_dir.exists():
        return None, None

    clean = (hostname or "").strip().lower().rstrip(".")
    if clean.startswith("www."):
        clean = clean[4:]
    if clean.startswith("fpanel."):
        clean = clean[7:]
    if clean.startswith("cpanel."):
        clean = clean[7:]

    # Check candidate directories
    candidates: list[Path] = []
    exact = live_dir / clean
    if exact.exists():
        candidates.append(exact)
    
    # Common spelling alias checks (e.g. theofiluskwame -> theophiluskwame)
    if "theofilus" in clean:
        theo_cand = live_dir / clean.replace("theofilus", "theophilus")
        if theo_cand.exists():
            candidates.append(theo_cand)
    elif "theophilus" in clean:
        theo_cand = live_dir / clean.replace("theophilus", "theofilus")
        if theo_cand.exists():
            candidates.append(theo_cand)

    try:
        candidates.extend(
            sorted(
                live_dir.glob(f"{clean}-*"),
                key=lambda p: p.stat().st_mtime if p.exists() else 0,
                reverse=True,
            )
        )
    except Exception:
        pass

    for cand in candidates:
        fullchain = cand / "fullchain.pem"
        privkey = cand / "privkey.pem"
        if fullchain.exists() and privkey.exists():
            return str(fullchain), str(privkey)

    # If this is a service prefix (fpanel., cpanel., webmail., mail.), check the apex domain
    for prefix in ("fpanel.", "cpanel.", "webmail.", "mail.", "www."):
        if clean.startswith(prefix):
            apex = clean[len(prefix):]
            for cand in [live_dir / apex, live_dir / f"{apex}-0001", live_dir / f"{apex}-0002"]:
                if (cand / "fullchain.pem").exists() and (cand / "privkey.pem").exists():
                    return str(cand / "fullchain.pem"), str(cand / "privkey.pem")

    # Fallback for platform/student subdomains to ensure HTTPS is always enabled
    if clean.endswith(".ifnotus.space"):
        p_full = live_dir / "ifnotus.space" / "fullchain.pem"
        p_key = live_dir / "ifnotus.space" / "privkey.pem"
        if p_full.exists() and p_key.exists():
            return str(p_full), str(p_key)

    if clean.endswith(".serverlabsttu.space"):
        p_full = live_dir / "serverlabsttu.space" / "fullchain.pem"
        p_key = live_dir / "serverlabsttu.space" / "privkey.pem"
        if p_full.exists() and p_key.exists():
            return str(p_full), str(p_key)

    # Fallback for custom subdomains to their parent apex domain cert (e.g. blog.yalleydadzie.online -> yalleydadzie.online)
    if "." in clean:
        parts = clean.split(".")
        if len(parts) > 2:
            parent_apex = ".".join(parts[-2:])
            apex_cand = live_dir / parent_apex
            if (apex_cand / "fullchain.pem").exists() and (apex_cand / "privkey.pem").exists():
                return str(apex_cand / "fullchain.pem"), str(apex_cand / "privkey.pem")

    return None, None

