"""Per-environment resource monitoring for customer hosting panel (PHASE 29)."""

from __future__ import annotations

import asyncio
import re
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.logging import get_logger
from app.models.platform import ApplicationInstance, CustomerEnvironment, EnvironmentBackup, HostingPlan
from app.services.platform.environment_databases import EnvironmentDatabaseService
from app.services.platform.environment_mail import entitlements_for_plan
from app.services.platform.plan_matrix import YES, feature_level
from app.services.platform.usage import measure_path_usage, usage_snapshot

logger = get_logger(__name__)

_POOL_NAME = re.compile(r"[^a-z0-9]+")


def _php_pool_name(hostname: str | None) -> str | None:
    if not hostname:
        return None
    safe = _POOL_NAME.sub("-", hostname.lower()).strip("-")[:40] or "site"
    return f"ifnotus-{safe}"


def _user_process_stats(username: str | None) -> dict[str, Any]:
    """Best-effort CPU/memory/process count for a unix account (compat wrapper)."""
    return environment_live_stats(unix_username=username)


def environment_live_stats(
    *,
    unix_username: str | None = None,
    unix_uid: int | None = None,
    document_root: str | None = None,
    domain: str | None = None,
    sample_seconds: float = 0.2,
) -> dict[str, Any]:
    """Live CPU/RAM/process sample for one tenant environment.

    Attributes work even when PHP-FPM pools run as www-data: workers are matched by
    ``php-fpm: pool <name>`` cmdline, and app processes by cwd under the site root.
    """
    empty = {"process_count": 0, "memory_rss_mb": 0.0, "cpu_percent": 0.0, "available": False, "source": None}
    try:
        import psutil
    except ImportError:
        return empty

    root = ""
    try:
        if document_root:
            root = str(Path(document_root).resolve())
    except OSError:
        root = str(document_root or "").rstrip("/")

    pool = _php_pool_name(domain)
    pool_markers = {f"pool {pool}", f"[{pool}]"} if pool else set()
    uid = int(unix_uid) if unix_uid is not None else None
    user = (unix_username or "").strip() or None

    def _matches(proc: Any) -> bool:
        try:
            uids = proc.uids()
            if uid is not None and int(uids.real) == uid:
                return True
        except (psutil.Error, AttributeError, TypeError, ValueError):
            pass
        try:
            if user and proc.username() == user:
                return True
        except (psutil.Error, AttributeError, KeyError):
            pass
        try:
            cmd = " ".join(proc.cmdline() or [])
        except (psutil.Error, AttributeError):
            cmd = ""
        if pool and any(marker in cmd for marker in pool_markers):
            return True
        if pool and f"php-fpm: pool {pool}" in cmd:
            return True
        if root:
            try:
                cwd = proc.cwd()
            except (psutil.Error, AttributeError):
                cwd = ""
            if cwd and (cwd == root or cwd.startswith(root + "/")):
                # Skip unrelated system daemons that happen to sit under the tree.
                name = (proc.name() or "").lower()
                if name in {"bash", "sh", "sshd", "systemd"}:
                    return False
                return True
        return False

    matched: list[Any] = []
    for proc in psutil.process_iter(["pid"]):
        try:
            if _matches(proc):
                # Prime cpu counters (first cpu_percent call is usually 0).
                try:
                    proc.cpu_percent(interval=None)
                except (psutil.Error, AttributeError):
                    pass
                matched.append(proc)
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            continue

    if sample_seconds > 0:
        time.sleep(min(1.0, max(0.05, float(sample_seconds))))

    rss = 0
    cpu = 0.0
    alive = 0
    for proc in matched:
        try:
            mem = proc.memory_info()
            rss += int(getattr(mem, "rss", 0) or 0)
            cpu += float(proc.cpu_percent(interval=None) or 0.0)
            alive += 1
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            continue

    source = "psutil"
    if pool and any(True for _ in matched):
        source = "psutil+pool"
    return {
        "process_count": alive,
        "memory_rss_mb": round(rss / (1024 * 1024), 1),
        "cpu_percent": round(min(cpu, 999.0), 1),
        "available": True,
        "source": source,
        "pool": pool,
    }


def _ssl_summary(env: CustomerEnvironment) -> dict[str, Any]:
    expiry = env.ssl_expiry
    if expiry is None:
        return {"status": "unknown", "expires_at": None, "days_remaining": None}
    now = datetime.now(UTC)
    exp = expiry if expiry.tzinfo else expiry.replace(tzinfo=UTC)
    days = (exp - now).days
    if days < 0:
        status = "expired"
    elif days <= 14:
        status = "expiring"
    elif days <= 60:
        status = "ok"
    else:
        status = "ok"
    return {
        "status": status,
        "expires_at": exp.isoformat(),
        "days_remaining": days,
    }


class EnvironmentMonitoringService:
    def __init__(self, settings: Settings, session: AsyncSession) -> None:
        self._settings = settings
        self._session = session

    async def snapshot(
        self,
        env: CustomerEnvironment,
        plan: HostingPlan | None,
        *,
        full: bool,
    ) -> dict[str, Any]:
        disk = usage_snapshot(env.document_root, env.storage_limit_gb)
        ram_limit_mb = float(env.ram_limit_gb or 0) * 1024

        backup_count = int(
            (
                await self._session.execute(
                    select(func.count())
                    .select_from(EnvironmentBackup)
                    .where(
                        EnvironmentBackup.environment_id == env.id,
                        EnvironmentBackup.status == "success",
                    )
                )
            ).scalar_one()
            or 0
        )

        app_count = int(
            (
                await self._session.execute(
                    select(func.count())
                    .select_from(ApplicationInstance)
                    .where(ApplicationInstance.environment_id == env.id)
                )
            ).scalar_one()
            or 0
        )

        active_apps = int(
            (
                await self._session.execute(
                    select(func.count())
                    .select_from(ApplicationInstance)
                    .where(
                        ApplicationInstance.environment_id == env.id,
                        ApplicationInstance.status.in_(["running", "active", "deployed"]),
                    )
                )
            ).scalar_one()
            or 0
        )

        mail_ent = entitlements_for_plan(plan)
        mail_used_mb = None
        if mail_ent.enabled and env.domain:
            vmail_root = getattr(self._settings, "mail_vmail_dir", "/var/vmail")
            used_bytes, _ = await asyncio.to_thread(
                measure_path_usage, f"{vmail_root}/{env.domain}"
            )
            mail_used_mb = round(used_bytes / (1024 * 1024), 1)

        payload: dict[str, Any] = {
            "environment_id": str(env.id),
            "domain": env.domain,
            "level": "full" if full else "limited",
            "checked_at": datetime.now(UTC).isoformat(),
            "disk": {
                "used_bytes": int(disk["storage_used_bytes"]),
                "used_gb": float(disk["storage_used_gb"]),
                "limit_gb": int(disk["storage_limit_gb"]),
                "pct": float(disk["storage_pct"]),
                "file_count": int(disk["file_count"]),
                "status": str(disk["storage_status"]),
            },
            "health_status": env.health_status or "unknown",
            "site_status": env.status,
            "ssl": _ssl_summary(env),
            "backups": {"success_count": backup_count},
            "applications": {"total": app_count, "active": active_apps},
        }

        if mail_ent.enabled:
            payload["mail"] = {
                "enabled": True,
                "used_mb": mail_used_mb,
                "limit_mb": mail_ent.storage_mb,
                "mailbox_limit": mail_ent.mailboxes,
            }
        else:
            payload["mail"] = {"enabled": False}

        if not full:
            # Still attach lightweight live samples on limited plans (usage bars).
            live: dict[str, Any] = {}
            try:
                from app.services.platform.systemd_env_slice import EnvironmentSliceService

                live = await asyncio.to_thread(EnvironmentSliceService().read_usage, env)
            except Exception:  # noqa: BLE001
                live = await asyncio.to_thread(
                    environment_live_stats,
                    unix_username=env.unix_username,
                    unix_uid=getattr(env, "unix_uid", None),
                    document_root=env.document_root,
                    domain=env.domain,
                )
                if live.get("available"):
                    live = {
                        "available": True,
                        "source": live.get("source") or "psutil",
                        "memory_mb": float(live.get("memory_rss_mb") or 0),
                        "cpu_percent": float(live.get("cpu_percent") or 0),
                        "process_count": int(live.get("process_count") or 0),
                    }
            if live.get("available"):
                mem_mb = float(live.get("memory_mb") or 0)
                payload["processes"] = {
                    "count": int(live.get("process_count") or 0),
                    "available": True,
                }
                payload["memory"] = {
                    "rss_mb": mem_mb,
                    "limit_mb": round(ram_limit_mb, 1),
                    "pct": round((mem_mb / ram_limit_mb) * 100, 1) if ram_limit_mb else 0.0,
                }
                payload["cpu"] = {
                    "percent": float(live.get("cpu_percent") or 0),
                    "limit_vcpu": float(env.cpu_limit or 0),
                }
                payload["metrics_source"] = live.get("source")
            payload["note"] = (
                "Limited monitoring on this plan — disk, health, SSL, backups, and basic live samples. "
                "Upgrade for richer process/database detail."
            )
            return payload

        # Prefer cgroup slice samples when present; always fall back to process attribution.
        try:
            from app.services.platform.systemd_env_slice import EnvironmentSliceService

            live = await asyncio.to_thread(EnvironmentSliceService().read_usage, env)
        except Exception:  # noqa: BLE001
            live = {}
        proc = await asyncio.to_thread(
            environment_live_stats,
            unix_username=env.unix_username,
            unix_uid=getattr(env, "unix_uid", None),
            document_root=env.document_root,
            domain=env.domain,
        )
        if live.get("available"):
            mem_mb = float(live.get("memory_mb") if live.get("memory_mb") is not None else proc.get("memory_rss_mb") or 0)
            cpu_pct = float(live.get("cpu_percent") if live.get("cpu_percent") is not None else proc.get("cpu_percent") or 0)
            pcount = int(live.get("process_count") if live.get("process_count") is not None else proc.get("process_count") or 0)
            metrics_source = live.get("source") or "psutil"
        else:
            mem_mb = float(proc.get("memory_rss_mb") or 0)
            cpu_pct = float(proc.get("cpu_percent") or 0)
            pcount = int(proc.get("process_count") or 0)
            metrics_source = str(proc.get("source") or "psutil") if proc.get("available") else None

        db_rows = await EnvironmentDatabaseService(self._settings, self._session).list_databases(
            env, plan
        )
        db_total_mb = round(
            sum(float(r.size_mb or 0) for r in db_rows if r.size_mb is not None),
            2,
        )

        payload["processes"] = {
            "count": pcount,
            "available": bool(metrics_source),
        }
        payload["memory"] = {
            "rss_mb": mem_mb,
            "limit_mb": round(ram_limit_mb, 1),
            "pct": round((mem_mb / ram_limit_mb) * 100, 1) if ram_limit_mb else 0.0,
        }
        payload["cpu"] = {
            "percent": cpu_pct,
            "limit_vcpu": float(env.cpu_limit or 0),
        }
        payload["databases"] = {
            "count": len(db_rows),
            "total_size_mb": db_total_mb,
        }
        payload["metrics_source"] = metrics_source
        payload["note"] = (
            "Live metrics are sampled from your environment resource slice / hosting account on this server."
        )
        return payload

    @staticmethod
    def is_full_monitoring(plan: HostingPlan | None) -> bool:
        return feature_level(plan, "monitoring") == YES
