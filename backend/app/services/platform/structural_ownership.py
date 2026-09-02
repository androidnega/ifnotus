"""Explicit structural ownership helpers (never recursive tree repair).

RESOURCE_RECONCILIATION must not import or call these for bulk repair.
OWNERSHIP_RECONCILIATION may call :func:`repair_explicit_structural_paths`
with an allow-list of exact paths only.
"""

from __future__ import annotations

import os
import pwd
import grp
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any


class PathClass(str, Enum):
    SYSTEM_STRUCTURAL = "SYSTEM_STRUCTURAL"
    CUSTOMER_CONTENT_ROOT = "CUSTOMER_CONTENT_ROOT"
    CUSTOMER_CONTENT = "CUSTOMER_CONTENT"
    GENERATED = "GENERATED"
    SYMLINK = "SYMLINK"
    RUNTIME = "RUNTIME"
    UNKNOWN = "UNKNOWN"


# Canonical expectations derived from tenant.py + unix_identity/sftp_access.
# Modes from ensure_cpanel_directory_layout; ownership from SFTP jail / harden.
STRUCTURAL_EXPECTATIONS: dict[str, dict[str, Any]] = {
    "site_home": {
        "class": PathClass.SYSTEM_STRUCTURAL,
        "owner": "root",
        "group": "root",
        "mode": 0o755,
        "source": "sftp_access._prepare_chroot_home / ensure_jail_layout",
        "notes": "OpenSSH ChrootDirectory when jail enabled; otherwise may vary",
    },
    "www": {
        "class": PathClass.SYMLINK,
        "owner": "root",
        "group": "root",
        "mode": None,
        "source": "tenant.ensure_cpanel_directory_layout",
        "target": "public_html",
    },
    "public_html": {
        "class": PathClass.CUSTOMER_CONTENT_ROOT,
        "owner": "tenant",
        "group": "www-data",
        "mode": 0o2750,
        "source": "unix_identity.apply_ownership (non-jail content)",
        "notes": "tenant.py lists mkdir mode 755; apply_ownership uses DIR_MODE 2750",
    },
    "public": {
        "class": PathClass.CUSTOMER_CONTENT_ROOT,
        "owner": "tenant",
        "group": "www-data",
        "mode": 0o2750,
        "source": "unix_identity.apply_ownership prepare_sftp_jail=True",
    },
    "public_ftp": {"class": PathClass.SYSTEM_STRUCTURAL, "owner": "root", "group": "root", "mode": 0o750, "source": "tenant.ensure_cpanel_directory_layout"},
    "logs": {"class": PathClass.SYSTEM_STRUCTURAL, "owner": "root", "group": "root", "mode": 0o700, "source": "tenant.ensure_cpanel_directory_layout"},
    "ssl": {"class": PathClass.SYSTEM_STRUCTURAL, "owner": "root", "group": "root", "mode": 0o700, "source": "tenant.ensure_cpanel_directory_layout"},
    "mail": {"class": PathClass.SYSTEM_STRUCTURAL, "owner": "root", "group": "root", "mode": 0o751, "source": "tenant.ensure_cpanel_directory_layout"},
    "tmp": {"class": PathClass.SYSTEM_STRUCTURAL, "owner": "root", "group": "root", "mode": 0o755, "source": "tenant.ensure_cpanel_directory_layout"},
    ".trash": {"class": PathClass.SYSTEM_STRUCTURAL, "owner": "root", "group": "root", "mode": 0o700, "source": "tenant.ensure_cpanel_directory_layout"},
    ".fpanel": {"class": PathClass.SYSTEM_STRUCTURAL, "owner": "root", "group": "root", "mode": 0o755, "source": "tenant.ensure_cpanel_directory_layout"},
    ".cache": {"class": PathClass.SYSTEM_STRUCTURAL, "owner": "root", "group": "root", "mode": 0o700, "source": "tenant.ensure_cpanel_directory_layout"},
    ".ssh": {"class": PathClass.SYSTEM_STRUCTURAL, "owner": "root", "group": "root", "mode": 0o700, "source": "tenant.ensure_cpanel_directory_layout"},
}


# Documented Phase 2A incident — first ExamFlow ensure_identity used default ownership.
EXAMFLOW_OWNERSHIP_INCIDENT: dict[str, Any] = {
    "environment_id": "34a9a20e-d00d-4e3c-9d6e-7cf1dc58d19e",
    "exact_code_path": (
        "UnixIdentityService.ensure_identity → apply_ownership(prepare_sftp_jail=False) "
        "→ _chown_tree(document_root) + harden_path_prefixes"
    ),
    "scope": (
        "document_root only: "
        "/srv/apps/ifnotus-customers/augustinedanqua/student-dev/public_html "
        "(recursive walk, followlinks=False); plus customers_root chown via harden"
    ),
    "target_uid_user": "ifn_34a9a20e",
    "target_gid_group": "www-data (web_run_user effective_gid)",
    "files_content_changed": False,
    "metadata_changed": True,
    "permissions_also_modified": True,
    "dir_mode_applied": "0o2750",
    "file_mode_applied": "0o640",
    "symlink_handling": "os.lchown only; no follow",
    "exclusions": "none under document_root; site-home siblings (logs/ssl/mail/…) not in walk",
}


@dataclass(frozen=True)
class ExplicitPathRepair:
    path: str
    owner: str
    group: str
    mode: int | None = None


def classify_site_relative(name: str, *, is_symlink: bool = False) -> PathClass:
    if is_symlink or name == "www":
        return PathClass.SYMLINK
    spec = STRUCTURAL_EXPECTATIONS.get(name)
    if spec:
        return PathClass(spec["class"])
    return PathClass.UNKNOWN


def repair_explicit_structural_paths(
    repairs: list[ExplicitPathRepair],
    *,
    dry_run: bool = True,
    allowed_roots: list[str] | None = None,
) -> list[dict[str, Any]]:
    """Repair only exact paths. Refuses any path that looks like a recursive flag.

    Never walks directories. Never follows symlinks for chown of children.
    """
    results: list[dict[str, Any]] = []
    roots = [Path(r).resolve() for r in (allowed_roots or [])]
    for item in repairs:
        path = Path(item.path)
        if path.name in {"-R", "--recursive"}:
            raise ValueError("recursive repair refused")
        resolved = path.resolve() if path.exists() and not path.is_symlink() else path
        if roots:
            ok = False
            for root in roots:
                try:
                    (resolved if resolved.exists() else path).resolve().relative_to(root)
                    ok = True
                    break
                except (ValueError, OSError):
                    continue
            if not ok:
                results.append({"path": item.path, "error": "outside_allowed_roots", "changed": False})
                continue
        entry: dict[str, Any] = {
            "path": item.path,
            "owner": item.owner,
            "group": item.group,
            "mode": oct(item.mode) if item.mode is not None else None,
            "dry_run": dry_run,
            "changed": False,
        }
        if dry_run:
            entry["would"] = "lchown_exact_path"
            results.append(entry)
            continue
        if not path.exists() and not path.is_symlink():
            entry["error"] = "missing"
            results.append(entry)
            continue
        uid = pwd.getpwnam(item.owner).pw_uid
        gid = grp.getgrnam(item.group).gr_gid
        os.lchown(path, uid, gid)
        if item.mode is not None and not path.is_symlink():
            os.chmod(path, item.mode)
        entry["changed"] = True
        results.append(entry)
    return results


def plan_sftp_chroot_structural_repairs(
    site_home: str | Path,
    *,
    tenant_user: str | None = None,
) -> list[ExplicitPathRepair]:
    """Exact-path repairs for OpenSSH chroot structural safety (never recursive)."""
    home = Path(site_home)
    # Refuse treating public_html (content root) as the chroot home.
    if home.name in {"public_html", "public", "www"}:
        return []
    repairs: list[ExplicitPathRepair] = [
        ExplicitPathRepair(path=str(home), owner="root", group="root", mode=0o755),
    ]
    www = home / "www"
    if www.exists() or www.is_symlink():
        repairs.append(ExplicitPathRepair(path=str(www), owner="root", group="root", mode=None))
    pftp = home / "public_ftp"
    if pftp.exists():
        repairs.append(ExplicitPathRepair(path=str(pftp), owner="root", group="root", mode=0o750))
    ph = home / "public_html"
    if ph.exists() and not ph.is_symlink() and tenant_user:
        repairs.append(
            ExplicitPathRepair(path=str(ph), owner=tenant_user, group="www-data", mode=0o2750)
        )
    return repairs
