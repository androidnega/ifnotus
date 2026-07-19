"""Nginx site configuration reader."""

from __future__ import annotations

import re
from pathlib import Path

from app.schemas.applications import NginxSiteSchema

NGINX_SITES_ENABLED = Path("/etc/nginx/sites-enabled")
NGINX_SITES_AVAILABLE = Path("/etc/nginx/sites-available")
STUB_MARKER = "# managed-by-ifnotus: disabled-stub"


class NginxReader:
    """Parses Nginx site configuration files."""

    def read(self, site_path: str | None, configured_server_name: str | None = None) -> NginxSiteSchema:
        path = self._resolve_site_path(site_path, configured_server_name)
        if path is None:
            return NginxSiteSchema(
                configured=False,
                server_names=[configured_server_name] if configured_server_name else [],
                message="Nginx site not configured.",
            )

        if not path.exists():
            return NginxSiteSchema(
                configured=True,
                site_path=str(path),
                server_names=[configured_server_name] if configured_server_name else [],
                enabled=False,
                message=f"Nginx site file not found: {path}",
            )

        try:
            content = path.read_text(encoding="utf-8", errors="replace")
            server_names = self._extract_server_names(content)
            if configured_server_name and configured_server_name not in server_names:
                server_names.insert(0, configured_server_name)
            root = self._extract_root(content)
            ssl_enabled = "ssl" in content.lower() or "listen 443" in content
            enabled = self._is_enabled(path)

            return NginxSiteSchema(
                configured=True,
                site_path=str(path),
                server_names=server_names,
                enabled=enabled,
                ssl_enabled=ssl_enabled,
                root=root,
            )
        except Exception as exc:
            return NginxSiteSchema(
                configured=True,
                site_path=str(path),
                message=str(exc),
            )

    def _resolve_site_path(self, site_path: str | None, server_name: str | None) -> Path | None:
        if site_path:
            return Path(site_path)
        if not server_name:
            return None

        for directory in (NGINX_SITES_ENABLED, NGINX_SITES_AVAILABLE):
            direct = directory / server_name
            if direct.exists():
                return direct

        # Scan enabled sites for a matching server_name directive.
        if NGINX_SITES_ENABLED.exists():
            for candidate in NGINX_SITES_ENABLED.iterdir():
                if not candidate.is_file() and not candidate.is_symlink():
                    continue
                try:
                    content = candidate.read_text(encoding="utf-8", errors="replace")
                except OSError:
                    continue
                if server_name in self._extract_server_names(content):
                    return candidate
        return None

    @staticmethod
    def _is_enabled(path: Path) -> bool:
        name = path.name
        enabled = NGINX_SITES_ENABLED / name
        if enabled.exists() or enabled.is_symlink():
            try:
                # Disabled apps leave a 503 stub in sites-enabled — treat as off.
                if not enabled.is_symlink():
                    head = enabled.read_text(encoding="utf-8", errors="replace")[:240]
                    if STUB_MARKER in head:
                        return False
            except OSError:
                pass
            return True
        if path.resolve().parent == NGINX_SITES_ENABLED.resolve():
            return True
        return path.is_symlink() or (
            NGINX_SITES_ENABLED.exists()
            and any(p.resolve() == path.resolve() for p in NGINX_SITES_ENABLED.iterdir() if p.exists())
        )

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
    def _extract_root(content: str) -> str | None:
        match = re.search(r"root\s+([^;]+);", content)
        return match.group(1).strip() if match else None
