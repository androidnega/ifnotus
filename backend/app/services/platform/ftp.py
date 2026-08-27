"""One FTP account per customer environment (vsftpd + system user).

Each account is chrooted to that environment's document root only — never
the host root, nginx configs, or another customer's tree.
"""

from __future__ import annotations

import ipaddress
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.exceptions import AppException
from app.core.logging import get_logger
from app.models.platform import CustomerEnvironment
from app.services.hosting.databases import DatabaseManagerService
from app.services.platform.plan_matrix import SFTP_BETA_NOTE

logger = get_logger(__name__)

VSFTPD_CONF = Path("/etc/vsftpd.conf")
VSFTPD_USERLIST = Path("/etc/vsftpd.user_list")
VSFTPD_USER_CONF_DIR = Path("/etc/vsftpd/user_conf")
DEFAULT_FTP_HOSTNAME = "ftp.ifnotus.space"
WORDPRESS_FTP_HOSTNAME = "localhost"


class EnvironmentFtpService:
    def __init__(self, settings: Settings, session: AsyncSession) -> None:
        self._settings = settings
        self._session = session
        self._crypto = DatabaseManagerService(settings)

    def _username_for(self, env: CustomerEnvironment) -> str:
        """Dedicated FTP OS identity — never the tenant Unix/SSH/SFTP username."""
        unix = env.unix_username or env.sftp_username
        if env.ftp_username and env.ftp_username != unix:
            return env.ftp_username
        short = str(env.id).replace("-", "")[:10]
        candidate = f"u{short}"
        if unix and candidate == unix:
            candidate = f"ftp{short}"[:32]
        return candidate

    def _assert_not_unix_identity(self, env: CustomerEnvironment, username: str) -> None:
        unix = env.unix_username or env.sftp_username
        if unix and username == unix:
            raise AppException(
                "FTP must use a dedicated OS user, not the SSH/SFTP Unix identity.",
                code="ftp_unix_identity_collision",
            )

    def _customers_root(self) -> Path:
        return Path(self._settings.customer_environments_root).resolve()

    def _assert_tenant_home(self, env: CustomerEnvironment, home: Path) -> Path:
        """Refuse FTP homes outside this customer's tree under customer_environments_root."""
        resolved = home.resolve()
        from app.services.platform.customer_storage import resolve_customer_prefix

        customer_prefix = resolve_customer_prefix(
            self._settings,
            customer_id=env.customer_id,
            document_root=env.document_root or str(resolved),
        )
        try:
            resolved.relative_to(customer_prefix)
        except ValueError as exc:
            raise AppException(
                "FTP home must stay inside this customer's hosting space.",
                code="ftp_home_outside_tenant",
            ) from exc
        return resolved

    def ensure_daemon(self) -> None:
        """Install/configure vsftpd when missing (best-effort on the host)."""
        if not self._settings.ftp_enabled:
            return
        if not shutil.which("vsftpd"):
            proc = subprocess.run(
                ["apt-get", "install", "-y", "vsftpd"],
                capture_output=True,
                text=True,
                timeout=180,
                check=False,
            )
            if proc.returncode != 0:
                raise AppException(
                    f"Could not install FTP service: {(proc.stderr or proc.stdout or '')[-400:]}",
                    code="ftp_install_failed",
                )
        self._write_vsftpd_conf()
        subprocess.run(["systemctl", "enable", "--now", "vsftpd"], capture_output=True, check=False)

    def _write_vsftpd_conf(self) -> None:
        pasv_addr = (self._settings.ftp_pasv_address or self._settings.server_public_ip or "").strip()
        if not self._is_ip(pasv_addr):
            pasv_addr = ""
        VSFTPD_USER_CONF_DIR.mkdir(parents=True, exist_ok=True)
        lines = [
            "listen=YES",
            "listen_ipv6=NO",
            "anonymous_enable=NO",
            "local_enable=YES",
            "write_enable=YES",
            "local_umask=002",
            "dirmessage_enable=YES",
            "use_localtime=YES",
            "xferlog_enable=YES",
            "connect_from_port_20=YES",
            "chroot_local_user=YES",
            "allow_writeable_chroot=YES",
            "secure_chroot_dir=/var/run/vsftpd/empty",
            "pam_service_name=vsftpd",
            "userlist_enable=YES",
            f"userlist_file={VSFTPD_USERLIST}",
            "userlist_deny=NO",
            f"user_config_dir={VSFTPD_USER_CONF_DIR}",
            "pasv_enable=YES",
            f"pasv_min_port={self._settings.ftp_pasv_min_port}",
            f"pasv_max_port={self._settings.ftp_pasv_max_port}",
            "ssl_enable=NO",
            "seccomp_sandbox=NO",
        ]
        if pasv_addr:
            lines.append(f"pasv_address={pasv_addr}")
        VSFTPD_CONF.parent.mkdir(parents=True, exist_ok=True)
        VSFTPD_CONF.write_text("\n".join(lines) + "\n", encoding="utf-8")
        VSFTPD_USERLIST.touch(exist_ok=True)
        Path("/var/run/vsftpd/empty").mkdir(parents=True, exist_ok=True)

    def _write_user_conf(self, username: str, home: Path) -> None:
        """Per-user local_root so FTP never escapes this site's folder."""
        VSFTPD_USER_CONF_DIR.mkdir(parents=True, exist_ok=True)
        conf = VSFTPD_USER_CONF_DIR / username
        conf.write_text(
            "\n".join(
                [
                    f"local_root={home}",
                    "write_enable=YES",
                    "anon_world_readable_only=NO",
                ]
            )
            + "\n",
            encoding="utf-8",
        )

    def _add_to_userlist(self, username: str) -> None:
        VSFTPD_USERLIST.touch(exist_ok=True)
        existing = VSFTPD_USERLIST.read_text(encoding="utf-8").splitlines()
        if username not in existing:
            with VSFTPD_USERLIST.open("a", encoding="utf-8") as fh:
                fh.write(username + "\n")

    def _remove_from_userlist(self, username: str) -> None:
        if not VSFTPD_USERLIST.exists():
            return
        lines = [ln for ln in VSFTPD_USERLIST.read_text(encoding="utf-8").splitlines() if ln.strip() != username]
        VSFTPD_USERLIST.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")

    def _system_user_exists(self, username: str) -> bool:
        try:
            import pwd

            pwd.getpwnam(username)
            return True
        except KeyError:
            return False

    def _create_system_user(
        self,
        username: str,
        home: Path,
        password: str,
        *,
        primary_group: str | None = None,
    ) -> None:
        home.mkdir(parents=True, exist_ok=True)
        # Prefer tenant primary group. Do NOT add FTP users to www-data — that
        # grants cross-tenant read of every tree owned *:www-data. nginx/php-fpm
        # still read via file group ownership (tenant:www-data + 640/2750).
        web_group = self._settings.web_run_user
        group = primary_group or web_group
        if not self._system_user_exists(username):
            cmd = [
                "/usr/sbin/useradd",
                "-d",
                str(home),
                "-s",
                "/usr/sbin/nologin",
                "-g",
                group,
                "-M",
                username,
            ]
            proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
            if proc.returncode != 0 and "already exists" not in (proc.stderr or ""):
                raise AppException(
                    f"Could not create FTP user: {(proc.stderr or '')[-300:]}",
                    code="ftp_user_create_failed",
                )
        else:
            subprocess.run(
                ["/usr/sbin/usermod", "-d", str(home), "-g", group, "-U", username],
                capture_output=True,
                check=False,
            )
        if web_group and web_group != group:
            subprocess.run(
                ["/usr/bin/gpasswd", "-d", username, web_group],
                capture_output=True,
                check=False,
            )
        proc = subprocess.run(
            ["chpasswd"],
            input=f"{username}:{password}\n",
            text=True,
            capture_output=True,
            check=False,
        )
        if proc.returncode != 0:
            raise AppException(
                f"Could not set FTP password: {(proc.stderr or '')[-300:]}",
                code="ftp_password_failed",
            )
        self._add_to_userlist(username)
        self._write_user_conf(username, home)

    async def ensure_account(
        self,
        env: CustomerEnvironment,
        *,
        reset_password: bool = False,
    ) -> dict[str, Any]:
        if not self._settings.ftp_enabled:
            raise AppException("FTP is not enabled on this server.", code="ftp_disabled")
        if not env.document_root:
            raise AppException("This site has no document root yet.", code="ftp_no_home")

        self.ensure_daemon()
        self._ensure_ftp_shell_allowed()
        home = self._assert_tenant_home(env, Path(env.document_root))
        home.mkdir(parents=True, exist_ok=True)

        from app.services.platform.unix_identity import UnixIdentityService

        unix = UnixIdentityService(self._settings, self._session)
        try:
            unix.ensure_identity(env, actor="ftp")
        except Exception as exc:  # noqa: BLE001
            logger.warning("ftp_unix_identity_deferred", error=str(exc))
        # Ownership via tenant identity (no 777).
        unix.apply_ownership(env, prepare_sftp_jail=False)

        username = self._username_for(env)
        self._assert_not_unix_identity(env, username)
        password: str | None = None
        if reset_password or not env.ftp_password_encrypted:
            password = DatabaseManagerService._strong_password(20)
            # Must not equal the Unix/SSH/SFTP secret when present.
            for attr in ("ssh_password_encrypted", "sftp_password_encrypted"):
                blob = getattr(env, attr, None)
                if not blob:
                    continue
                try:
                    other = self._crypto._decrypt(blob)
                    if password == other:
                        password = DatabaseManagerService._strong_password(24)
                        break
                except Exception:  # noqa: BLE001
                    pass
            env.ftp_password_encrypted = self._crypto._encrypt(password)
        else:
            password = self._crypto._decrypt(env.ftp_password_encrypted)

        if not password:
            raise AppException("FTP password missing.", code="ftp_password_missing")

        # Separate FTP OS user (password independent of SSH/SFTP Unix login).
        tenant_group = env.unix_username if env.unix_username else None
        self._create_system_user(username, home, password, primary_group=tenant_group)
        env.ftp_username = username
        env.ftp_home = str(home)
        env.ftp_enabled = True
        await self._session.flush()
        # Shell entitlement may attach to Unix identity — never chpasswd this FTP user from SSH.
        try:
            from app.services.platform.ssh_access import EnvironmentSshService

            await EnvironmentSshService(self._settings, self._session).sync_from_environment(env)
        except Exception as exc:  # noqa: BLE001
            logger.warning("ssh_sync_after_ftp_failed", error=str(exc)[:300])

        payload = self.status_payload(env, reveal=True)
        payload["password"] = password
        return payload

    def _ensure_ftp_shell_allowed(self) -> None:
        """vsftpd PAM includes pam_shells.so — nologin must be listed in /etc/shells."""
        shells = Path("/etc/shells")
        allowed = {"/usr/sbin/nologin", "/sbin/nologin", "/bin/false"}
        existing: set[str] = set()
        if shells.exists():
            existing = {
                line.strip()
                for line in shells.read_text(encoding="utf-8").splitlines()
                if line.strip() and not line.strip().startswith("#")
            }
        missing = sorted(allowed - existing)
        if not missing:
            return
        with shells.open("a", encoding="utf-8") as fh:
            for shell in missing:
                fh.write(f"{shell}\n")

    @staticmethod
    def _is_ip(value: str | None) -> bool:
        host = (value or "").strip().strip("[]")
        if not host:
            return False
        try:
            ipaddress.ip_address(host)
            return True
        except ValueError:
            return False

    def _hostname_from(self, value: str | None) -> str | None:
        raw = (value or "").strip()
        if not raw:
            return None
        host = re.sub(r"^https?://", "", raw, flags=re.I).split("/")[0].split(":")[0].strip().strip(".")
        if not host or self._is_ip(host):
            return None
        return host.lower()

    def _public_host(self) -> str:
        for candidate in (
            self._settings.ftp_public_host,
            "ftp.ifnotus.space",
            self._settings.customer_portal_url,
        ):
            host = self._hostname_from(candidate)
            if host:
                return host
        return DEFAULT_FTP_HOSTNAME

    def reveal_password(self, env: CustomerEnvironment) -> str | None:
        if not env.ftp_password_encrypted:
            return None
        try:
            return self._crypto._decrypt(env.ftp_password_encrypted)
        except Exception:  # noqa: BLE001
            return None

    def status_payload(self, env: CustomerEnvironment, *, reveal: bool = False) -> dict[str, Any]:
        password = self.reveal_password(env) if reveal else None
        return {
            "environment_id": env.id,
            "enabled": bool(env.ftp_enabled and env.ftp_username),
            "username": env.ftp_username,
            "host": self._public_host(),
            "wordpress_host": WORDPRESS_FTP_HOSTNAME,
            "port": self._settings.ftp_port,
            # Absolute home stays server-side only (schema excludes it too).
            "home": None,
            "password_set": bool(env.ftp_password_encrypted),
            "password": password,
            "connection_type": "FTP",
            "sftp_coming_note": SFTP_BETA_NOTE,
            "separate_from_ssh_sftp": True,
            "hint": (
                f"In FileZilla use host {self._public_host()} and port {self._settings.ftp_port} "
                f"with protocol FTP (not SFTP). This FTP login is separate from SSH/SFTP. "
                f"If WordPress asks for a hostname, enter {WORDPRESS_FTP_HOSTNAME}."
            ),
        }

    async def disable(self, env: CustomerEnvironment) -> None:
        if env.ftp_username and self._system_user_exists(env.ftp_username):
            subprocess.run(["/usr/sbin/usermod", "-L", env.ftp_username], capture_output=True, check=False)
            self._remove_from_userlist(env.ftp_username)
        env.ftp_enabled = False
        await self._session.flush()

    async def enable(self, env: CustomerEnvironment) -> None:
        """Re-enable a previously provisioned FTP account (e.g. after suspend restore)."""
        if not env.ftp_username or not env.document_root:
            return
        if self._system_user_exists(env.ftp_username):
            home = self._assert_tenant_home(env, Path(env.document_root))
            subprocess.run(["/usr/sbin/usermod", "-U", "-d", str(home), env.ftp_username], capture_output=True, check=False)
            self._add_to_userlist(env.ftp_username)
            self._write_user_conf(env.ftp_username, home)
        env.ftp_enabled = True
        await self._session.flush()
