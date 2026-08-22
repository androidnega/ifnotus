"""PHASE 33 — staff shared-node capacity / hosting operations dashboard."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any

import psutil
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.logging import get_logger
from app.models.hosting import Mailbox
from app.models.platform import (
    ApplicationInstance,
    Customer,
    CustomerEnvironment,
    EnvironmentBackup,
    EnvironmentDatabase,
    PlatformJob,
    Subscription,
)
from app.services.platform.environment_storage import host_storage_pressure
from app.services.platform.resources import ResourceManager

logger = get_logger(__name__)


def _live_host_metrics() -> dict[str, Any]:
    """Actual host usage — not package-advertised sums."""
    try:
        vm = psutil.virtual_memory()
        disk = psutil.disk_usage("/")
        load = psutil.getloadavg() if hasattr(psutil, "getloadavg") else (0.0, 0.0, 0.0)
        boot = psutil.boot_time()
        uptime = max(0.0, datetime.now(UTC).timestamp() - boot)
        # Brief interval for non-zero CPU sample
        cpu = psutil.cpu_percent(interval=0.15)
        return {
            "cpu_percent": round(float(cpu), 1),
            "ram_percent": round(float(vm.percent), 1),
            "ram_used_gb": round(vm.used / (1024**3), 2),
            "ram_total_gb": round(vm.total / (1024**3), 2),
            "disk_percent": round(float(disk.percent), 1),
            "disk_used_gb": round(disk.used / (1024**3), 2),
            "disk_total_gb": round(disk.total / (1024**3), 2),
            "disk_free_gb": round(disk.free / (1024**3), 2),
            "load_average": [round(float(x), 2) for x in load],
            "uptime_seconds": round(uptime, 1),
            "process_count": len(psutil.pids()),
        }
    except Exception as exc:  # noqa: BLE001
        logger.warning("live_host_metrics_failed", error=str(exc))
        return {
            "cpu_percent": 0.0,
            "ram_percent": 0.0,
            "ram_used_gb": 0.0,
            "ram_total_gb": 0.0,
            "disk_percent": 0.0,
            "disk_used_gb": 0.0,
            "disk_total_gb": 0.0,
            "disk_free_gb": 0.0,
            "load_average": [0.0, 0.0, 0.0],
            "uptime_seconds": 0.0,
            "process_count": 0,
        }


class StaffCapacityService:
    def __init__(self, settings: Settings, session: AsyncSession) -> None:
        self._settings = settings
        self._session = session
        self._resources = ResourceManager(session)

    async def dashboard(self) -> dict[str, Any]:
        await self._resources.ensure_primary_node(self._settings)
        nodes = await self._resources.list_nodes()
        live = await asyncio.to_thread(_live_host_metrics)
        pressure = host_storage_pressure(self._settings)

        node_rows: list[dict[str, Any]] = []
        policy: dict[str, Any] | None = None
        for idx, node in enumerate(nodes):
            snap = await self._resources.snapshot(node, settings=self._settings)
            display = "Shared Node 01" if idx == 0 else f"Shared Node {idx + 1:02d}"
            cpu_reserve = max(1, int(snap.cpu_total * snap.cpu_reserved_pct / 100))
            ram_pct = int(getattr(self._settings, "infra_ram_reserved_pct", 20) or 20)
            storage_pct = int(getattr(self._settings, "infra_storage_reserved_pct", 15) or 15)
            ram_reserve = max(1, int(snap.ram_total_gb * ram_pct / 100))
            storage_reserve = max(1, int(snap.storage_total_gb * storage_pct / 100))

            row = {
                "node_id": snap.node_id,
                "hostname": snap.hostname or node.hostname,
                "display_name": display,
                "status": snap.status,
                "cpu_total": snap.cpu_total,
                "ram_total_gb": snap.ram_total_gb,
                "storage_total_gb": snap.storage_total_gb,
                "cpu_reserved_pct": snap.cpu_reserved_pct,
                "ram_reserved_pct": ram_pct,
                "storage_reserved_pct": storage_pct,
                # Committed = sum of environment plan allocations (not live RSS)
                "cpu_committed": snap.cpu_used,
                "ram_committed_gb": snap.ram_used,
                "storage_committed_gb": snap.storage_used,
                "cpu_available": snap.cpu_free,
                "ram_available_gb": snap.ram_free,
                "storage_available_gb": snap.storage_free,
                "cpu_reserve": cpu_reserve,
                "ram_reserve_gb": ram_reserve,
                "storage_reserve_gb": storage_reserve,
                # Legacy field names for older clients
                "cpu_used": snap.cpu_used,
                "ram_used": snap.ram_used,
                "storage_used": snap.storage_used,
                "cpu_free": snap.cpu_free,
                "ram_free": snap.ram_free,
                "storage_free": snap.storage_free,
            }
            node_rows.append(row)
            if policy is None:
                policy = {
                    "cpu": {
                        "total": snap.cpu_total,
                        "system_reserve": cpu_reserve,
                        "committed": snap.cpu_used,
                        "available": snap.cpu_free,
                        "actual_percent": live.get("cpu_percent"),
                    },
                    "ram": {
                        "total_gb": snap.ram_total_gb,
                        "system_reserve_gb": ram_reserve,
                        "committed_gb": snap.ram_used,
                        "available_gb": snap.ram_free,
                        "actual_used_gb": live.get("ram_used_gb"),
                        "actual_percent": live.get("ram_percent"),
                    },
                    "storage": {
                        "total_gb": snap.storage_total_gb,
                        "system_reserve_gb": storage_reserve,
                        "committed_gb": snap.storage_used,
                        "available_gb": snap.storage_free,
                        "actual_used_gb": live.get("disk_used_gb"),
                        "actual_free_gb": live.get("disk_free_gb"),
                        "actual_percent": live.get("disk_percent"),
                        "min_free_gb": int(getattr(self._settings, "infra_min_free_storage_gb", 20) or 20),
                    },
                    "note": (
                        "Available = allocatable after system reserve, minus committed plan "
                        "allocations. Actual usage is live host metrics — not package RAM sums."
                    ),
                }

        counts = await self._counts()
        ops = await self._ops()

        primary = node_rows[0] if node_rows else None
        return {
            "display_name": (primary or {}).get("display_name") or "Shared Node 01",
            "hostname": (primary or {}).get("hostname")
            or getattr(self._settings, "infra_hostname", "ifnotus-1"),
            "checked_at": datetime.now(UTC).isoformat(),
            "live": live,
            "policy": policy
            or {
                "cpu": {},
                "ram": {},
                "storage": {},
                "note": "No infrastructure node registered.",
            },
            "counts": counts,
            "ops": ops,
            "host_pressure": pressure,
            "nodes": node_rows,
            "selling_paused": bool(pressure.get("block_provisioning")),
        }

    async def _counts(self) -> dict[str, int]:
        customers = int(
            (await self._session.execute(select(func.count()).select_from(Customer))).scalar_one() or 0
        )
        environments = int(
            (
                await self._session.execute(
                    select(func.count())
                    .select_from(CustomerEnvironment)
                    .where(CustomerEnvironment.status.in_(["active", "provisioning", "suspended"]))
                )
            ).scalar_one()
            or 0
        )
        applications = int(
            (await self._session.execute(select(func.count()).select_from(ApplicationInstance))).scalar_one()
            or 0
        )
        databases = int(
            (await self._session.execute(select(func.count()).select_from(EnvironmentDatabase))).scalar_one()
            or 0
        )
        # Legacy primary DB on env without registry row
        legacy_db = int(
            (
                await self._session.execute(
                    select(func.count())
                    .select_from(CustomerEnvironment)
                    .where(
                        CustomerEnvironment.db_name.isnot(None),
                        CustomerEnvironment.status.in_(["active", "provisioning", "suspended"]),
                    )
                )
            ).scalar_one()
            or 0
        )
        mailboxes = int(
            (await self._session.execute(select(func.count()).select_from(Mailbox))).scalar_one() or 0
        )
        return {
            "customers": customers,
            "environments": environments,
            "applications": applications,
            "databases": databases + legacy_db,
            "mailboxes": mailboxes,
        }

    async def _ops(self) -> dict[str, int]:
        provisioning = int(
            (
                await self._session.execute(
                    select(func.count())
                    .select_from(PlatformJob)
                    .where(
                        PlatformJob.job_type.in_(
                            ["provision_environment", "configure_dns", "issue_ssl", "deploy_stack"]
                        ),
                        PlatformJob.status.in_(["pending", "queued", "running"]),
                    )
                )
            ).scalar_one()
            or 0
        )
        failed_provisioning = int(
            (
                await self._session.execute(
                    select(func.count())
                    .select_from(PlatformJob)
                    .where(
                        PlatformJob.job_type == "provision_environment",
                        PlatformJob.status == "failed",
                        PlatformJob.created_at >= datetime.now(UTC) - timedelta(days=7),
                    )
                )
            ).scalar_one()
            or 0
        )
        ssl_problems = int(
            (
                await self._session.execute(
                    select(func.count())
                    .select_from(CustomerEnvironment)
                    .where(
                        CustomerEnvironment.status == "active",
                        CustomerEnvironment.ssl_expiry.isnot(None),
                        CustomerEnvironment.ssl_expiry <= datetime.now(UTC) + timedelta(days=14),
                    )
                )
            ).scalar_one()
            or 0
        )
        # Also count missing SSL on active sites with domains
        ssl_missing = int(
            (
                await self._session.execute(
                    select(func.count())
                    .select_from(CustomerEnvironment)
                    .where(
                        CustomerEnvironment.status == "active",
                        CustomerEnvironment.domain.isnot(None),
                        CustomerEnvironment.ssl_expiry.is_(None),
                    )
                )
            ).scalar_one()
            or 0
        )
        backup_problems = int(
            (
                await self._session.execute(
                    select(func.count())
                    .select_from(EnvironmentBackup)
                    .where(
                        EnvironmentBackup.status.in_(["failed", "error"]),
                        EnvironmentBackup.created_at >= datetime.now(UTC) - timedelta(days=7),
                    )
                )
            ).scalar_one()
            or 0
        )
        suspended = int(
            (
                await self._session.execute(
                    select(func.count())
                    .select_from(CustomerEnvironment)
                    .where(CustomerEnvironment.status == "suspended")
                )
            ).scalar_one()
            or 0
        )
        suspended_subs = int(
            (
                await self._session.execute(
                    select(func.count())
                    .select_from(Subscription)
                    .where(Subscription.status == "suspended")
                )
            ).scalar_one()
            or 0
        )
        # Disk alerts ≈ envs over soft warning — sampled via storage_status is not stored;
        # use host pressure level as the host disk alert flag (0/1) plus count of near-full envs
        # by comparing storage_limit when we have a cheap signal: health unhealthy from disk abuse
        disk_alerts = 1 if str(host_storage_pressure(self._settings).get("level")) != "ok" else 0

        return {
            "provisioning_jobs": provisioning,
            "failed_provisioning": failed_provisioning,
            "ssl_problems": ssl_problems + ssl_missing,
            "backup_problems": backup_problems,
            "disk_alerts": disk_alerts,
            "suspended_accounts": max(suspended, suspended_subs),
        }
