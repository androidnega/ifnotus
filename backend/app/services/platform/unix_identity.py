"""PHASE 20 — Real Unix tenant identity for each CustomerEnvironment.

Creates an isolated system user/group (``ifn_<id>``) during provisioning,
owns the environment document root, and removes the identity on terminate.

SFTP (Phase 19) and FTP attach to this identity instead of inventing users.
"""

from __future__ import annotations

import grp
import os
import pwd
import stat
import subprocess
from pathlib import Path
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.exceptions import AppException, ValidationError
from app.core.logging import get_logger
from app.models.platform import CustomerEnvironment, PlatformAuditLog
from app.services.platform.fs_ownership import (
    allocate_unix_ids,
    fix_web_ownership,
    safe_join,
    unix_ids_exist_on_host,
)

logger = get_logger(__name__)

NOLOGIN = "/usr/sbin/nologin"
# Never world-writable.
DIR_MODE = 0o2755  # setgid so new files inherit group where supported
FILE_MODE = 0o664
JAIL_ROOT_MODE = 0o755  # OpenSSH chroot requirement when used as SFTP jail


class UnixIdentityService:
    def __init__(self, settings: Settings, session: AsyncSession) -> None:
        self._settings = settings
        self._session = session

    def username_for(self, env: CustomerEnvironment) -> str:
        if getattr(env, "unix_username", None):
            return str(env.unix_username)
        if env.sftp_username:
            return env.sftp_username
        short = str(env.id).replace("-", "")[:8]
        return f"ifn_{short}"

    def _customers_root(self) -> Path:
        return Path(self._settings.customer_environments_root).resolve()

    def assert_env_home(self, env: CustomerEnvironment, home: Path | None = None) -> Path:
        """Document root must stay under this customer's tree."""
        root = self._customers_root()
        raw = home or Path(env.document_root or "")
        if not str(raw):
            raise AppException("Environment has no document root.", code="unix_no_docroot")
        resolved = Path(raw).resolve()
        customer_prefix = (root / str(env.customer_id)).resolve()
        try:
            resolved.relative_to(customer_prefix)
        except ValueError as exc:
            raise AppException(
                "Environment home must stay inside this customer's hosting space.",
                code="unix_home_outside_tenant",
            ) from exc
        return resolved

    def _user_exists(self, username: str) -> bool:
        try:
            pwd.getpwnam(username)
            return True
        except KeyError:
            return False

    def _group_exists(self, name: str) -> bool:
        try:
            grp.getgrnam(name)
            return True
        except KeyError:
            return False

    def _ensure_group(self, group_name: str, gid: int) -> int:
        if self._group_exists(group_name):
            return grp.getgrnam(group_name).gr_gid
        proc = subprocess.run(
            ["groupadd", "-g", str(gid), group_name],
            capture_output=True,
            text=True,
            check=False,
        )
        if proc.returncode != 0 and "already exists" not in (proc.stderr or ""):
            subprocess.run(["groupadd", group_name], capture_output=True, check=False)
        return grp.getgrnam(group_name).gr_gid

    def _web_gid(self) -> int | None:
        web = self._settings.web_run_user or "www-data"
        try:
            return grp.getgrnam(web).gr_gid
        except KeyError:
            try:
                return pwd.getpwnam(web).pw_gid
            except KeyError:
                return None

    def ensure_ids(self, env: CustomerEnvironment) -> tuple[int, int]:
        if env.unix_uid is None or env.unix_gid is None:
            uid, gid = allocate_unix_ids(env.id)
            env.unix_uid = uid
            env.unix_gid = gid
        return int(env.unix_uid), int(env.unix_gid)

    def ensure_identity(
        self,
        env: CustomerEnvironment,
        *,
        shell: str | None = None,
        actor: str = "system",
    ) -> dict[str, Any]:
        """Create or refresh the OS user/group for this environment.

        Default shell is nologin (no interactive login). Pass a restricted
        shell path only when SSH jail is entitled (Phase 9/19 consumers).
        """
        if env.status == "terminated":
            raise AppException("Cannot create Unix identity for a terminated environment.", code="unix_terminated")

        home = self.assert_env_home(env)
        home.mkdir(parents=True, exist_ok=True)
        uid, gid = self.ensure_ids(env)
        username = self.username_for(env)
        env.unix_username = username
        # Keep SFTP username aligned when SFTP columns exist.
        if not env.sftp_username:
            env.sftp_username = username

        primary_gid = self._ensure_group(username, gid)
        shell_path = shell or NOLOGIN

        if not self._user_exists(username):
            cmd = [
                "useradd",
                "-u",
                str(uid),
                "-g",
                username,
                "-d",
                str(home),
                "-s",
                shell_path,
                "-M",
                username,
            ]
            proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
            if proc.returncode != 0 and "already exists" not in (proc.stderr or ""):
                proc2 = subprocess.run(
                    [
                        "useradd",
                        "-g",
                        username,
                        "-d",
                        str(home),
                        "-s",
                        shell_path,
                        "-M",
                        username,
                    ],
                    capture_output=True,
                    text=True,
                    check=False,
                )
                if proc2.returncode != 0 and "already exists" not in (proc2.stderr or ""):
                    raise AppException(
                        f"Could not create Unix user: {(proc2.stderr or proc.stderr or '')[-300:]}",
                        code="unix_user_create_failed",
                    )
        else:
            subprocess.run(
                ["usermod", "-d", str(home), "-s", shell_path, "-g", username, username],
                capture_output=True,
                check=False,
            )

        # Supplementary web group so nginx/php-fpm can read tenant files (not primary).
        web = self._settings.web_run_user or "www-data"
        if self._group_exists(web) or self._user_exists(web):
            subprocess.run(["usermod", "-aG", web, username], capture_output=True, check=False)

        # Persist actual ids from the host after create.
        try:
            pw = pwd.getpwnam(username)
            env.unix_uid = pw.pw_uid
            env.unix_gid = pw.pw_gid
            uid, gid = pw.pw_uid, pw.pw_gid
        except KeyError as exc:
            raise AppException("Unix user missing after create.", code="unix_user_missing") from exc

        self.apply_ownership(env, prepare_sftp_jail=False)
        # PHASE 32 — best-effort OS user quota (no-op if quotas not enabled on FS)
        try:
            from app.services.platform.environment_storage import apply_os_user_quota

            apply_os_user_quota(
                self._settings,
                username=username,
                home=home,
                storage_limit_gb=env.storage_limit_gb,
            )
        except Exception as exc:  # noqa: BLE001
            logger.debug("os_quota_apply_skipped", error=str(exc))
        self._audit(
            env,
            "unix.ensure",
            detail={"username": username, "uid": uid, "gid": gid, "home": str(home), "actor": actor},
        )
        return {
            "username": username,
            "uid": uid,
            "gid": gid,
            "home": str(home),
            "shell": shell_path,
            "primary_gid": primary_gid,
        }

    def apply_ownership(self, env: CustomerEnvironment, *, prepare_sftp_jail: bool = False) -> None:
        """chown tree to tenant; never chmod 777.

        When ``prepare_sftp_jail`` is True, the document root itself is root:root
        755 (OpenSSH ChrootDirectory) while children stay tenant-owned.
        """
        home = self.assert_env_home(env)
        uid, gid = self.ensure_ids(env)
        if not unix_ids_exist_on_host(uid, gid) and env.unix_username and self._user_exists(env.unix_username):
            pw = pwd.getpwnam(env.unix_username)
            uid, gid = pw.pw_uid, pw.pw_gid
            env.unix_uid, env.unix_gid = uid, gid

        web_gid = self._web_gid()
        effective_gid = web_gid if web_gid is not None else gid

        if prepare_sftp_jail:
            subprocess.run(["chown", "root:root", str(home)], capture_output=True, check=False)
            os.chmod(home, JAIL_ROOT_MODE)
            for child in home.iterdir():
                self._chown_tree(child, uid, effective_gid)
        else:
            self._chown_tree(home, uid, effective_gid)

    def _chown_tree(self, path: Path, uid: int, gid: int) -> None:
        if not path.exists():
            return
        if path.is_symlink():
            # Do not follow symlinks for ownership changes.
            try:
                os.lchown(path, uid, gid)
            except OSError as exc:
                logger.warning("lchown_failed", path=str(path), error=str(exc))
            return
        if path.is_file():
            try:
                os.chown(path, uid, gid)
                mode = stat.S_IMODE(path.stat().st_mode)
                # Strip other-write / sticky world bits; never 777.
                new_mode = (mode | FILE_MODE) & ~0o002 & ~0o111
                if path.stat().st_mode & stat.S_IXUSR:
                    new_mode |= 0o110
                os.chmod(path, new_mode if new_mode else FILE_MODE)
                if stat.S_IMODE(path.stat().st_mode) == 0o777:
                    os.chmod(path, FILE_MODE)
            except OSError as exc:
                logger.warning("chown_file_failed", path=str(path), error=str(exc))
            return

        for dirpath, dirnames, filenames in os.walk(path, followlinks=False):
            dpath = Path(dirpath)
            try:
                os.chown(dpath, uid, gid)
                os.chmod(dpath, DIR_MODE)
            except OSError as exc:
                logger.warning("chown_dir_failed", path=dirpath, error=str(exc))
            for name in dirnames + filenames:
                target = dpath / name
                if target.is_symlink():
                    try:
                        os.lchown(target, uid, gid)
                    except OSError:
                        pass
                    continue
                try:
                    os.chown(target, uid, gid)
                    if target.is_dir():
                        os.chmod(target, DIR_MODE)
                    else:
                        os.chmod(target, FILE_MODE)
                except OSError as exc:
                    logger.warning("chown_file_failed", path=str(target), error=str(exc))

    def set_shell(self, env: CustomerEnvironment, *, enable_jail_shell: bool, jail_shell: str) -> None:
        username = env.unix_username or self.username_for(env)
        if not self._user_exists(username):
            return
        shell = jail_shell if enable_jail_shell else NOLOGIN
        subprocess.run(["usermod", "-s", shell, username], capture_output=True, check=False)

    def lock(self, env: CustomerEnvironment, *, actor: str = "system") -> None:
        username = env.unix_username or env.sftp_username
        if username and self._user_exists(username):
            subprocess.run(["usermod", "-L", username], capture_output=True, check=False)
            subprocess.run(["usermod", "-s", NOLOGIN, username], capture_output=True, check=False)
        self._audit(env, "unix.lock", detail={"username": username, "actor": actor})

    def unlock(self, env: CustomerEnvironment, *, actor: str = "system") -> None:
        username = env.unix_username or env.sftp_username
        if username and self._user_exists(username):
            subprocess.run(["usermod", "-U", username], capture_output=True, check=False)
        self._audit(env, "unix.unlock", detail={"username": username, "actor": actor})

    def remove_identity(self, env: CustomerEnvironment, *, actor: str = "system") -> None:
        """Disable and delete the OS user/group. Does not wipe document_root files."""
        username = env.unix_username or env.sftp_username or self.username_for(env)
        if username and self._user_exists(username):
            subprocess.run(["pkill", "-u", username], capture_output=True, check=False)
            subprocess.run(["userdel", "-f", username], capture_output=True, check=False)
        if username and self._group_exists(username):
            # groupdel fails if still primary for someone; best-effort after userdel
            subprocess.run(["groupdel", username], capture_output=True, check=False)
        env.unix_username = None
        self._audit(env, "unix.remove", detail={"username": username, "actor": actor})

    def resolve_under_home(self, env: CustomerEnvironment, rel: str | Path | None) -> Path:
        """Safe path join under the environment home (blocks .. and symlinks out)."""
        home = self.assert_env_home(env)
        target = safe_join(home, rel)
        # Extra: if target exists via symlink, resolved path must stay in home.
        if target.exists() or target.is_symlink():
            real = target.resolve()
            try:
                real.relative_to(home.resolve())
            except ValueError as exc:
                raise ValidationError("Path escapes the site root via symlink.", code="path_escape") from exc
        return target

    @staticmethod
    def assert_mode_not_world_writable(path: Path) -> None:
        if not path.exists():
            return
        mode = stat.S_IMODE(path.stat().st_mode)
        if mode & stat.S_IWOTH:
            raise ValidationError(
                f"World-writable mode forbidden: {path} ({oct(mode)})",
                code="unix_world_writable",
            )
        if mode == 0o777:
            raise ValidationError("chmod 777 is forbidden.", code="unix_mode_777")

    def _audit(self, env: CustomerEnvironment, action: str, *, detail: dict[str, Any] | None = None) -> None:
        self._session.add(
            PlatformAuditLog(
                customer_id=env.customer_id,
                action=action,
                target_type="environment",
                target_id=str(env.id),
                result="success",
                metadata_json=detail or {},
            )
        )


def tenant_cannot_access(path_a: Path, path_b: Path) -> bool:
    """True when path_b is not under path_a (cross-tenant denial helper for tests)."""
    try:
        path_b.resolve().relative_to(path_a.resolve())
        return False
    except ValueError:
        return True
