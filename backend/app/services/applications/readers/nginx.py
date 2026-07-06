"""Nginx site configuration reader."""

from __future__ import annotations

import re
from pathlib import Path

from app.schemas.applications import NginxSiteSchema


class NginxReader:
    """Parses Nginx site configuration files."""

    def read(self, site_path: str | None, configured_server_name: str | None = None) -> NginxSiteSchema:
        if not site_path:
            return NginxSiteSchema(configured=False, message="Nginx site not configured.")

        path = Path(site_path)
        if not path.exists():
            return NginxSiteSchema(
                configured=True,
                site_path=str(path),
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

            return NginxSiteSchema(
                configured=True,
                site_path=str(path),
                server_names=server_names,
                enabled=path.is_symlink() or path.exists(),
                ssl_enabled=ssl_enabled,
                root=root,
            )
        except Exception as exc:
            return NginxSiteSchema(
                configured=True,
                site_path=str(path),
                message=str(exc),
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
