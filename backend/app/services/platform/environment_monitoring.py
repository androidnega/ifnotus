"""Per-environment resource monitoring for customer hosting panel (PHASE 29)."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
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


def _user_process_stats(username: str | None) -> dict[str, Any]:
    """Best-effort CPU/memory/process count for a unix account."""
    if not username:
        return {"process_count": 0, "memory_rss_mb": 0.0, "cpu_percent": 0.0, "available": False}
    try:
        import psutil
    except ImportError:
        return {"process_count": 0, "memory_rss_mb": 0.0, "cpu_percent": 0.0, "available": False}

    procs: list[Any] = []
    rss = 0
    cpu = 0.0
    for proc in psutil.process_iter(["username", "memory_info", "cpu_percent"]):
        try:
            info = proc.info
            if (info.get("username") or "") != username:
                continue
            procs.append(proc)
            mem = info.get("memory_info")
            if mem:
                rss += int(getattr(mem, "rss", 0) or 0)
            cpu += float(info.get("cpu_percent") or 0.0)
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            continue
    return {
        "process_count": len(procs),
        "memory_rss_mb": round(rss / (1024 * 1024), 1),
        "cpu_percent": round(min(cpu, 999.0), 1),
        "available": True,
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
            payload["note"] = (
                "Limited monitoring on this plan — disk, health, SSL, and backups. "
                "Upgrade for live CPU, memory, and process metrics."
            )
            return payload

        proc = await asyncio.to_thread(_user_process_stats, env.unix_username)
        db_rows = await EnvironmentDatabaseService(self._settings, self._session).list_databases(
            env, plan
        )
        db_total_mb = round(
            sum(float(r.size_mb or 0) for r in db_rows if r.size_mb is not None),
            2,
        )

        payload["processes"] = {
            "count": int(proc["process_count"]),
            "available": bool(proc["available"]),
        }
        payload["memory"] = {
            "rss_mb": float(proc["memory_rss_mb"]),
            "limit_mb": round(ram_limit_mb, 1),
            "pct": round((proc["memory_rss_mb"] / ram_limit_mb) * 100, 1) if ram_limit_mb else 0.0,
        }
        payload["cpu"] = {
            "percent": float(proc["cpu_percent"]),
            "limit_vcpu": float(env.cpu_limit or 0),
        }
        payload["databases"] = {
            "count": len(db_rows),
            "total_size_mb": db_total_mb,
        }
        payload["note"] = "Live metrics are sampled from your hosting account on this server."
        return payload

    @staticmethod
    def is_full_monitoring(plan: HostingPlan | None) -> bool:
        return feature_level(plan, "monitoring") == YES
