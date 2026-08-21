"""Ensure customer site trees are writable by PHP-FPM (www-data)."""

from __future__ import annotations

import grp
import os
import pwd
import shutil
from pathlib import Path

from app.core.logging import get_logger

logger = get_logger(__name__)


def fix_web_ownership(
    root: str | Path,
    *,
    user: str = "www-data",
    group: str | None = None,
) -> None:
    """chown tree to the PHP/nginx user so WordPress can write without FTP."""
    path = Path(root)
    if not path.exists():
        return
    group = group or user
    try:
        uid = pwd.getpwnam(user).pw_uid
        gid = grp.getgrnam(group).gr_gid
    except KeyError:
        logger.warning("web_user_missing", user=user, group=group)
        return

    if path.is_file():
        try:
            os.chown(path, uid, gid)
            os.chmod(path, 0o664)
        except OSError as exc:
            logger.warning("chown_file_failed", path=str(path), error=str(exc))
        return

    for dirpath, dirnames, filenames in os.walk(path):
        try:
            os.chown(dirpath, uid, gid)
            os.chmod(dirpath, 0o775)
        except OSError as exc:
            logger.warning("chown_dir_failed", path=dirpath, error=str(exc))
        for name in dirnames + filenames:
            target = Path(dirpath) / name
            try:
                os.chown(target, uid, gid)
                if target.is_dir():
                    os.chmod(target, 0o775)
                else:
                    os.chmod(target, 0o664)
            except OSError as exc:
                logger.warning("chown_file_failed", path=str(target), error=str(exc))

    # Keep .ifnotus readable/writable for platform jobs
    meta = path / ".ifnotus"
    if meta.exists():
        try:
            os.chown(meta, uid, gid)
            os.chmod(meta, 0o775)
        except OSError:
            pass


def ensure_dir(path: str | Path, *, user: str = "www-data") -> Path:
    p = Path(path)
    p.mkdir(parents=True, exist_ok=True)
    fix_web_ownership(p, user=user)
    return p


def which_or_none(cmd: str) -> str | None:
    return shutil.which(cmd)
