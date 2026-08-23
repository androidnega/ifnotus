"""Jailed customer SSH — never root, never the operator VPS IP.

All customers see a shared access host/IP (ssh.ifnotus.space).
SSH login is enabled only when the plan is ₵300/month or higher.
Lower packs still see the shared address but cannot open a shell.

PHASE 38E — SSH/SFTP use the tenant Unix identity. Legacy FTP keeps a
separate OS user. Never chpasswd the FTP account from this service.
"""

from __future__ import annotations

import ipaddress
import subprocess
from pathlib import Path
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.exceptions import AppException
from app.core.logging import get_logger
from app.models.platform import CustomerEnvironment, HostingPlan, Subscription
from app.services.hosting.databases import DatabaseManagerService

logger = get_logger(__name__)

SSH_GROUP = "ifnotus-ssh"
CUSTOMER_SHELL = Path("/usr/local/bin/ifnotus-customer-shell")
SSHD_DROPIN = Path("/etc/ssh/sshd_config.d/ifnotus-customers.conf")
DEFAULT_SSH_HOST = "ssh.ifnotus.space"
NOLOGIN = "/usr/sbin/nologin"


class EnvironmentSshService:
    def __init__(self, settings: Settings, session: AsyncSession) -> None:
        self._settings = settings
        self._session = session
        self._crypto = DatabaseManagerService(settings)

    def min_price(self) -> float:
        return float(self._settings.customer_ssh_min_price_ghs or 300)

    def public_host(self) -> str:
        host = (self._settings.customer_ssh_host or DEFAULT_SSH_HOST).strip().lower()
        return host or DEFAULT_SSH_HOST

    def shared_ip(self) -> str | None:
        """Customer-facing shared IP. Never the operator / root host address."""
        raw = (self._settings.customer_shared_ip or "").strip()
        if not raw:
            return None
        try:
            ipaddress.ip_address(raw.split("/")[0].strip("[]"))
        except ValueError:
            return None
        host_ip = (self._settings.server_public_ip or "").strip()
        if host_ip and raw == host_ip:
            logger.warning("customer_shared_ip_matches_host_ip_ignored")
            return None
        return raw

    def unix_username(self, env: CustomerEnvironment) -> str | None:
        return env.unix_username or env.sftp_username

    async def plan_price(self, env: CustomerEnvironment) -> float:
        sub = await self._session.get(Subscription, env.subscription_id)
        if sub is None:
            return 0.0
        plan = await self._session.get(HostingPlan, sub.plan_id)
        if plan is None:
            return 0.0
        return float(plan.price_monthly or 0)

    async def ssh_allowed(self, env: CustomerEnvironment) -> bool:
        sub = await self._session.get(Subscription, env.subscription_id)
        plan = await self._session.get(HostingPlan, sub.plan_id) if sub else None
        from app.services.platform.plan_matrix import ssh_allowed as matrix_ssh

        return matrix_ssh(plan)

    def _ensure_group(self) -> None:
        subprocess.run(["groupadd", "-f", SSH_GROUP], capture_output=True, check=False)

    def _write_customer_shell(self) -> None:
        CUSTOMER_SHELL.parent.mkdir(parents=True, exist_ok=True)
        CUSTOMER_SHELL.write_text(
            "#!/bin/bash\n"
            "# IFNOTUS jailed customer shell — site folder only, never root.\n"
            "cd \"${HOME:-/}\" || exit 1\n"
            "export HOME PATH=/usr/bin:/bin\n"
            "exec /bin/bash --restricted -i\n",
            encoding="utf-8",
        )
        CUSTOMER_SHELL.chmod(0o755)
        shells = Path("/etc/shells")
        line = str(CUSTOMER_SHELL)
        existing = shells.read_text(encoding="utf-8") if shells.exists() else ""
        if line not in existing.splitlines():
            with shells.open("a", encoding="utf-8") as fh:
                fh.write(line + "\n")

    def _write_sshd_dropin(self) -> None:
        SSHD_DROPIN.parent.mkdir(parents=True, exist_ok=True)
        SSHD_DROPIN.write_text(
            "\n".join(
                [
                    "# IFNOTUS customers — jailed SSH, no root, no forwarding.",
                    f"Match Group {SSH_GROUP}",
                    "    PasswordAuthentication yes",
                    "    PubkeyAuthentication no",
                    "    AllowTcpForwarding no",
                    "    X11Forwarding no",
                    "    PermitTunnel no",
                    "    PermitRootLogin no",
                    f"    ForceCommand {CUSTOMER_SHELL}",
                    "",
                ]
            ),
            encoding="utf-8",
        )
        subprocess.run(["systemctl", "reload", "ssh"], capture_output=True, check=False)
        subprocess.run(["systemctl", "reload", "sshd"], capture_output=True, check=False)

    def _user_exists(self, username: str) -> bool:
        try:
            import pwd

            pwd.getpwnam(username)
            return True
        except KeyError:
            return False

    def _set_shell(self, username: str, *, enable: bool) -> None:
        if not self._user_exists(username):
            return
        shell = str(CUSTOMER_SHELL) if enable else NOLOGIN
        subprocess.run(["usermod", "-s", shell, username], capture_output=True, check=False)
        if enable:
            subprocess.run(["usermod", "-aG", SSH_GROUP, username], capture_output=True, check=False)
        else:
            subprocess.run(["gpasswd", "-d", username, SSH_GROUP], capture_output=True, check=False)

    def ensure_ssh_password(self, env: CustomerEnvironment, *, reset: bool = False) -> str:
        """Return the Unix login password used for SSH (same OS account as SFTP)."""
        if not reset and env.ssh_password_encrypted:
            try:
                return self._crypto._decrypt(env.ssh_password_encrypted)
            except Exception:  # noqa: BLE001
                logger.warning("ssh_password_decrypt_failed", env=str(env.id))
        if not reset and env.sftp_password_encrypted:
            try:
                return self._crypto._decrypt(env.sftp_password_encrypted)
            except Exception:  # noqa: BLE001
                pass

        password = DatabaseManagerService._strong_password(20)
        # Must differ from the dedicated FTP secret when present.
        if env.ftp_password_encrypted:
            try:
                ftp_pw = self._crypto._decrypt(env.ftp_password_encrypted)
                if password == ftp_pw:
                    password = DatabaseManagerService._strong_password(24)
            except Exception:  # noqa: BLE001
                pass
        return password

    def reveal_password(self, env: CustomerEnvironment) -> str | None:
        for attr in ("ssh_password_encrypted", "sftp_password_encrypted"):
            blob = getattr(env, attr, None)
            if not blob:
                continue
            try:
                return self._crypto._decrypt(blob)
            except Exception:  # noqa: BLE001
                continue
        return None

    async def ensure_access(self, env: CustomerEnvironment, *, reset_password: bool = False) -> dict[str, Any]:
        """Enable jailed SSH on the tenant Unix identity (never the FTP OS user)."""
        allowed = await self.ssh_allowed(env)
        password: str | None = None
        from app.services.platform.unix_identity import UnixIdentityService

        unix = UnixIdentityService(self._settings, self._session)
        if allowed:
            identity = unix.ensure_identity(env, actor="ssh")
            username = identity["username"]
            if env.ftp_username and env.ftp_username == username:
                from app.services.platform.ftp import EnvironmentFtpService

                # Split legacy shared OS account into dedicated FTP identity.
                await EnvironmentFtpService(self._settings, self._session).ensure_account(env)
            password = self.ensure_ssh_password(env, reset=reset_password)
            self._ensure_group()
            self._write_customer_shell()
            self._write_sshd_dropin()
            self._set_shell(username, enable=True)
            unix.set_login_password(env, password, actor="ssh")
            await self._session.flush()
        else:
            username = self.unix_username(env)
            if username and self._user_exists(username):
                self._set_shell(username, enable=False)
        return self.status_payload(env, allowed=allowed, reveal=True, password=password)

    async def sync_from_environment(self, env: CustomerEnvironment) -> dict[str, Any]:
        """Enable jailed SSH for entitled packs on the Unix identity only."""
        allowed = await self.ssh_allowed(env)
        username = self.unix_username(env)
        if username and self._user_exists(username):
            # Never operate on the dedicated FTP OS user.
            if env.ftp_username and username == env.ftp_username:
                logger.warning(
                    "ssh_sync_skipped_ftp_collision",
                    env=str(env.id),
                    username=username,
                )
                return self.status_payload(env, allowed=allowed)
            self._ensure_group()
            self._write_customer_shell()
            self._write_sshd_dropin()
            self._set_shell(username, enable=allowed)
            if allowed:
                from app.services.platform.unix_identity import UnixIdentityService

                pw = self.ensure_ssh_password(env)
                UnixIdentityService(self._settings, self._session).set_login_password(
                    env, pw, actor="ssh_sync"
                )
                await self._session.flush()
        return self.status_payload(env, allowed=allowed)

    def status_payload(
        self,
        env: CustomerEnvironment,
        *,
        allowed: bool,
        reveal: bool = False,
        password: str | None = None,
    ) -> dict[str, Any]:
        host = self.public_host()
        shared_ip = self.shared_ip()
        username = self.unix_username(env)
        enabled = bool(allowed and username)
        command = f"ssh {username}@{host}" if enabled and username else None
        min_price = int(self.min_price())
        ftp_separate = bool(
            env.ftp_username and username and env.ftp_username != username
        )
        if allowed:
            hint = (
                f"SSH is on for this site. Connect to {host}"
                + (f" ({shared_ip})" if shared_ip else "")
                + ". SSH and SFTP share this Unix login"
                + (
                    "; FTP uses a separate username and password."
                    if ftp_separate
                    else "."
                )
            )
        else:
            hint = (
                f"This pack includes the shared access address, but SSH is locked "
                f"until ₵{min_price}/month. Use SFTP or FTP for file transfer until you upgrade."
            )
        return {
            "environment_id": env.id,
            "ssh_allowed": allowed,
            "enabled": enabled,
            "username": username,
            "host": host,
            "shared_ip": shared_ip,
            "port": 22,
            "password_set": bool(env.ssh_password_encrypted or env.sftp_password_encrypted),
            "password": password if (reveal and allowed) else None,
            "passwords_differ_from_ftp": ftp_separate,
            "shares_password_with_sftp": True,
            "command": command,
            "min_price_ghs": min_price,
            "hint": hint,
            "message": hint,
        }
