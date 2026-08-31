"""Default parking page for ACTIVE hosting with no customer stack yet (Phase F)."""

from __future__ import annotations

from html import escape
from pathlib import Path
from urllib.parse import quote

PARKING_MARKERS = (
    "your hosting is ready",
    "it works",
    "provisioned by ifnotus",
    "site cleared",
    "no application has been installed",
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
    label = ready_page_label(hostname, display_hostname=display_hostname)
    safe_label = escape(label) if label else ""
    if is_internal_addon_hostname(hostname):
        manage = escape(panel_entry_url(hostname, portal_base))
    else:
        manage = escape(panel_path())
    title_suffix = f"{safe_label} — " if label else ""
    domain_block = f'    <p class="domain">{safe_label}</p>\n' if label else ""
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <meta name="robots" content="noindex" />
  <title>{title_suffix}Hosting ready</title>
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
    a.cta {{
      display: inline-flex;
      align-items: center;
      justify-content: center;
      margin-top: 1.25rem;
      min-height: 2.5rem;
      padding: 0.5rem 1.1rem;
      border-radius: 0.5rem;
      font-size: 0.88rem;
      font-weight: 600;
      text-decoration: none;
      border: 1px solid #d5dbe3;
      color: #1a1f24;
      background: #fff;
    }}
    a.cta:hover {{
      background: #f6f7f9;
    }}
    .foot {{
      margin: 1rem 0 0;
      font-size: 0.72rem;
      color: #8a939c;
    }}
  </style>
</head>
<body>
  <main>
    <h1>Your hosting is ready</h1>
{domain_block}    <p class="lede">Nothing is published here yet. Sign in to upload files or install an application.</p>
    <a class="cta" href="{manage}">Open hosting panel</a>
    <p class="foot">IFNOTUS</p>
  </main>
</body>
</html>
"""


def write_hosting_ready_page(
    root: Path | str,
    *,
    hostname: str,
    portal_base: str = "https://ifnotus.space",
    display_hostname: str | None = None,
    force: bool = False,
) -> Path:
    """Ensure ``index.html`` is the IFNOTUS hosting-ready parking page.

    When ``force`` is False, existing non-parking customer content is left alone.
    """
    path = Path(root)
    path.mkdir(parents=True, exist_ok=True)
    if not force:
        # Never place parking index.html if user files (php, html, etc.) already exist
        try:
            if any(p.is_file() and p.name != "index.html" for p in path.iterdir()):
                return path
        except OSError:
            pass
    index = path / "index.html"
    if index.exists() and not force:
        try:
            existing = index.read_text(encoding="utf-8", errors="replace")
        except OSError:
            existing = ""
        if not is_parking_page(existing):
            return path
    index.write_text(
        hosting_ready_html(
            hostname=hostname,
            portal_base=portal_base,
            display_hostname=display_hostname,
        ),
        encoding="utf-8",
    )
    return path
