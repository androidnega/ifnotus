"""Customer control-panel and service access URLs according to IFNOTUS routing standard.

Routing Standard:
1. Customer fPanel Canonical: https://fpanel.{domain} (custom apex) or https://{tenant}/hosting/ (platform subdomains)
2. Convenience Shortcut: https://{domain}/fpanel & https://{domain}/cpanel
3. Customer Webmail: https://{domain}/mail (same-host Roundcube) — never bounce platform tenants to mail.ifnotus.space
4. Optional custom alias: https://webmail.{custom-apex}
5. Mail Server (IMAP/SMTP): mail.{custom-apex} or shared mail.ifnotus.space for platform/student hosts
6. Staff Control Plane (supreme, never a tenant): https://fpanel.ifnotus.space
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
LEGACY_STAFF_PANEL_HOST = "cpanel.ifnotus.space"
PLATFORM_MAIL_HOST = "mail.ifnotus.space"
PLATFORM_SERVICE_HOSTS = frozenset(
    {
        STAFF_PANEL_HOST,
        LEGACY_STAFF_PANEL_HOST,
        PLATFORM_MAIL_HOST,
        "webmail.ifnotus.space",
        "api.ifnotus.space",
        "www.ifnotus.space",
    }
)


def is_service_hostname(hostname: str | None) -> bool:
    """True for fpanel./cpanel./webmail./mail. aliases — never standalone customer website vhosts."""
    clean = (hostname or "").strip().lower().rstrip(".")
    if clean.startswith("www."):
        clean = clean[4:]
    if not clean:
        return False
    if clean in PLATFORM_SERVICE_HOSTS:
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


def panel_handoff_host(domain: str | None, *, settings: object | None = None) -> str | None:
    """Hostname where SSO handoff lands.

    Platform subdomains (user.ifnotus.space) use the site itself — panel lives at /hosting/*.
    Custom apex domains use fpanel.<domain>.
    """
    host = (domain or "").lower().rstrip(".")
    if host.startswith("www."):
        host = host[4:]
    if not host or "." not in host:
        return None
    if host in {STAFF_PANEL_HOST, PLATFORM_APEX, "mail.ifnotus.space", "api.ifnotus.space"}:
        return STAFF_PANEL_HOST
    if _is_subdomain_host(host, settings=settings):
        return host
    fpanel = control_panel_hostname(host, settings=settings)
    if fpanel and fpanel != STAFF_PANEL_HOST:
        return fpanel
    return f"fpanel.{host}"


def panel_handoff_url(
    domain: str | None,
    token: str,
    *,
    tab: str | None = None,
    settings: object | None = None,
) -> str | None:
    """Full SSO handoff URL for a tenant site."""
    host = panel_handoff_host(domain, settings=settings)
    if not host:
        return None
    from urllib.parse import urlencode

    site = (domain or "").lower().rstrip(".")
    if site.startswith("www."):
        site = site[4:]
    if _is_subdomain_host(site, settings=settings):
        path = f"https://{host}/hosting/sso"
    else:
        path = f"https://{host}/sso"
    q: dict[str, str] = {"token": token}
    if tab and tab != "overview":
        q["tab"] = tab.lstrip("/")
    return f"{path}?{urlencode(q)}"


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
    """Dedicated webmail.* hostname for custom apex DNS/vhosts.

    Platform/student tenants do NOT get webmail.<subdomain> — they use same-host /mail.
    Shared Roundcube server hostname remains mail.ifnotus.space (IMAP/SMTP + root UI).
    """
    host = (domain or "").lower().rstrip(".")
    if host.startswith("www."):
        host = host[4:]
    if not host or "." not in host:
        return None
    if host in PLATFORM_SERVICE_HOSTS or host == PLATFORM_APEX:
        return PLATFORM_MAIL_HOST
    if host.startswith("webmail."):
        apex = host[len("webmail.") :]
        # Platform / student trees never get a dedicated webmail.* vhost.
        if (
            apex == PLATFORM_APEX
            or apex.endswith(f".{PLATFORM_APEX}")
            or apex.endswith(".serverlabsttu.space")
            or apex == "serverlabsttu.space"
            or apex in PLATFORM_SERVICE_HOSTS
        ):
            return PLATFORM_MAIL_HOST
        return host
    if host.startswith("fpanel.") or host.startswith("cpanel."):
        host = host.split(".", 1)[1]
    if host.endswith(".customers.ifnotus.space"):
        return f"webmail.{host}"
    # Student / platform subdomains: no dedicated webmail.* — same-host /mail only.
    if (
        host == PLATFORM_APEX
        or host.endswith(f".{PLATFORM_APEX}")
        or host.endswith(".serverlabsttu.space")
        or host == "serverlabsttu.space"
    ):
        return None

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
    """Mail client incoming/outgoing server hostname: mail.<domain> or shared mail.ifnotus.space."""
    host = (domain or "").lower().rstrip(".")
    if host.startswith("www."):
        host = host[4:]
    if not host or "." not in host:
        return None
    if host in {PLATFORM_APEX, STAFF_PANEL_HOST, LEGACY_STAFF_PANEL_HOST, PLATFORM_MAIL_HOST} or host in PLATFORM_SERVICE_HOSTS:
        return PLATFORM_MAIL_HOST
    if host.startswith("mail."):
        return host
    if host.startswith("fpanel.") or host.startswith("cpanel.") or host.startswith("webmail."):
        host = host.split(".", 1)[1]
    if (
        host == PLATFORM_APEX
        or host.endswith(f".{PLATFORM_APEX}")
        or host.endswith(".serverlabsttu.space")
        or host == "serverlabsttu.space"
        or host.endswith(".customers.ifnotus.space")
    ):
        return PLATFORM_MAIL_HOST
    return f"mail.{host}"


def _is_subdomain_host(host: str, *, settings: object | None = None) -> bool:
    h = (host or "").lower().rstrip(".")
    if h.startswith("www."):
        h = h[4:]
    # Staff WHM + platform service hosts are never tenant subdomains.
    if not h or h == PLATFORM_APEX or h in PLATFORM_SERVICE_HOSTS:
        return False
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
        return f"https://{host}/hosting/"
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
    """Customer webmail entry URL.

    - Platform mail server UI: https://mail.ifnotus.space/
    - Tenant / customer sites: https://{that-host}/mail (same-host Roundcube — never bounce away)
    - Custom apex may also use https://webmail.{apex} as an optional dedicated alias
    """
    host = (domain or "").lower().rstrip(".")
    if host.startswith("www."):
        host = host[4:]
    if not host or "." not in host:
        return None
    if host in {PLATFORM_APEX, STAFF_PANEL_HOST, LEGACY_STAFF_PANEL_HOST, PLATFORM_MAIL_HOST, "webmail.ifnotus.space"}:
        return f"https://{PLATFORM_MAIL_HOST}/"
    if host.startswith("webmail."):
        return f"https://{host}/"
    if host.startswith("mail.") and host != PLATFORM_MAIL_HOST:
        # mail.<custom> convenience host redirects to webmail; entry stays on webmail host when present
        apex = host[len("mail.") :]
        wm = webmail_hostname(apex)
        return f"https://{wm}/" if wm else f"https://{apex}/mail"
    # Same-host path for every customer site (platform tenant or custom apex).
    return f"https://{host}/mail"


def site_mail_url(domain: str | None) -> str | None:
    """Webmail shortcut URL: https://{domain}/mail (same host)."""
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

