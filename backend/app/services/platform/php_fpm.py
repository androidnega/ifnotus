"""Per-site PHP-FPM pools so plan RAM maps to max_children and open_basedir."""

from __future__ import annotations

import pwd
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

    @staticmethod
    def _unix_user_exists(name: str) -> bool:
        try:
            pwd.getpwnam(name)
            return True
        except KeyError:
            return False

    def ensure_pool(
        self,
        *,
        hostname: str,
        document_root: str,
        ram_gb: float | Decimal | None = None,
        unix_user: str | None = None,
    ) -> Path | None:
        if not self._pool_dir.is_dir():
            return None
        name = self.pool_name(hostname)
        sock = self.socket_for(hostname)
        root = Path(document_root).resolve()
        base = root.parent if root.name == "public" else root
        children = max(2, min(12, int(round(float(ram_gb or 0.5) * 4)) or 2))
        conf = self._pool_dir / f"{name}.conf"
        run_user = (unix_user or "").strip()

        if not run_user:
            for check_path in (root, base, root / "public"):
                if check_path.exists():
                    try:
                        stat_info = check_path.stat()
                        owner_name = pwd.getpwuid(stat_info.st_uid).pw_name
                        if owner_name not in ("root", "www-data", "nobody", "bin", "daemon"):
                            run_user = owner_name
                            break
                    except Exception:
                        pass

        if not run_user:
            run_user = "www-data"

        if run_user != "www-data" and not self._unix_user_exists(run_user):
            logger.warning("php_fpm_user_missing_fallback_www_data", pool=name, user=run_user)
            run_user = "www-data"

        run_group = run_user if run_user != "www-data" else "www-data"
        if run_user != "www-data":
            try:
                subprocess.run(["usermod", "-aG", run_user, "www-data"], capture_output=True, check=False)
            except Exception:
                pass
            # Ensure parent directories up to /srv/apps/ifnotus-customers are traversable by tenant unix user
            try:
                curr = base
                while curr and curr != curr.parent:
                    curr = curr.parent
                    if curr.exists() and (curr.name in ("ifnotus-customers", "apps", "srv") or str(curr).startswith("/srv/apps")):
                        st = curr.stat()
                        if (st.st_mode & 0o111) != 0o111:
                            curr.chmod(st.st_mode | 0o755)
            except Exception:
                pass

        # Socket must stay www-data-owned so nginx can connect.
        body = "\n".join(
            [
                f"[{name}]",
                f"user = {run_user}",
                f"group = {run_group}",
                f"listen = {sock}",
                "listen.owner = www-data",
                "listen.group = www-data",
                "listen.mode = 0660",
                "pm = ondemand",
                f"pm.max_children = {children}",
                "pm.process_idle_timeout = 10s",
                "pm.max_requests = 200",
                f"php_admin_value[open_basedir] = {base}:/tmp:/var/tmp",
                "php_admin_value[disable_functions] = exec,passthru,shell_exec,system,proc_open,popen,pcntl_exec",
                "php_admin_flag[allow_url_fopen] = on",
                "",
            ]
        )
        existing = conf.read_text(encoding="utf-8") if conf.exists() else ""
        if existing != body:
            previous = existing
            conf.write_text(body, encoding="utf-8")
            if not self._fpm_config_ok():
                # Roll back — never leave php-fpm unable to start (breaks all PHP sites).
                if previous:
                    conf.write_text(previous, encoding="utf-8")
                else:
                    conf.unlink(missing_ok=True)
                if run_user != "www-data":
                    logger.warning("php_fpm_pool_invalid_retry_www_data", pool=name, user=run_user)
                    return self.ensure_pool(
                        hostname=hostname,
                        document_root=document_root,
                        ram_gb=ram_gb,
                        unix_user="www-data",
                    )
                logger.error("php_fpm_pool_config_invalid", pool=name)
                self._reload_or_start_fpm(pool=name, sock=sock)
                return None
            self._reload_or_start_fpm(pool=name, sock=sock)
        return sock if sock.exists() or conf.exists() else None

    def remove_pool(self, hostname: str) -> None:
        """Delete the per-site pool so terminate cannot leave orphan users in FPM config."""
        if not self._pool_dir.is_dir() or not hostname:
            return
        name = self.pool_name(hostname)
        conf = self._pool_dir / f"{name}.conf"
        if not conf.exists():
            return
        conf.unlink(missing_ok=True)
        logger.info("php_fpm_pool_removed", pool=name)
        self._reload_or_start_fpm(pool=name, sock=self.socket_for(hostname))

    def _fpm_config_ok(self) -> bool:
        binary = Path("/usr/sbin/php-fpm8.3")
        cmd = [str(binary) if binary.exists() else "php-fpm8.3", "-t"]
        proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
        return proc.returncode == 0

    def _reload_or_start_fpm(self, *, pool: str, sock: Path) -> None:
        active = subprocess.run(
            ["systemctl", "is-active", "--quiet", "php8.3-fpm"],
            capture_output=True,
            check=False,
        )
        action = "reload" if active.returncode == 0 else "start"
        proc = subprocess.run(
            ["systemctl", action, "php8.3-fpm"],
            capture_output=True,
            text=True,
            check=False,
        )
        if proc.returncode != 0 and action == "reload":
            proc = subprocess.run(
                ["systemctl", "start", "php8.3-fpm"],
                capture_output=True,
                text=True,
                check=False,
            )
        if proc.returncode != 0:
            logger.warning(
                "php_fpm_reload_failed",
                pool=pool,
                error=(proc.stderr or proc.stdout or "")[-300:],
            )
        else:
            logger.info("php_fpm_pool_ready", pool=pool, socket=str(sock), action=action)
