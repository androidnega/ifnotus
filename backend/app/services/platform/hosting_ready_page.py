"""Default parking page for ACTIVE hosting with no customer stack yet (Phase F)."""

from __future__ import annotations

from html import escape
from pathlib import Path
from urllib.parse import quote

PARKING_MARKERS = (
    "your hosting is ready",
    "nothing here yet",
    "no website has been published",
    "powered by ifnotus",
    "it works",
    "provisioned by ifnotus",
    "site cleared",
    "no application has been installed",
    "this folder has no public files",
)


def is_parking_page(html: str | None) -> bool:
    text = (html or "").lower()
    if not text.strip():
        return True
    return any(marker in text for marker in PARKING_MARKERS)


def _host_resolves_publicly(hostname: str) -> bool:
    """True when public DNS (not local BIND) returns A/AAAA for the name."""
    import subprocess

    name = (hostname or "").strip().lower().rstrip(".")
    if not name:
        return False
    for qtype in ("A", "AAAA"):
        try:
            proc = subprocess.run(
                ["dig", "+short", "+time=2", "+tries=1", qtype, name, "@8.8.8.8"],
                capture_output=True,
                text=True,
                timeout=6,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            continue
        if any(line.strip() and not line.startswith(";") for line in (proc.stdout or "").splitlines()):
            return True
    return False


def manage_hosting_url(hostname: str, portal_base: str = "https://ifnotus.space", *, tab: str | None = None) -> str:
    """Public deep-link into the tenant Hosting Panel via site /cpanel.

    All customer sites (student + custom domain) use https://{domain}/cpanel.
    Only IFNOTUS staff uses cpanel.ifnotus.space.
    """
    from app.services.platform.panel_access import site_cpanel_url

    base = (portal_base or "https://ifnotus.space").rstrip("/")
    host = (hostname or "").strip().lower().rstrip(".")
    if not host:
        return f"{base}/account"
    url = site_cpanel_url(host)
    if not url:
        return f"{base}/account"
    if tab:
        return f"{url}?tab={quote(tab)}"
    return url


def is_internal_addon_hostname(hostname: str | None) -> bool:
    """True for provisional env-* hostnames — never show these to customers."""
    host = (hostname or "").strip().lower().rstrip(".")
    return bool(host) and host.endswith(".customers.ifnotus.space")


def ready_page_label(
    hostname: str,
    *,
    display_hostname: str | None = None,
) -> str | None:
    """Public site name for the parking page, or None when only an internal host exists."""
    for candidate in (display_hostname, hostname):
        name = (candidate or "").strip().lower().rstrip(".")
        if name and not is_internal_addon_hostname(name):
            return name
    return None


def panel_path(*, tab: str | None = None) -> str:
    """Relative /fpanel link — resolved dynamically by nginx → API at click time."""
    if tab:
        return f"/fpanel?tab={quote(tab)}"
    return "/fpanel"


def panel_entry_url(
    hostname: str,
    portal_base: str = "https://ifnotus.space",
    *,
    tab: str | None = None,
) -> str:
    """Where nginx /cpanel should send browsers (SSO handoff — never loops back to /cpanel)."""
    from app.services.platform.panel_access import panel_sso_url

    if is_internal_addon_hostname(hostname):
        return f"{(portal_base or 'https://ifnotus.space').rstrip('/')}/account"
    return panel_sso_url(hostname, portal_base, tab=tab)


def hosting_ready_html(
    *,
    hostname: str,
    portal_base: str = "https://ifnotus.space",
    display_hostname: str | None = None,
) -> str:
    """Server-served empty-site page (not written into the customer's public folder)."""
    del portal_base  # reserved for callers; page stays hostname-agnostic by default
    label = ready_page_label(hostname, display_hostname=display_hostname)
    safe_label = escape(label) if label else ""
    domain_block = f'    <p class="domain">{safe_label}</p>\n' if label else ""
    title = f"{safe_label} — Nothing here yet" if label else "Nothing here yet"
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <meta name="robots" content="noindex" />
  <title>{title}</title>
  <style>
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      min-height: 100vh;
      display: grid;
      place-items: center;
      font-family: Figtree, "Segoe UI", system-ui, sans-serif;
      background: #f6f7f9;
      color: #1a1f24;
      padding: 1.25rem;
    }}
    main {{
      width: min(26rem, 100%);
      padding: 1.75rem 1.5rem;
      background: #fff;
      border: 1px solid #e3e7ec;
      border-radius: 0.75rem;
      text-align: center;
    }}
    h1 {{
      margin: 0;
      font-family: Sora, Figtree, sans-serif;
      font-size: 1.35rem;
      font-weight: 650;
      letter-spacing: -0.02em;
      line-height: 1.25;
    }}
    .domain {{
      margin: 0.5rem 0 0;
      font-size: 0.95rem;
      font-weight: 600;
      color: #3a4450;
      word-break: break-word;
    }}
    .lede {{
      margin: 0.75rem 0 0;
      color: #5c6670;
      font-size: 0.9rem;
      line-height: 1.5;
    }}
    .foot {{
      margin: 1.25rem 0 0;
      font-size: 0.78rem;
      font-weight: 600;
      color: #8a939c;
    }}
  </style>
</head>
<body>
  <main>
    <h1>Nothing here yet.</h1>
{domain_block}    <p class="lede">This domain is active, but no website has been published.</p>
    <p class="foot">Powered by IFNOTUS</p>
  </main>
</body>
</html>
"""


def empty_site_html() -> str:
    """Hostname-agnostic empty-site page for nginx ``error_page`` alias."""
    return hosting_ready_html(hostname="")


def write_hosting_ready_page(
    root: Path | str,
    *,
    hostname: str,
    portal_base: str = "https://ifnotus.space",
    display_hostname: str | None = None,
    force: bool = False,
) -> Path:
    """Ensure the document root exists — do not seed a default ``index.html``.

    Historically wrote an IFNOTUS parking page. Customers upload or install their
    own content; empty folders stay empty. Any leftover parking ``index.html``
    is removed (customer pages are left alone).
    """
    del hostname, portal_base, display_hostname, force  # unused — kept for call-site compatibility
    path = Path(root)
    path.mkdir(parents=True, exist_ok=True)
    index = path / "index.html"
    if not index.is_file():
        return path
    try:
        existing = index.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return path
    if is_parking_page(existing):
        try:
            index.unlink(missing_ok=True)
        except OSError:
            pass
    return path
