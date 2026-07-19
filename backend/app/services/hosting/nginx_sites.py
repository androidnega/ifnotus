"""Enable / disable Nginx site configs and reload."""

from __future__ import annotations

import re
import shutil
from pathlib import Path

from app.core.config import Settings
from app.schemas.operations import OperationResult
from app.services.applications.config import ApplicationDefinition
from app.services.monitoring.subprocess_util import resolve_binary, run_command

STUB_MARKER = "# managed-by-ifnotus: disabled-stub"


class NginxSiteManager:
    """Mutate sites-enabled for registered applications."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._enabled_dir = Path(settings.nginx_sites_enabled)
        self._available_dir = Path(settings.nginx_sites_available)

    def resolve_site_name(self, app: ApplicationDefinition) -> str | None:
        if app.nginx.site:
            return Path(app.nginx.site).name
        if app.nginx.server_name:
            return app.nginx.server_name
        if app.ssl.domain:
            return app.ssl.domain
        return None

    def is_enabled(self, app: ApplicationDefinition) -> bool:
        name = self.resolve_site_name(app)
        if not name:
            return False
        link = self._enabled_dir / name
        if not (link.exists() or link.is_symlink()):
            return False
        return not self.is_disabled_stub(link)

    @staticmethod
    def is_disabled_stub(path: Path) -> bool:
        try:
            if not path.exists() and not path.is_symlink():
                return False
            # Follow symlink only if checking content of real file; stubs are real files.
            target = path
            if path.is_symlink():
                return False
            return STUB_MARKER in target.read_text(encoding="utf-8", errors="replace")[:240]
        except OSError:
            return False

    async def set_site_enabled(self, app: ApplicationDefinition, enabled: bool) -> OperationResult:
        name = self.resolve_site_name(app)
        if not name:
            return OperationResult(
                success=True,
                message="No nginx site configured for this app.",
                details={"skipped": True},
            )

        self._enabled_dir.mkdir(parents=True, exist_ok=True)
        self._available_dir.mkdir(parents=True, exist_ok=True)

        enabled_path = self._enabled_dir / name
        available_path = self._available_dir / name

        try:
            if enabled:
                self._enable_site(enabled_path, available_path)
            else:
                self._disable_site(enabled_path, available_path)
        except OSError as exc:
            return OperationResult(success=False, message=f"Failed to update nginx site: {exc}")

        reload_result = await self.reload()
        if not reload_result.success:
            return reload_result

        state = "enabled" if enabled else "disabled"
        return OperationResult(
            success=True,
            message=f"Nginx site '{name}' {state}.",
            details={"site": name, "enabled": enabled},
        )

    def _enable_site(self, enabled_path: Path, available_path: Path) -> None:
        self._ensure_available(enabled_path, available_path)
        if not available_path.exists():
            raise FileNotFoundError(f"Nginx site config not found in sites-available: {available_path}")
        # Remove stub or stale link, then restore symlink to real config.
        if enabled_path.exists() or enabled_path.is_symlink():
            enabled_path.unlink()
        enabled_path.symlink_to(available_path)

    def _ensure_available(self, enabled_path: Path, available_path: Path) -> None:
        """If the only copy lives in sites-enabled, move it to sites-available."""
        if available_path.exists():
            return
        if enabled_path.exists() and not enabled_path.is_symlink() and not self.is_disabled_stub(enabled_path):
            shutil.move(str(enabled_path), str(available_path))

    def _disable_site(self, enabled_path: Path, available_path: Path) -> None:
        # Preserve real config under sites-available.
        if enabled_path.exists() and not enabled_path.is_symlink() and not self.is_disabled_stub(enabled_path):
            if not available_path.exists():
                shutil.move(str(enabled_path), str(available_path))
            else:
                enabled_path.unlink()
        elif enabled_path.is_symlink() or enabled_path.exists():
            enabled_path.unlink()

        if not available_path.exists():
            raise FileNotFoundError(f"Cannot disable — missing config at {available_path}")

        stub = self._build_disabled_stub(available_path)
        enabled_path.write_text(stub, encoding="utf-8")

    def _offline_page_dir(self, site_name: str) -> Path:
        return Path("/var/lib/ifnotus/disabled-pages") / site_name

    def _build_disabled_stub(self, available_path: Path) -> str:
        content = available_path.read_text(encoding="utf-8", errors="replace")
        names = self._extract_server_names(content)
        if not names:
            names = [available_path.name]
        cert = self._extract_directive(content, "ssl_certificate")
        key = self._extract_directive(content, "ssl_certificate_key")
        primary = names[0]
        names_line = " ".join(names)
        site_name = available_path.name

        page_dir = self._offline_page_dir(site_name)
        page_dir.mkdir(parents=True, exist_ok=True)
        (page_dir / "index.html").write_text(self._disabled_html(primary), encoding="utf-8")

        blocks: list[str] = [STUB_MARKER, "# Application temporarily disabled by IFNOTUS.", ""]

        def append_server(listen_lines: list[str], *, ssl: bool) -> None:
            blocks.append("server {")
            blocks.extend(f"    {line}" for line in listen_lines)
            blocks.append(f"    server_name {names_line};")
            if ssl and cert and key:
                blocks.append(f"    ssl_certificate {cert};")
                blocks.append(f"    ssl_certificate_key {key};")
                if Path("/etc/letsencrypt/options-ssl-nginx.conf").exists():
                    blocks.append("    include /etc/letsencrypt/options-ssl-nginx.conf;")
                if Path("/etc/letsencrypt/ssl-dhparams.pem").exists():
                    blocks.append("    ssl_dhparam /etc/letsencrypt/ssl-dhparams.pem;")
            blocks.append(f"    root {page_dir};")
            blocks.append("    add_header Retry-After 3600 always;")
            blocks.append('    add_header Cache-Control "no-store" always;')
            blocks.append("    error_page 503 /index.html;")
            blocks.append("    location / {")
            blocks.append("        return 503;")
            blocks.append("    }")
            blocks.append("    location = /index.html {")
            blocks.append("        internal;")
            blocks.append("    }")
            blocks.append("}")
            blocks.append("")

        append_server(["listen 80;", "listen [::]:80;"], ssl=False)
        if cert and key:
            append_server(["listen 443 ssl;", "listen [::]:443 ssl;"], ssl=True)

        return "\n".join(blocks)

    @staticmethod
    def _disabled_html(hostname: str) -> str:
        safe_host = (
            hostname.replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace('"', "&quot;")
        )
        return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <meta name="robots" content="noindex, nofollow" />
  <title>Unavailable — {safe_host}</title>
  <style>
    html, body {{
      height: 100%;
      margin: 0;
      font-family: ui-sans-serif, system-ui, -apple-system, "Segoe UI", sans-serif;
      background: #07110c;
      color: #d1fae5;
    }}
    .wrap {{
      min-height: 100%;
      display: flex;
      align-items: center;
      justify-content: center;
      padding: 2rem;
      background: radial-gradient(ellipse 70% 50% at 50% -10%, rgba(16, 185, 129, 0.14), transparent 55%);
    }}
    .card {{
      max-width: 28rem;
      width: 100%;
      border: 1px solid rgba(16, 185, 129, 0.25);
      border-radius: 12px;
      background: rgba(7, 17, 12, 0.92);
      padding: 1.5rem 1.35rem;
      box-shadow: 0 24px 60px rgba(0, 0, 0, 0.45);
    }}
    .kicker {{
      font-size: 11px;
      letter-spacing: 0.14em;
      text-transform: uppercase;
      color: #34d399;
      margin: 0 0 0.5rem;
    }}
    h1 {{
      font-size: 1.25rem;
      margin: 0 0 0.55rem;
      color: #ecfdf5;
    }}
    p {{
      margin: 0;
      color: rgba(167, 243, 208, 0.78);
      line-height: 1.5;
      font-size: 0.95rem;
    }}
    .meta {{
      margin-top: 1rem;
      font-size: 12px;
      color: rgba(110, 231, 183, 0.55);
      font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
    }}
  </style>
</head>
<body>
  <div class="wrap">
    <div class="card">
      <p class="kicker">IFNOTUS</p>
      <h1>This application is temporarily offline</h1>
      <p>
        The site has been stopped by the server operator.
        Please try again later or contact the site administrator.
      </p>
      <p class="meta">host: {safe_host} · status: 503</p>
    </div>
  </div>
</body>
</html>
"""

    @staticmethod
    def _extract_server_names(content: str) -> list[str]:
        names: list[str] = []
        for match in re.finditer(r"server_name\s+([^;]+);", content):
            for name in match.group(1).split():
                name = name.strip()
                if name and name not in names:
                    names.append(name)
        return names

    @staticmethod
    def _extract_directive(content: str, name: str) -> str | None:
        match = re.search(rf"{name}\s+([^;]+);", content)
        return match.group(1).strip() if match else None

    async def reload(self) -> OperationResult:
        nginx = resolve_binary("nginx", self._settings.nginx_binary)
        if nginx:
            test_code, _, test_err = await run_command(nginx, "-t", timeout=30)
            if test_code != 0:
                return OperationResult(
                    success=False,
                    message=test_err or "nginx -t failed; site change not applied cleanly.",
                )
            code, stdout, stderr = await run_command(nginx, "-s", "reload", timeout=30)
            if code == 0:
                return OperationResult(success=True, message=stdout or "Nginx reloaded.")

        systemctl = resolve_binary("systemctl")
        if systemctl:
            code, stdout, stderr = await run_command(systemctl, "reload", "nginx", timeout=30)
            if code == 0:
                return OperationResult(success=True, message=stdout or "Nginx reloaded via systemctl.")
            return OperationResult(success=False, message=stderr or stdout or "Failed to reload nginx.")

        return OperationResult(success=False, message="nginx binary / systemctl not available.")
