"""Per-site PHP-FPM pools so plan RAM maps to max_children and open_basedir."""

from __future__ import annotations

import re
import subprocess
from decimal import Decimal
from pathlib import Path

from app.core.config import Settings
from app.core.logging import get_logger

logger = get_logger(__name__)

_POOL_NAME = re.compile(r"[^a-z0-9]+")


class PhpFpmPoolService:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._pool_dir = Path("/etc/php/8.3/fpm/pool.d")

    def pool_name(self, hostname: str) -> str:
        safe = _POOL_NAME.sub("-", hostname.lower()).strip("-")[:40] or "site"
        return f"ifnotus-{safe}"

    def socket_for(self, hostname: str) -> Path:
        return Path(f"/run/php/{self.pool_name(hostname)}.sock")

    def ensure_pool(
        self,
        *,
        hostname: str,
        document_root: str,
        ram_gb: float | Decimal | None = None,
    ) -> Path | None:
        if not self._pool_dir.is_dir():
            return None
        name = self.pool_name(hostname)
        sock = self.socket_for(hostname)
        root = Path(document_root).resolve()
        base = root.parent if root.name == "public" else root
        children = max(2, min(12, int(round(float(ram_gb or 0.5) * 4)) or 2))
        conf = self._pool_dir / f"{name}.conf"
        body = "\n".join(
            [
                f"[{name}]",
                "user = www-data",
                "group = www-data",
                f"listen = {sock}",
                "listen.owner = www-data",
                "listen.group = www-data",
                "pm = ondemand",
                f"pm.max_children = {children}",
                "pm.process_idle_timeout = 10s",
                "pm.max_requests = 200",
                f"php_admin_value[open_basedir] = {base}:/tmp",
                "php_admin_value[disable_functions] = exec,passthru,shell_exec,system,proc_open,popen,pcntl_exec",
                "php_admin_flag[allow_url_fopen] = on",
                "",
            ]
        )
        existing = conf.read_text(encoding="utf-8") if conf.exists() else ""
        if existing != body:
            conf.write_text(body, encoding="utf-8")
            reload = subprocess.run(
                ["systemctl", "reload", "php8.3-fpm"],
                capture_output=True,
                text=True,
                check=False,
            )
            if reload.returncode != 0:
                logger.warning("php_fpm_reload_failed", error=(reload.stderr or reload.stdout or "")[-300:])
            else:
                logger.info("php_fpm_pool_ready", pool=name, socket=str(sock))
        return sock if sock.exists() or conf.exists() else None
