"""Real SFTP for customer environments via OpenSSH internal-sftp.

PHASE 19 / 38D — Per-environment Unix user, chroot jail with writable
``public/`` content child, password + SSH key auth. Does NOT grant
interactive shell; that remains ``EnvironmentSshService`` gated by ``ssh.mode``.
"""

from __future__ import annotations

import hashlib
import ipaddress
import os
import re
import secrets
import shutil
import subprocess
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.exceptions import AppException, ValidationError
from app.core.logging import get_logger
from app.models.platform import CustomerEnvironment, HostingPlan, PlatformAuditLog, Subscription
from app.services.hosting.databases import DatabaseManagerService

logger = get_logger(__name__)

SFTP_GROUP = "ifnotus-sftp"
SFTP_CONTENT_DIR = "public"
SSHD_DROPIN = Path("/etc/ssh/sshd_config.d/ifnotus-sftp.conf")
AUTHORIZED_KEYS_DIR = Path("/etc/ssh/ifnotus_authorized_keys")
NOLOGIN = "/usr/sbin/nologin"
DEFAULT_SFTP_HOST = "serverlabsttu.space"
# Fallback hosts customers already know
ALT_SFTP_HOST = "ssh.ifnotus.space"

_SSH_KEY_RE = re.compile(
    r"^(ssh-(?:rsa|ed25519)|ecdsa-sha2-nistp(?:256|384|521)|sk-ssh-ed25519@openssh\.com)"
    r"\s+\S+(?:\s+\S.*)?$"
)


class EnvironmentSftpService:
    def __init__(self, settings: Settings, session: AsyncSession) -> None:
        self._settings = settings
        self._session = session
        self._crypto = DatabaseManagerService(settings)

    def public_host(self) -> str:
        host = (getattr(self._settings, "customer_sftp_host", None) or "").strip().lower()
        if host:
            return host
        zone = (getattr(self._settings, "student_zone", None) or DEFAULT_SFTP_HOST).strip().lower()
        return zone or ALT_SFTP_HOST

    def shared_ip(self) -> str | None:
        raw = (self._settings.customer_shared_ip or "").strip()
        if not raw:
            return None
        try:
            ipaddress.ip_address(raw.split("/")[0].strip("[]"))
        except ValueError:
            return None
        host_ip = (self._settings.server_public_ip or "").strip()
        if host_ip and raw == host_ip:
            return None
        return raw

    def username_for(self, env: CustomerEnvironment) -> str:
        if env.sftp_username:
            return env.sftp_username
        short = str(env.id).replace("-", "")[:8]
        return f"ifn_{short}"

    def _customers_root(self) -> Path:
        return Path(self._settings.customer_environments_root).resolve()

    def _assert_tenant_home(self, env: CustomerEnvironment, home: Path) -> Path:
        root = self._customers_root()
        resolved = home.resolve()
        customer_prefix = (root / str(env.customer_id)).resolve()
        try:
            resolved.relative_to(customer_prefix)
        except ValueError as exc:
            raise AppException(
                "SFTP home must stay inside this customer's hosting space.",
                code="sftp_home_outside_tenant",
            ) from exc
        # Must be the environment document root (or equal), not a sibling env.
        doc = Path(env.document_root or "").resolve()
        if doc.exists() and resolved != doc:
            try:
                resolved.relative_to(doc)
            except ValueError as exc:
                if doc != resolved:
                    raise AppException(
                        "SFTP jail must be this site's document root.",
                        code="sftp_home_wrong_env",
                    ) from exc
        return resolved

    async def plan_for(self, env: CustomerEnvironment) -> HostingPlan | None:
        sub = await self._session.get(Subscription, env.subscription_id)
        if sub is None:
            return None
        return await self._session.get(HostingPlan, sub.plan_id)

    async def sftp_allowed(self, env: CustomerEnvironment) -> bool:
        from app.services.platform.plan_matrix import feature_included

        plan = await self.plan_for(env)
        return feature_included(plan, "sftp")

    def _ensure_group(self) -> None:
        subprocess.run(["groupadd", "-f", SFTP_GROUP], capture_output=True, check=False)

    @staticmethod
    def render_sshd_dropin(*, authorized_keys_dir: Path = AUTHORIZED_KEYS_DIR) -> str:
        """Render sshd Match block for SFTP-only tenants.

        Does not redefine ``Subsystem sftp`` — main sshd_config already has one;
        ``ForceCommand internal-sftp`` is enough. Exclude interactive SSH group so
        dual membership does not force SFTP over the customer shell Match.
        """
        return "\n".join(
            [
                "# IFNOTUS PHASE 38D — SFTP only (no interactive shell).",
                "# Do not add a second Subsystem sftp line (duplicate fails sshd -t).",
                f"Match Group {SFTP_GROUP},!ifnotus-ssh",
                "    PasswordAuthentication yes",
                "    PubkeyAuthentication yes",
                f"    AuthorizedKeysFile {authorized_keys_dir}/%u",
                "    AllowTcpForwarding no",
                "    X11Forwarding no",
                "    PermitTunnel no",
                "    PermitRootLogin no",
                "    AllowAgentForwarding no",
                f"    ForceCommand internal-sftp -d /{SFTP_CONTENT_DIR}",
                "    ChrootDirectory %h",
                "",
            ]
        )

    def install_sshd_dropin(self, *, reload: bool = True) -> None:
        """Write drop-in only after ``sshd -t`` succeeds (never reload on bad config)."""
        AUTHORIZED_KEYS_DIR.mkdir(parents=True, exist_ok=True)
        try:
            AUTHORIZED_KEYS_DIR.chmod(0o755)
        except OSError:
            pass
        SSHD_DROPIN.parent.mkdir(parents=True, exist_ok=True)
        content = self.render_sshd_dropin()
        previous = SSHD_DROPIN.read_text(encoding="utf-8") if SSHD_DROPIN.exists() else None
        fd, tmp_name = tempfile.mkstemp(prefix="ifnotus-sftp-", suffix=".conf", dir=str(SSHD_DROPIN.parent))
        tmp_path = Path(tmp_name)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write(content)
            tmp_path.chmod(0o644)
            tmp_path.replace(SSHD_DROPIN)
            test = subprocess.run(["sshd", "-t"], capture_output=True, text=True, check=False)
            if test.returncode != 0:
                if previous is None:
                    SSHD_DROPIN.unlink(missing_ok=True)
                else:
                    SSHD_DROPIN.write_text(previous, encoding="utf-8")
                err = (test.stderr or test.stdout or "").strip()[-500:]
                raise AppException(
                    f"sshd -t failed; SFTP drop-in not installed: {err}",
                    code="sftp_sshd_invalid",
                )
        except Exception:
            if tmp_path.exists():
                tmp_path.unlink(missing_ok=True)
            raise
        if not reload:
            return
        subprocess.run(["systemctl", "reload", "ssh"], capture_output=True, check=False)
        subprocess.run(["systemctl", "reload", "sshd"], capture_output=True, check=False)

    def _write_sshd_dropin(self) -> None:
        self.install_sshd_dropin(reload=True)

    def jail_paths(self, env: CustomerEnvironment) -> tuple[Path, Path]:
        """Return (chroot_root, writable_content_dir) under the customer tree."""
        raw = Path(env.document_root or "")
        if not str(raw):
            raise AppException("Environment has no document root.", code="sftp_no_docroot")
        doc = raw.resolve()
        root = self._customers_root()
        customer_prefix = (root / str(env.customer_id)).resolve()
        try:
            doc.relative_to(customer_prefix)
        except ValueError as exc:
            raise AppException(
                "SFTP home must stay inside this customer's hosting space.",
                code="sftp_home_outside_tenant",
            ) from exc
        if doc.name == SFTP_CONTENT_DIR:
            chroot = doc.parent
            content = doc
        else:
            chroot = doc
            content = doc / SFTP_CONTENT_DIR
        try:
            chroot.resolve().relative_to(customer_prefix)
        except ValueError as exc:
            raise AppException(
                "SFTP chroot must stay inside this customer's hosting space.",
                code="sftp_home_outside_tenant",
            ) from exc
        return chroot, content

    def ensure_jail_layout(self, env: CustomerEnvironment) -> tuple[Path, Path]:
        """Ensure chroot root + writable public/ child; migrate flat docroots in place."""
        chroot, content = self.jail_paths(env)
        chroot.mkdir(parents=True, exist_ok=True)
        if not content.exists():
            content.mkdir(parents=True, exist_ok=True)
            for child in list(chroot.iterdir()):
                if child.name == SFTP_CONTENT_DIR:
                    continue
                dest = content / child.name
                if dest.exists():
                    continue
                try:
                    shutil.move(str(child), str(dest))
                except OSError as exc:
                    logger.warning("sftp_jail_migrate_failed", path=str(child), error=str(exc))
        env.document_root = str(content.resolve())
        # OpenSSH: chroot must be root-owned and not group/world-writable.
        subprocess.run(["chown", "root:root", str(chroot)], capture_output=True, check=False)
        subprocess.run(["chmod", "755", str(chroot)], capture_output=True, check=False)
        return chroot.resolve(), content.resolve()

    async def _sync_document_root_refs(self, env: CustomerEnvironment, content: Path) -> None:
        """Keep Domain rows + managed nginx root in sync after jail migration."""
        from app.models.hosting import Domain

        result = await self._session.execute(select(Domain).where(Domain.name == env.domain))
        for domain in result.scalars().all():
            domain.document_root = str(content)
        if not env.domain:
            return
        try:
            from app.services.hosting.nginx_provisioner import MANAGED_MARKER, DomainNginxProvisioner

            provisioner = DomainNginxProvisioner(self._settings)
            available, _enabled = provisioner.site_paths(env.domain)
            if not available.exists():
                return
            text = available.read_text(encoding="utf-8", errors="replace")
            if MANAGED_MARKER not in text and "managed-by-ifnotus" not in text:
                return
            updated = re.sub(
                r"(?m)^(\s*root\s+)\S+(\s*;)",
                lambda m: f"{m.group(1)}{content}{m.group(2)}",
                text,
                count=1,
            )
            if updated == text:
                return
            available.write_text(updated, encoding="utf-8")
            test = subprocess.run(["nginx", "-t"], capture_output=True, text=True, check=False)
            if test.returncode != 0:
                available.write_text(text, encoding="utf-8")
                logger.warning("sftp_nginx_root_sync_reverted", domain=env.domain)
                return
            subprocess.run(["systemctl", "reload", "nginx"], capture_output=True, check=False)
        except Exception as exc:  # noqa: BLE001
            logger.warning("sftp_nginx_root_sync_failed", error=str(exc), domain=env.domain)

    def _user_exists(self, username: str) -> bool:
        try:
            import pwd

            pwd.getpwnam(username)
            return True
        except KeyError:
            return False

    def _group_exists(self, name: str) -> bool:
        try:
            import grp

            grp.getgrnam(name)
            return True
        except KeyError:
            return False

    def _prepare_chroot_home(self, home: Path, uid: int, gid: int) -> None:
        """OpenSSH requires ChrootDirectory owned by root and not group/world-writable.

        Site files *inside* the chroot stay owned by the tenant so uploads work.
        """
        home.mkdir(parents=True, exist_ok=True)
        # Root owns the jail root; contents remain tenant-owned.
        subprocess.run(["chown", "root:root", str(home)], capture_output=True, check=False)
        subprocess.run(["chmod", "755", str(home)], capture_output=True, check=False)
        for child in home.iterdir():
            try:
                subprocess.run(
                    ["chown", "-R", f"{uid}:{gid}", str(child)],
                    capture_output=True,
                    check=False,
                )
            except OSError:
                pass
        # Ensure web server can still read site files.
        subprocess.run(["chmod", "-R", "g+rX", str(home)], capture_output=True, check=False)
        web = self._settings.web_run_user or "www-data"
        try:
            import grp

            web_gid = grp.getgrnam(web).gr_gid
            for child in home.rglob("*"):
                try:
                    st = child.stat()
                    os.chown(child, st.st_uid if st.st_uid else uid, web_gid)
                except OSError:
                    pass
        except KeyError:
            pass

    def _ensure_primary_group(self, group_name: str, gid: int) -> None:
        if self._group_exists(group_name):
            return
        proc = subprocess.run(
            ["groupadd", "-g", str(gid), group_name],
            capture_output=True,
            text=True,
            check=False,
        )
        if proc.returncode != 0 and "already exists" not in (proc.stderr or ""):
            # GID collision — create without fixed gid
            subprocess.run(["groupadd", group_name], capture_output=True, check=False)

    def _create_or_update_user(
        self,
        *,
        username: str,
        home: Path,
        uid: int,
        gid: int,
        password: str | None,
        enable: bool,
    ) -> None:
        self._ensure_group()
        primary_group = username  # 1:1 group matching username when possible
        self._ensure_primary_group(primary_group, gid)

        if not self._user_exists(username):
            cmd = [
                "useradd",
                "-u",
                str(uid),
                "-g",
                primary_group,
                "-d",
                str(home),
                "-s",
                NOLOGIN,
                "-M",
                username,
            ]
            proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
            if proc.returncode != 0 and "already exists" not in (proc.stderr or ""):
                # UID collision — retry without fixed uid
                proc2 = subprocess.run(
                    [
                        "useradd",
                        "-g",
                        primary_group,
                        "-d",
                        str(home),
                        "-s",
                        NOLOGIN,
                        "-M",
                        username,
                    ],
                    capture_output=True,
                    text=True,
                    check=False,
                )
                if proc2.returncode != 0 and "already exists" not in (proc2.stderr or ""):
                    raise AppException(
                        f"Could not create SFTP user: {(proc2.stderr or proc.stderr or '')[-300:]}",
                        code="sftp_user_create_failed",
                    )
        else:
            subprocess.run(
                ["usermod", "-d", str(home), "-s", NOLOGIN, "-g", primary_group, username],
                capture_output=True,
                check=False,
            )

        # Supplement: sftp match group; never grant interactive SSH group here.
        if enable:
            subprocess.run(["usermod", "-aG", SFTP_GROUP, username], capture_output=True, check=False)
            subprocess.run(["usermod", "-U", username], capture_output=True, check=False)
        else:
            subprocess.run(["gpasswd", "-d", username, SFTP_GROUP], capture_output=True, check=False)
            subprocess.run(["usermod", "-L", username], capture_output=True, check=False)

        if password:
            proc = subprocess.run(
                ["chpasswd"],
                input=f"{username}:{password}\n",
                text=True,
                capture_output=True,
                check=False,
            )
            if proc.returncode != 0:
                raise AppException(
                    f"Could not set SFTP password: {(proc.stderr or '')[-300:]}",
                    code="sftp_password_failed",
                )

        try:
            import pwd

            pw = pwd.getpwnam(username)
            self._prepare_chroot_home(home, pw.pw_uid, pw.pw_gid)
        except KeyError:
            self._prepare_chroot_home(home, uid, gid)

    def _keys_path(self, username: str) -> Path:
        AUTHORIZED_KEYS_DIR.mkdir(parents=True, exist_ok=True)
        return AUTHORIZED_KEYS_DIR / username

    def _write_authorized_keys(self, username: str, keys: list[dict[str, Any]]) -> None:
        path = self._keys_path(username)
        lines = [str(k.get("public_key") or "").strip() for k in keys if k.get("public_key")]
        path.write_text(("\n".join(lines) + ("\n" if lines else "")), encoding="utf-8")
        path.chmod(0o600)
        subprocess.run(["chown", "root:root", str(path)], capture_output=True, check=False)

    def _audit(
        self,
        env: CustomerEnvironment,
        action: str,
        *,
        detail: dict[str, Any] | None = None,
        result: str = "success",
    ) -> None:
        self._session.add(
            PlatformAuditLog(
                customer_id=env.customer_id,
                action=action,
                target_type="environment",
                target_id=str(env.id),
                result=result,
                metadata_json=detail or {},
            )
        )

    def ensure_password(self, env: CustomerEnvironment, *, reset: bool = False) -> str:
        if not reset and env.sftp_password_encrypted:
            try:
                return self._crypto._decrypt(env.sftp_password_encrypted)
            except Exception:  # noqa: BLE001
                logger.warning("sftp_password_decrypt_failed", env=str(env.id))
        password = DatabaseManagerService._strong_password(20)
        # Must differ from FTP and SSH secrets when present.
        for attr in ("ftp_password_encrypted", "ssh_password_encrypted"):
            blob = getattr(env, attr, None)
            if not blob:
                continue
            try:
                other = self._crypto._decrypt(blob)
                if password == other:
                    password = DatabaseManagerService._strong_password(24)
            except Exception:  # noqa: BLE001
                pass
        env.sftp_password_encrypted = self._crypto._encrypt(password)
        # Keep SSH ciphertext aligned — same Unix account (PHASE 38E).
        env.ssh_password_encrypted = env.sftp_password_encrypted
        return password

    def reveal_password(self, env: CustomerEnvironment) -> str | None:
        if not env.sftp_password_encrypted:
            return None
        try:
            return self._crypto._decrypt(env.sftp_password_encrypted)
        except Exception:  # noqa: BLE001
            return None

    def _keys_list(self, env: CustomerEnvironment) -> list[dict[str, Any]]:
        raw = env.sftp_authorized_keys
        if isinstance(raw, list):
            return [k for k in raw if isinstance(k, dict)]
        return []

    @staticmethod
    def fingerprint_key(public_key: str) -> str:
        parts = public_key.strip().split()
        if len(parts) < 2:
            return ""
        import base64

        try:
            data = base64.b64decode(parts[1] + "===")
        except Exception:  # noqa: BLE001
            data = public_key.encode("utf-8")
        digest = hashlib.sha256(data).digest()
        import base64 as b64

        return "SHA256:" + b64.b64encode(digest).decode("ascii").rstrip("=")

    @staticmethod
    def validate_public_key(public_key: str) -> str:
        text = (public_key or "").strip()
        if not text or "\n" in text.strip():
            # allow single trailing newline only
            text = text.strip()
        if not text or not _SSH_KEY_RE.match(text):
            raise ValidationError(
                "Public key must be a single OpenSSH line (ssh-ed25519 / ssh-rsa / ecdsa).",
                code="sftp_invalid_key",
            )
        return text

    async def ensure_account(
        self,
        env: CustomerEnvironment,
        *,
        reset_password: bool = False,
        enable_password: bool = True,
        actor: str = "system",
    ) -> dict[str, Any]:
        if env.status in {"terminated", "suspended"}:
            raise AppException(
                "SFTP is unavailable while this hosting service is suspended or terminated.",
                code="sftp_env_inactive",
            )
        allowed = await self.sftp_allowed(env)
        if not allowed:
            raise AppException("SFTP is not included on this package.", code="sftp_not_entitled")

        from app.services.platform.unix_identity import UnixIdentityService

        unix = UnixIdentityService(self._settings, self._session)
        identity = unix.ensure_identity(env, actor=actor)
        username = identity["username"]
        env.sftp_username = username

        chroot, content = self.ensure_jail_layout(env)
        await self._sync_document_root_refs(env, content)

        password: str | None = None
        if enable_password:
            password = self.ensure_password(env, reset=reset_password)

        self._ensure_group()
        self.install_sshd_dropin(reload=True)
        # Home = chroot root (%h); writable site files live in /public inside the jail.
        subprocess.run(
            ["usermod", "-d", str(chroot), "-s", NOLOGIN, username],
            capture_output=True,
            check=False,
        )
        # Attach SFTP Match group; never grant interactive SSH group here.
        subprocess.run(["usermod", "-aG", SFTP_GROUP, username], capture_output=True, check=False)
        subprocess.run(["usermod", "-U", username], capture_output=True, check=False)
        if password:
            # PHASE 38E — Unix login password is shared by SSH+SFTP; never FTP.
            if env.ftp_username and env.ftp_username == username:
                from app.services.platform.ftp import EnvironmentFtpService

                await EnvironmentFtpService(self._settings, self._session).ensure_account(env)
            unix.set_login_password(env, password, actor=actor)
        unix.apply_ownership(env, prepare_sftp_jail=True)

        env.sftp_enabled = True
        self._write_authorized_keys(username, self._keys_list(env))
        self._audit(
            env,
            "sftp.ensure",
            detail={
                "username": username,
                "reset_password": reset_password,
                "actor": actor,
                "chroot": str(chroot),
                "content": str(content),
            },
        )
        await self._session.flush()
        return self.status_payload(env, allowed=True, reveal=True, password=password)

    async def disable(self, env: CustomerEnvironment, *, actor: str = "system") -> None:
        username = env.sftp_username or env.unix_username
        env.sftp_enabled = False
        if username and self._user_exists(username):
            subprocess.run(["gpasswd", "-d", username, SFTP_GROUP], capture_output=True, check=False)
        from app.services.platform.unix_identity import UnixIdentityService

        UnixIdentityService(self._settings, self._session).lock(env, actor=actor)
        self._audit(env, "sftp.disable", detail={"username": username, "actor": actor})
        await self._session.flush()

    async def enable(self, env: CustomerEnvironment, *, actor: str = "system") -> None:
        if not await self.sftp_allowed(env):
            return
        if env.status != "active":
            return
        username = env.sftp_username or env.unix_username
        if username and self._user_exists(username):
            subprocess.run(["usermod", "-aG", SFTP_GROUP, username], capture_output=True, check=False)
            from app.services.platform.unix_identity import UnixIdentityService

            UnixIdentityService(self._settings, self._session).unlock(env, actor=actor)
            env.sftp_enabled = True
            self._audit(env, "sftp.enable", detail={"username": username, "actor": actor})
            await self._session.flush()

    async def remove_access(self, env: CustomerEnvironment, *, actor: str = "system") -> None:
        """Detach SFTP group/keys. OS user removal is owned by UnixIdentityService."""
        username = env.sftp_username or env.unix_username
        if username and self._user_exists(username):
            subprocess.run(["gpasswd", "-d", username, SFTP_GROUP], capture_output=True, check=False)
        if username:
            key_path = self._keys_path(username)
            if key_path.exists():
                key_path.unlink(missing_ok=True)
        env.sftp_enabled = False
        env.sftp_authorized_keys = []
        self._audit(env, "sftp.remove", detail={"username": username, "actor": actor})
        await self._session.flush()

    async def add_key(
        self,
        env: CustomerEnvironment,
        *,
        public_key: str,
        name: str | None = None,
        actor: str = "customer",
    ) -> dict[str, Any]:
        if not await self.sftp_allowed(env) or not env.sftp_enabled:
            raise AppException("Enable SFTP before adding keys.", code="sftp_not_ready")
        key = self.validate_public_key(public_key)
        keys = self._keys_list(env)
        fp = self.fingerprint_key(key)
        if any(k.get("fingerprint") == fp for k in keys):
            raise ValidationError("This SSH key is already registered.", code="sftp_key_exists")
        entry = {
            "id": secrets.token_hex(8),
            "name": (name or "key").strip()[:64] or "key",
            "fingerprint": fp,
            "public_key": key,
            "created_at": datetime.now(UTC).isoformat(),
        }
        keys.append(entry)
        env.sftp_authorized_keys = keys
        if env.sftp_username:
            self._write_authorized_keys(env.sftp_username, keys)
        self._audit(env, "sftp.key_add", detail={"key_id": entry["id"], "fingerprint": fp, "actor": actor})
        await self._session.flush()
        return entry

    async def remove_key(
        self,
        env: CustomerEnvironment,
        key_id: str,
        *,
        actor: str = "customer",
    ) -> None:
        keys = self._keys_list(env)
        kept = [k for k in keys if str(k.get("id")) != str(key_id)]
        if len(kept) == len(keys):
            raise ValidationError("SSH key not found.", code="sftp_key_missing")
        env.sftp_authorized_keys = kept
        if env.sftp_username:
            self._write_authorized_keys(env.sftp_username, kept)
        self._audit(env, "sftp.key_remove", detail={"key_id": key_id, "actor": actor})
        await self._session.flush()

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
        username = env.sftp_username
        enabled = bool(allowed and env.sftp_enabled and username)
        keys = [
            {
                "id": k.get("id"),
                "name": k.get("name"),
                "fingerprint": k.get("fingerprint"),
                "created_at": k.get("created_at"),
            }
            for k in self._keys_list(env)
        ]
        if allowed and enabled:
            hint = (
                f"SFTP (SSH File Transfer) on port 22. Host {host}"
                + (f" ({shared_ip})" if shared_ip else "")
                + ". This account has no interactive shell — file transfer only. "
                "SSH (when entitled) uses the same Unix login; FTP is a separate account."
            )
        elif allowed:
            hint = "SFTP is included on this package. Create your SFTP login to upload files securely."
        else:
            hint = "SFTP is not included on this package."
        return {
            "environment_id": env.id,
            "sftp_allowed": allowed,
            "enabled": enabled,
            "username": username,
            "host": host,
            "shared_ip": shared_ip,
            "port": 22,
            "password_auth_enabled": bool(env.sftp_password_encrypted),
            "password_set": bool(env.sftp_password_encrypted),
            "password": password if (reveal and allowed and enabled) else None,
            "connection_type": "SFTP",
            "protocol": "sftp",
            "shell_access": False,
            "shares_password_with_ssh": True,
            "keys": keys,
            "command": f"sftp {username}@{host}" if enabled and username else None,
            "hint": hint,
            "message": hint,
        }
