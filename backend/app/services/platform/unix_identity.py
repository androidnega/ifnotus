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
USERADD = "/usr/sbin/useradd"
USERMOD = "/usr/sbin/usermod"
GROUPADD = "/usr/sbin/groupadd"
GPASSWD = "/usr/bin/gpasswd"
CHOWN = "/usr/bin/chown"
# Owner + web group only — never world-readable/writable (PHASE 38G).
DIR_MODE = 0o2750  # setgid; www-data group can traverse when used as group
FILE_MODE = 0o640
JAIL_ROOT_MODE = 0o755  # OpenSSH chroot requirement when used as SFTP jail
CUSTOMER_PREFIX_MODE = 0o750  # root:www-data — other tenants cannot enter
CUSTOMERS_ROOT_MODE = 0o750


class UnixIdentityService:
    def __init__(self, settings: Settings, session: AsyncSession) -> None:
        self._settings = settings
        self._session = session

    def username_for(self, env: CustomerEnvironment) -> str:
        if getattr(env, "unix_username", None):
            return str(env.unix_username)
        if env.sftp_username:
            return env.sftp_username
        # Separate from hosting_name / panel_username (spec).
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
        from app.services.platform.customer_storage import resolve_customer_prefix

        customer_prefix = resolve_customer_prefix(
            self._settings,
            customer_id=env.customer_id,
            storage_slug=getattr(env, "storage_slug", None),
            document_root=str(resolved),
        )
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
            [GROUPADD, "-g", str(gid), group_name],
            capture_output=True,
            text=True,
            check=False,
        )
        if proc.returncode != 0 and "already exists" not in (proc.stderr or ""):
            subprocess.run([GROUPADD, group_name], capture_output=True, check=False)
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
                USERADD,
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
                        USERADD,
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
                [USERMOD, "-d", str(home), "-s", shell_path, "-g", username, username],
                capture_output=True,
                check=False,
            )

        # Never put tenants in the web group. Files are owned tenant:www-data so
        # nginx/php-fpm (running as www-data) can read via group bits; if tenants
        # also join www-data they inherit group access to every peer tree.
        self._strip_web_group(username)

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

        When ``prepare_sftp_jail`` is True, the SFTP chroot root is root:root
        755 (OpenSSH ChrootDirectory) while the writable ``public/`` content
        child stays tenant-owned.
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
            content = home
            chroot = home.parent if home.name == "public" else home
            if home.name != "public":
                content = home / "public"
                content.mkdir(parents=True, exist_ok=True)
            subprocess.run([CHOWN, "root:root", str(chroot)], capture_output=True, check=False)
            os.chmod(chroot, JAIL_ROOT_MODE)
            if content.exists():
                self._chown_tree(content, uid, effective_gid)
        else:
            self._chown_tree(home, uid, effective_gid)
        self.harden_path_prefixes(env)

    def harden_path_prefixes(self, env: CustomerEnvironment) -> dict[str, Any]:
        """Lock customers root + per-customer prefix so other tenants cannot traverse."""
        from app.services.platform.fs_ownership import grant_tenant_traverse, harden_customer_prefixes

        web = self._settings.web_run_user or "www-data"
        from app.services.platform.customer_storage import resolve_customer_prefix

        folder = resolve_customer_prefix(
            self._settings,
            customer_id=env.customer_id,
            document_root=env.document_root,
        ).name
        result = harden_customer_prefixes(
            self._customers_root(),
            customer_id=env.customer_id,
            web_user=web,
            customer_folder=folder,
        )
        if env.unix_username:
            result["tenant_traverse"] = grant_tenant_traverse(
                self._customers_root(),
                customer_id=env.customer_id,
                unix_username=env.unix_username,
                customer_folder=folder,
            )
        return result

    def _strip_web_group(self, username: str) -> bool:
        """Remove tenant from www-data (or configured web group). Returns True if removed/attempted."""
        web = self._settings.web_run_user or "www-data"
        if not username or not (self._group_exists(web) or self._user_exists(web)):
            return False
        # Drop supplementary membership even when primary is already correct.
        proc = subprocess.run(
            [GPASSWD, "-d", username, web],
            capture_output=True,
            text=True,
            check=False,
        )
        # Also clear accidental primary-group == www-data by forcing tenant primary below in callers.
        return proc.returncode == 0 or "not a member" in (proc.stderr or "").lower() or "not a member" in (proc.stdout or "").lower()

    def repair_dac(self, env: CustomerEnvironment, *, dry_run: bool = False, actor: str = "system") -> dict[str, Any]:
        """Re-apply tenant ownership + prefix DAC (legacy www-data / world modes)."""
        plan: dict[str, Any] = {
            "environment_id": str(env.id),
            "document_root": env.document_root,
            "unix_username": env.unix_username,
            "dry_run": dry_run,
            "actions": [],
        }
        if not env.document_root:
            plan["actions"].append({"skip": "no_document_root"})
            return plan
        if dry_run:
            plan["actions"].append(
                {
                    "would": "ensure_identity+strip_www_data+apply_ownership+harden_prefixes",
                    "dir_mode": oct(DIR_MODE),
                    "file_mode": oct(FILE_MODE),
                }
            )
            return plan
        self.ensure_identity(env, actor=actor)
        username = env.unix_username or self.username_for(env)
        stripped = self._strip_web_group(username)
        self.apply_ownership(env, prepare_sftp_jail=False)
        doc = Path(env.document_root)
        if doc.name == "public" or (doc / "public").is_dir():
            self.apply_ownership(env, prepare_sftp_jail=True)
        prefixes = self.harden_path_prefixes(env)
        plan["actions"].append(
            {
                "applied": "ownership",
                "stripped_web_group": stripped,
                "prefixes": prefixes,
            }
        )
        self._audit(env, "unix.repair_dac", detail={"actor": actor, "prefixes": prefixes, "stripped_web_group": stripped})
        return plan

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

    def set_login_password(
        self,
        env: CustomerEnvironment,
        password: str,
        *,
        actor: str = "system",
    ) -> str:
        """Set the tenant Unix login password (SSH + SFTP share this OS account).

        Never touches the legacy FTP OS user. Keeps ``ssh_password_encrypted`` and
        ``sftp_password_encrypted`` in sync so the panel matches ``passwd``.
        """
        username = env.unix_username or self.username_for(env)
        if not username:
            raise AppException("Unix identity missing.", code="unix_user_missing")
        if not self._user_exists(username):
            raise AppException("Unix user missing on host.", code="unix_user_missing")
        # Refuse to clobber a dedicated FTP account when names collide in legacy data.
        if env.ftp_username and env.ftp_username == username:
            raise AppException(
                "FTP still shares this Unix account — create a dedicated FTP login first.",
                code="unix_ftp_identity_collision",
            )
        from app.services.hosting.databases import DatabaseManagerService

        proc = subprocess.run(
            ["chpasswd"],
            input=f"{username}:{password}\n",
            text=True,
            capture_output=True,
            check=False,
        )
        if proc.returncode != 0:
            raise AppException(
                f"Could not set Unix password: {(proc.stderr or '')[-300:]}",
                code="unix_password_failed",
            )
        crypto = DatabaseManagerService(self._settings)
        enc = crypto._encrypt(password)
        env.ssh_password_encrypted = enc
        env.sftp_password_encrypted = enc
        self._audit(
            env,
            "unix.password_set",
            detail={"username": username, "actor": actor, "protocols": ["ssh", "sftp"]},
        )
        return username

    def set_shell(self, env: CustomerEnvironment, *, enable_jail_shell: bool, jail_shell: str) -> None:
        username = env.unix_username or self.username_for(env)
        if not self._user_exists(username):
            return
        shell = jail_shell if enable_jail_shell else NOLOGIN
        subprocess.run([USERMOD, "-s", shell, username], capture_output=True, check=False)

    def lock(self, env: CustomerEnvironment, *, actor: str = "system") -> None:
        username = env.unix_username or env.sftp_username
        if username and self._user_exists(username):
            subprocess.run([USERMOD, "-L", username], capture_output=True, check=False)
            subprocess.run([USERMOD, "-s", NOLOGIN, username], capture_output=True, check=False)
        self._audit(env, "unix.lock", detail={"username": username, "actor": actor})

    def unlock(self, env: CustomerEnvironment, *, actor: str = "system") -> None:
        username = env.unix_username or env.sftp_username
        if username and self._user_exists(username):
            subprocess.run([USERMOD, "-U", username], capture_output=True, check=False)
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
