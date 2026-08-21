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

    def read(
        self,
        site_path: str | None,
        configured_server_name: str | None = None,
        app_root: str | None = None,
    ) -> NginxSiteSchema:
        path = self._resolve_site_path(site_path, configured_server_name, app_root)
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
            cert = self._extract_ssl_certificate(content)
            ssl_enabled = bool(cert) or "listen 443" in content or re.search(r"listen\s+\d+\s+ssl", content) is not None
            enabled = self._is_enabled(path)

            return NginxSiteSchema(
                configured=True,
                site_path=str(path),
                server_names=server_names,
                enabled=enabled,
                ssl_enabled=ssl_enabled,
                root=root,
                certificate_path=cert,
            )
        except Exception as exc:
            return NginxSiteSchema(
                configured=True,
                site_path=str(path),
                message=str(exc),
            )

    def _resolve_site_path(
        self,
        site_path: str | None,
        server_name: str | None,
        app_root: str | None,
    ) -> Path | None:
        if site_path:
            return Path(site_path)
        if server_name:
            for directory in (NGINX_SITES_ENABLED, NGINX_SITES_AVAILABLE):
                direct = directory / server_name
                if direct.exists():
                    return direct
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

        if app_root:
            discovered = self._discover_by_app_root(app_root)
            if discovered:
                return discovered
        return None

    def _discover_by_app_root(self, app_root: str) -> Path | None:
        root = str(Path(app_root).resolve())
        needles = {root, root.rstrip("/")}
        # Also match parent/child paths that commonly appear in aliases
        parent = str(Path(root).parent)
        if parent not in {"/", ""}:
            needles.add(parent)

        best: Path | None = None
        best_score = 0
        for directory in (NGINX_SITES_ENABLED, NGINX_SITES_AVAILABLE):
            if not directory.exists():
                continue
            for candidate in directory.iterdir():
                if not candidate.is_file() and not candidate.is_symlink():
                    continue
                try:
                    content = candidate.read_text(encoding="utf-8", errors="replace")
                except OSError:
                    continue
                score = 0
                for needle in needles:
                    if needle and needle in content:
                        score += 10 if needle == root else 4
                # Prefer sites that also have SSL / proxy hints for this app name
                name_hint = Path(root).name.lower()
                if name_hint and name_hint in candidate.name.lower():
                    score += 6
                if name_hint and name_hint in content.lower():
                    score += 3
                if score > best_score:
                    best_score = score
                    best = candidate
        return best if best_score >= 6 else None

    @staticmethod
    def _is_enabled(path: Path) -> bool:
        name = path.name
        enabled = NGINX_SITES_ENABLED / name
        if enabled.exists() or enabled.is_symlink():
            try:
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

    @staticmethod
    def _extract_ssl_certificate(content: str) -> str | None:
        match = re.search(r"ssl_certificate\s+([^;]+);", content)
        if not match:
            return None
        path = match.group(1).strip().strip("'\"")
        return path or None
