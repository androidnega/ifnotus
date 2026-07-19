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

    def _build_disabled_stub(self, available_path: Path) -> str:
        content = available_path.read_text(encoding="utf-8", errors="replace")
        names = self._extract_server_names(content)
        if not names:
            names = [available_path.name]
        cert = self._extract_directive(content, "ssl_certificate")
        key = self._extract_directive(content, "ssl_certificate_key")

        blocks: list[str] = [STUB_MARKER, "# Application temporarily disabled by IFNOTUS.", ""]
        names_line = " ".join(names)

        blocks.append("server {")
        blocks.append("    listen 80;")
        blocks.append("    listen [::]:80;")
        blocks.append(f"    server_name {names_line};")
        blocks.append('    return 503 "Application temporarily disabled.\\n";')
        blocks.append("    add_header Retry-After 3600 always;")
        blocks.append("}")
        blocks.append("")

        if cert and key:
            blocks.append("server {")
            blocks.append("    listen 443 ssl;")
            blocks.append("    listen [::]:443 ssl;")
            blocks.append(f"    server_name {names_line};")
            blocks.append(f"    ssl_certificate {cert};")
            blocks.append(f"    ssl_certificate_key {key};")
            blocks.append('    return 503 "Application temporarily disabled.\\n";')
            blocks.append("    add_header Retry-After 3600 always;")
            blocks.append("}")
            blocks.append("")

        return "\n".join(blocks)

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
