"""Enable / disable Nginx site configs and reload."""

from __future__ import annotations

import shutil
from pathlib import Path

from app.core.config import Settings
from app.schemas.operations import OperationResult
from app.services.applications.config import ApplicationDefinition
from app.services.monitoring.subprocess_util import resolve_binary, run_command


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
        return link.exists() or link.is_symlink()

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
                self._ensure_available(enabled_path, available_path)
                if not (enabled_path.exists() or enabled_path.is_symlink()):
                    if not available_path.exists():
                        return OperationResult(
                            success=False,
                            message=f"Nginx site config not found in sites-available: {available_path}",
                        )
                    enabled_path.symlink_to(available_path)
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

    def _ensure_available(self, enabled_path: Path, available_path: Path) -> None:
        """If the only copy lives in sites-enabled, move it to sites-available."""
        if available_path.exists():
            return
        if enabled_path.exists() and not enabled_path.is_symlink():
            shutil.move(str(enabled_path), str(available_path))

    def _disable_site(self, enabled_path: Path, available_path: Path) -> None:
        if enabled_path.is_symlink() or enabled_path.exists():
            if enabled_path.exists() and not enabled_path.is_symlink() and not available_path.exists():
                shutil.move(str(enabled_path), str(available_path))
            else:
                enabled_path.unlink(missing_ok=True)
            return
        # Already disabled
        return

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
