"""Ensure customer site trees have safe ownership and modes.

PHASE 20 / 38G — Prefer tenant ``unix_uid``/``unix_gid`` when those users exist on
the host. Never use chmod 777. Customer path prefixes are not world-traversable.
Fallback to ``web_run_user`` only when the OS identity has not been provisioned yet.
"""

from __future__ import annotations

import grp
import hashlib
import os
import pwd
import shutil
from pathlib import Path
from typing import Any
from uuid import UUID

from app.core.exceptions import ValidationError
from app.core.logging import get_logger

logger = get_logger(__name__)

# Inclusive range for tenant unix ids (30_000 slots).
UNIX_UID_MIN = 20000
UNIX_UID_MAX = 49999
UNIX_ID_SPAN = UNIX_UID_MAX - UNIX_UID_MIN + 1

DIR_MODE_SAFE = 0o2750
FILE_MODE_SAFE = 0o640
CUSTOMER_PREFIX_MODE = 0o750
CUSTOMERS_ROOT_MODE = 0o750


def allocate_unix_ids(environment_id: UUID | str) -> tuple[int, int]:
    """Deterministic (uid, gid) in 20000–49999 from the environment UUID hash.

    Collision risk: the space has only ~30k slots. With a few thousand
    environments the birthday-paradox collision chance becomes material; ids
    are advisory until unique system users are provisioned and collisions are
    detected at useradd time.
    """
    digest = hashlib.sha256(str(environment_id).encode("utf-8")).digest()
    offset = int.from_bytes(digest[:4], "big") % UNIX_ID_SPAN
    uid = UNIX_UID_MIN + offset
    gid_offset = int.from_bytes(digest[4:8], "big") % UNIX_ID_SPAN
    gid = UNIX_UID_MIN + gid_offset
    return uid, gid


def unix_ids_exist_on_host(uid: int, gid: int) -> bool:
    """True when both numeric ids resolve to real passwd/group entries."""
    try:
        pwd.getpwuid(uid)
        grp.getgrgid(gid)
        return True
    except KeyError:
        return False


def safe_join(root: str | Path, rel: str | Path | None) -> Path:
    """Join ``rel`` under ``root``, rejecting ``..`` and absolute escapes."""
    base = Path(root).resolve()
    raw = "" if rel is None else str(rel).strip()
    if raw in {"", ".", "./"}:
        return base
    candidate = Path(raw)
    if candidate.is_absolute():
        raise ValidationError("Path must be relative to the site root.", code="path_escape")
    parts = candidate.parts
    if any(p == ".." for p in parts):
        raise ValidationError("Path must not contain '..'.", code="path_escape")
    joined = (base / candidate).resolve()
    try:
        joined.relative_to(base)
    except ValueError as exc:
        raise ValidationError("Path escapes the site root.", code="path_escape") from exc
    return joined


def ownership_plan(
    *,
    tenant_uid: int,
    web_gid: int,
    prepare_sftp_jail: bool = False,
) -> dict[str, Any]:
    """Describe intended DAC layout (for tests / dry-run reports)."""
    return {
        "content_owner_uid": tenant_uid,
        "content_group_gid": web_gid,
        "dir_mode": oct(DIR_MODE_SAFE),
        "file_mode": oct(FILE_MODE_SAFE),
        "world_readable": False,
        "world_writable": False,
        "sftp_chroot_root_owned": prepare_sftp_jail,
        "customer_prefix_mode": oct(CUSTOMER_PREFIX_MODE),
    }


def harden_customer_prefixes(
    customers_root: str | Path,
    *,
    customer_id: UUID | str,
    web_user: str = "www-data",
) -> dict[str, Any]:
    """Make customers root + per-customer prefix non-world-traversable."""
    root = Path(customers_root)
    result: dict[str, Any] = {"customers_root": str(root), "customer_id": str(customer_id)}
    try:
        web_gid = grp.getgrnam(web_user).gr_gid
    except KeyError:
        try:
            web_gid = pwd.getpwnam(web_user).pw_gid
        except KeyError:
            result["error"] = "web_user_missing"
            return result

    if root.exists():
        try:
            os.chown(root, 0, web_gid)
        except OSError as exc:
            result["customers_root_chown_error"] = str(exc)
        try:
            os.chmod(root, CUSTOMERS_ROOT_MODE)
            result["customers_root_mode"] = oct(CUSTOMERS_ROOT_MODE)
        except OSError as exc:
            result["customers_root_error"] = str(exc)

    prefix = root / str(customer_id)
    if prefix.exists():
        try:
            os.chown(prefix, 0, web_gid)
        except OSError as exc:
            result["customer_prefix_chown_error"] = str(exc)
        try:
            os.chmod(prefix, CUSTOMER_PREFIX_MODE)
            result["customer_prefix"] = str(prefix)
            result["customer_prefix_mode"] = oct(CUSTOMER_PREFIX_MODE)
        except OSError as exc:
            result["customer_prefix_error"] = str(exc)
    return result


def fix_web_ownership(
    root: str | Path,
    *,
    user: str = "www-data",
    group: str | None = None,
    uid: int | None = None,
    gid: int | None = None,
) -> None:
    """chown tree to tenant uid with web group, or web user fallback. Never 777."""
    path = Path(root)
    if not path.exists():
        return

    use_uid: int | None = None
    use_gid: int | None = None
    if uid is not None and gid is not None and unix_ids_exist_on_host(uid, gid):
        use_uid = uid
        try:
            use_gid = grp.getgrnam(user).gr_gid
        except KeyError:
            use_gid = gid
    else:
        if uid is not None and gid is not None:
            logger.info(
                "tenant_unix_ids_not_on_host",
                uid=uid,
                gid=gid,
                fallback=user,
                note="Intended ids stored for future; using web_run_user for chown.",
            )
        group = group or user
        try:
            use_uid = pwd.getpwnam(user).pw_uid
            use_gid = grp.getgrnam(group).gr_gid
        except KeyError:
            logger.warning("web_user_missing", user=user, group=group)
            return

    assert use_uid is not None and use_gid is not None

    if path.is_file():
        try:
            os.chown(path, use_uid, use_gid)
            os.chmod(path, FILE_MODE_SAFE)
        except OSError as exc:
            logger.warning("chown_file_failed", path=str(path), error=str(exc))
        return

    for dirpath, dirnames, filenames in os.walk(path, followlinks=False):
        try:
            os.chown(dirpath, use_uid, use_gid)
            os.chmod(dirpath, DIR_MODE_SAFE)
        except OSError as exc:
            logger.warning("chown_dir_failed", path=dirpath, error=str(exc))
        for name in dirnames + filenames:
            target = Path(dirpath) / name
            if target.is_symlink():
                try:
                    os.lchown(target, use_uid, use_gid)
                except OSError:
                    pass
                continue
            try:
                os.chown(target, use_uid, use_gid)
                if target.is_dir():
                    os.chmod(target, DIR_MODE_SAFE)
                else:
                    os.chmod(target, FILE_MODE_SAFE)
            except OSError as exc:
                logger.warning("chown_file_failed", path=str(target), error=str(exc))

    meta = path / ".ifnotus"
    if meta.exists():
        try:
            os.chown(meta, use_uid, use_gid)
            os.chmod(meta, DIR_MODE_SAFE)
        except OSError:
            pass


def ensure_dir(path: str | Path, *, user: str = "www-data") -> Path:
    p = Path(path)
    p.mkdir(parents=True, exist_ok=True)
    fix_web_ownership(p, user=user)
    return p


def which_or_none(cmd: str) -> str | None:
    return shutil.which(cmd)
