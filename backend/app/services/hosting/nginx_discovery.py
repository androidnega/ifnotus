"""Nginx site discovery — read-only scan of sites-enabled/available."""

from __future__ import annotations

import re
from pathlib import Path

from app.core.config import Settings
from app.core.logging import get_logger
from app.schemas.inventory import DomainReconciliationState, NginxDiscoveredDomainSchema

logger = get_logger(__name__)


class NginxDiscoveryService:
    """Parse nginx vhost files without modifying them."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def scan_sites(self) -> list[NginxDiscoveredDomainSchema]:
        sites: dict[str, NginxDiscoveredDomainSchema] = {}
        enabled_dir = Path(self._settings.nginx_sites_enabled)
        available_dir = Path(self._settings.nginx_sites_available)

        for directory in (enabled_dir, available_dir):
            if not directory.exists():
                logger.debug("nginx_dir_missing", path=str(directory))
                continue
            for path in sorted(directory.iterdir()):
                if not path.is_file() and not path.is_symlink():
                    continue
                try:
                    parsed = self._parse_site(path, enabled=path.is_symlink() or directory == enabled_dir)
                except OSError as exc:
                    logger.warning("nginx_site_read_failed", path=str(path), error=str(exc))
                    continue
                for site in parsed:
                    existing = sites.get(site.server_name)
                    if existing is None or (site.enabled and not existing.enabled):
                        sites[site.server_name] = site

        return list(sites.values())

    def _parse_site(self, path: Path, *, enabled: bool) -> list[NginxDiscoveredDomainSchema]:
        content = path.read_text(encoding="utf-8", errors="replace")
        server_names = self._extract_server_names(content)
        if not server_names:
            return []

        document_root = self._extract_root(content)
        proxy_pass = self._extract_proxy_pass(content)
        ssl_enabled = "listen 443" in content or "ssl_certificate" in content
        cert_path = self._extract_ssl_certificate(content)

        return [
            NginxDiscoveredDomainSchema(
                server_name=name,
                site_path=str(path),
                enabled=enabled,
                ssl_enabled=ssl_enabled,
                document_root=document_root,
                proxy_pass=proxy_pass,
                certificate_path=cert_path,
                in_database=False,
                reconciliation_state=DomainReconciliationState.DISCOVERED,
            )
            for name in server_names
            if name and name != "_"
        ]

    @staticmethod
    def _extract_server_names(content: str) -> list[str]:
        names: list[str] = []
        for match in re.finditer(r"server_name\s+([^;]+);", content):
            for name in match.group(1).split():
                name = name.strip().rstrip(";")
                if name and name not in names and name != "_":
                    names.append(name)
        return names

    @staticmethod
    def _extract_root(content: str) -> str | None:
        match = re.search(r"root\s+([^;]+);", content)
        return match.group(1).strip() if match else None

    @staticmethod
    def _extract_proxy_pass(content: str) -> str | None:
        match = re.search(r"proxy_pass\s+([^;]+);", content)
        return match.group(1).strip() if match else None

    @staticmethod
    def _extract_ssl_certificate(content: str) -> str | None:
        match = re.search(r"ssl_certificate\s+([^;]+);", content)
        if not match:
            return None
        value = match.group(1).strip()
        if value.endswith("fullchain.pem") or value.endswith(".pem"):
            return value
        return value
