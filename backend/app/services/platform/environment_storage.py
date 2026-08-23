"""PHASE 32 / 38F — real environment + host storage quotas."""

from __future__ import annotations

import asyncio
import shutil
import subprocess
from pathlib import Path
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.logging import get_logger
from app.models.platform import CustomerEnvironment, EnvironmentBackup, HostingPlan
from app.services.platform.usage import HARD_PCT, HIGH_PCT, WARN_PCT, measure_path_usage, usage_snapshot

logger = get_logger(__name__)


def host_storage_pressure(settings: Settings) -> dict[str, Any]:
    """Host volume pressure with 80 / 90 / 95 levels + minimum free GB."""
    root = getattr(settings, "customer_environments_root", None) or "/"
    path = Path(root)
    target = path if path.exists() else Path("/")
    usage = shutil.disk_usage(str(target))
    used_pct = round((usage.used / usage.total) * 100, 1) if usage.total else 0.0
    free_gb = round(usage.free / (1024**3), 2)
    warn = float(getattr(settings, "host_disk_warn_pct", 80) or 80)
    high = float(getattr(settings, "host_disk_high_pct", 90) or 90)
    crit = float(getattr(settings, "host_disk_crit_pct", 95) or 95)
    min_free = float(getattr(settings, "infra_min_free_storage_gb", 20) or 20)

    level = "ok"
    if used_pct >= crit or free_gb < min_free:
        level = "critical"
    elif used_pct >= high:
        level = "high"
    elif used_pct >= warn:
        level = "warning"

    return {
        "path": str(target),
        "total_bytes": usage.total,
        "used_bytes": usage.used,
        "free_bytes": usage.free,
        "used_pct": used_pct,
        "free_gb": free_gb,
        "min_free_gb": min_free,
        "warn_pct": warn,
        "high_pct": high,
        "crit_pct": crit,
        "level": level,
        "block_provisioning": level == "critical",
        "block_storage_upgrades": level in {"high", "critical"},
    }


def should_block_provisioning(settings: Settings, *, pressure: dict[str, Any] | None = None) -> bool:
    snap = pressure or host_storage_pressure(settings)
    block = bool(snap.get("block_provisioning")) or str(snap.get("level") or "") == "critical"
    if block:
        logger.warning(
            "host_disk_blocks_provisioning",
            used_pct=snap.get("used_pct"),
            free_gb=snap.get("free_gb"),
            path=snap.get("path"),
        )
    return block


def should_block_storage_upgrade(
    settings: Settings,
    *,
    extra_gb: float = 0,
    pressure: dict[str, Any] | None = None,
) -> bool:
    """Block plan upgrades that need more disk when the host is high/critical."""
    snap = pressure or host_storage_pressure(settings)
    level = str(snap.get("level") or "")
    if float(extra_gb or 0) <= 0:
        return False
    if snap.get("block_provisioning") or level == "critical":
        return True
    free_gb = float(snap.get("free_gb") or 0)
    min_free = float(snap.get("min_free_gb") or 20)
    if free_gb - float(extra_gb or 0) < min_free:
        return True
    return bool(snap.get("block_storage_upgrades")) or level in {"high", "critical"}


def _detect_mount(path: Path) -> tuple[str | None, str | None]:
    """Return (mountpoint, fstype) for path."""
    try:
        proc = subprocess.run(
            ["findmnt", "-n", "-o", "TARGET,FSTYPE", "--target", str(path)],
            capture_output=True,
            text=True,
            check=False,
            timeout=5,
        )
        if proc.returncode == 0 and proc.stdout.strip():
            parts = proc.stdout.strip().split()
            if len(parts) >= 2:
                return parts[0], parts[1]
            if parts:
                return parts[0], None
    except (OSError, subprocess.SubprocessError):
        pass
    return None, None


def _mount_options(mount: str) -> str:
    try:
        proc = subprocess.run(
            ["findmnt", "-n", "-o", "OPTIONS", mount],
            capture_output=True,
            text=True,
            check=False,
            timeout=5,
        )
        if proc.returncode == 0:
            return (proc.stdout or "").strip().lower()
    except (OSError, subprocess.SubprocessError):
        pass
    return ""


def mount_supports_usrquota(mount: str | None) -> bool:
    """True when mount options advertise usrquota / quota (ext4/xfs style)."""
    if not mount:
        return False
    opts = _mount_options(mount)
    tokens = {p.strip() for p in opts.replace(",", " ").split() if p.strip()}
    if "usrquota" in tokens or "quota" in tokens:
        return True
    return any(t.startswith("usrjquota=") or t.startswith("jqfmt=") for t in tokens)


def quotas_actively_on(mount: str | None) -> bool:
    """True when ``quotaon -p`` reports user quotas are on for mount."""
    if not mount:
        return False
    try:
        proc = subprocess.run(
            ["quotaon", "-p", mount],
            capture_output=True,
            text=True,
            check=False,
            timeout=5,
        )
        text = f"{proc.stdout or ''}\n{proc.stderr or ''}".lower()
        if "user quota" in text and ("is on" in text or "on" == text.strip()):
            return True
        # Common: "user quota on /dev/loopX (/path) is on"
        if "user quota" in text and "is on" in text:
            return True
        if "user quotas are on" in text:
            return True
    except (OSError, subprocess.SubprocessError):
        pass
    return False


def quota_tools_present() -> bool:
    return shutil.which("setquota") is not None and shutil.which("quotaon") is not None


def build_setquota_argv(
    *,
    username: str,
    mount: str,
    storage_limit_gb: float,
    warn_pct: float = WARN_PCT,
) -> list[str]:
    """Build ``setquota -u`` argv. Blocks are KiB (1024-byte)."""
    limit_gb = max(float(storage_limit_gb or 0), 0.0)
    hard_kb = max(int(limit_gb * 1024 * 1024), 1)
    soft_kb = max(int(hard_kb * (float(warn_pct) / 100.0)), 1)
    hard_inodes = max(10_000, min(2_000_000, int(limit_gb * 50_000)))
    soft_inodes = max(1, int(hard_inodes * (float(warn_pct) / 100.0)))
    return [
        "setquota",
        "-u",
        username,
        str(soft_kb),
        str(hard_kb),
        str(soft_inodes),
        str(hard_inodes),
        mount,
    ]


def os_quota_runtime_ready(settings: Settings, home: str | Path | None) -> dict[str, Any]:
    """Probe whether hard OS user quotas can actually be applied on this host."""
    enabled = bool(getattr(settings, "os_user_quota_enabled", True))
    mount, fstype = _detect_mount(
        Path(home or getattr(settings, "customer_environments_root", "/") or "/")
    )
    tools = quota_tools_present()
    usrquota = mount_supports_usrquota(mount)
    active = quotas_actively_on(mount) if (tools and mount) else False
    ready = bool(enabled and tools and usrquota and active and mount)
    return {
        "settings_enabled": enabled,
        "tools_present": tools,
        "mount": mount,
        "fstype": fstype,
        "usrquota_enabled": usrquota,
        "quotas_active": active,
        "ready": ready,
        "soft_tracking_only": not ready,
    }


def apply_os_user_quota(
    settings: Settings,
    *,
    username: str | None,
    home: str | Path | None,
    storage_limit_gb: int | float | None,
) -> dict[str, Any]:
    """Apply Linux user quota via ``setquota`` when the filesystem is quota-ready.

    Never reports ``applied=True`` unless setquota succeeds. When settings claim
    quotas are on but the host is not ready, returns an honest soft-tracking state.
    """
    result: dict[str, Any] = {
        "applied": False,
        "available": False,
        "hard_enforced": False,
        "soft_tracking_only": True,
        "username": username,
        "message": "OS quotas not applied",
    }
    probe = os_quota_runtime_ready(settings, home)
    result.update(
        {
            "settings_enabled": probe["settings_enabled"],
            "tools_present": probe["tools_present"],
            "mount": probe["mount"],
            "fstype": probe["fstype"],
            "usrquota_enabled": probe["usrquota_enabled"],
            "quotas_active": probe.get("quotas_active"),
        }
    )

    if not probe["settings_enabled"]:
        result["message"] = "OS user quotas disabled in settings (soft panel tracking only)"
        return result
    if not username or not home:
        result["message"] = "Missing unix user or home"
        return result
    if not probe["tools_present"]:
        result["message"] = "quota tools missing (setquota/quotaon) — soft panel tracking only"
        logger.warning("os_quota_tools_missing", username=username)
        return result
    if not probe["mount"]:
        result["message"] = "Could not detect filesystem mount"
        return result
    if not probe["usrquota_enabled"] or not probe.get("quotas_active"):
        result["message"] = (
            f"Mount {probe['mount']} quotas not active — soft panel tracking only"
        )
        logger.warning(
            "os_quota_mount_not_ready",
            username=username,
            mount=probe["mount"],
            fstype=probe["fstype"],
            usrquota=probe["usrquota_enabled"],
            active=probe.get("quotas_active"),
        )
        return result

    limit_gb = max(float(storage_limit_gb or 0), 0.0)
    if limit_gb <= 0:
        result["message"] = "No storage limit"
        result["available"] = True
        return result

    argv = build_setquota_argv(
        username=username,
        mount=str(probe["mount"]),
        storage_limit_gb=limit_gb,
    )
    result["soft_kb"] = int(argv[3])
    result["hard_kb"] = int(argv[4])
    result["soft_inodes"] = int(argv[5])
    result["hard_inodes"] = int(argv[6])
    result["available"] = True

    try:
        proc = subprocess.run(
            argv,
            capture_output=True,
            text=True,
            check=False,
            timeout=15,
        )
        if proc.returncode == 0:
            result["applied"] = True
            result["hard_enforced"] = True
            result["soft_tracking_only"] = False
            result["message"] = "OS user hard quota applied"
        else:
            err = (proc.stderr or proc.stdout or "").strip()[-300:]
            result["message"] = err or f"setquota exit {proc.returncode}"
            logger.warning(
                "os_quota_not_applied",
                username=username,
                mount=probe["mount"],
                error=result["message"],
            )
    except (OSError, subprocess.SubprocessError) as exc:
        result["message"] = str(exc)
        logger.warning("os_quota_apply_error", username=username, error=str(exc))
    return result


class EnvironmentStorageService:
    """Composite per-environment storage accounting (disk, DB, mail, backups, logs)."""

    def __init__(self, settings: Settings, session: AsyncSession) -> None:
        self._settings = settings
        self._session = session

    async def composite_snapshot(
        self,
        env: CustomerEnvironment,
        plan: HostingPlan | None = None,
    ) -> dict[str, Any]:
        root = env.document_root
        disk = usage_snapshot(root, env.storage_limit_gb)

        logs_bytes, _logs_files = await asyncio.to_thread(
            measure_path_usage, Path(root or ".") / ".ifnotus" / "cron-logs" if root else None
        )
        ifnotus_bytes, _ = await asyncio.to_thread(
            measure_path_usage, Path(root or ".") / ".ifnotus" if root else None
        )

        backup_bytes = int(
            (
                await self._session.execute(
                    select(func.coalesce(func.sum(EnvironmentBackup.file_size), 0)).where(
                        EnvironmentBackup.environment_id == env.id,
                        EnvironmentBackup.status == "success",
                    )
                )
            ).scalar_one()
            or 0
        )

        db_mb = 0.0
        try:
            from app.services.platform.environment_databases import EnvironmentDatabaseService

            rows = await EnvironmentDatabaseService(self._settings, self._session).list_databases(
                env, plan
            )
            db_mb = round(sum(float(r.size_mb or 0) for r in rows if r.size_mb is not None), 2)
        except Exception as exc:  # noqa: BLE001
            logger.debug("storage_db_size_failed", error=str(exc))

        mail_mb = 0.0
        if env.domain:
            vmail = Path(getattr(self._settings, "mail_vmail_dir", "/var/vmail")) / env.domain
            mail_bytes, _ = await asyncio.to_thread(measure_path_usage, vmail)
            mail_mb = round(mail_bytes / (1024 * 1024), 1)

        components = {
            "site_bytes": int(disk["storage_used_bytes"]),
            "logs_bytes": int(logs_bytes),
            "ifnotus_meta_bytes": int(ifnotus_bytes),
            "backup_bytes": backup_bytes,
            "database_mb": db_mb,
            "mail_mb": mail_mb,
            "inode_file_count": int(disk["file_count"]),
        }

        status = str(disk["storage_status"])
        pct = float(disk["storage_pct"])
        if pct >= HARD_PCT:
            tier = "critical"
        elif pct >= HIGH_PCT:
            tier = "high"
        elif pct >= WARN_PCT:
            tier = "warning"
        else:
            tier = "ok"

        os_quota = apply_os_user_quota(
            self._settings,
            username=env.unix_username,
            home=env.document_root,
            storage_limit_gb=env.storage_limit_gb,
        )

        if os_quota.get("hard_enforced"):
            note = "Panel usage tracking plus OS hard quota on the tenant Unix user."
        else:
            note = (
                "Panel soft usage tracking only — OS hard quota is not active on this host yet."
            )

        return {
            "environment_id": str(env.id),
            "domain": env.domain,
            "disk": disk,
            "components": components,
            "tier": tier,
            "thresholds": {"warn_pct": WARN_PCT, "high_pct": HIGH_PCT, "critical_pct": HARD_PCT},
            "os_quota": os_quota,
            "host": host_storage_pressure(self._settings),
            "storage_status": status,
            "message": disk.get("message"),
            "note": note,
        }

    def apply_quota_for_env(self, env: CustomerEnvironment) -> dict[str, Any]:
        return apply_os_user_quota(
            self._settings,
            username=env.unix_username,
            home=env.document_root,
            storage_limit_gb=env.storage_limit_gb,
        )
