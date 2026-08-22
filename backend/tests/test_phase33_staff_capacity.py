"""PHASE 33 — staff capacity dashboard."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from app.services.platform.staff_capacity import StaffCapacityService, _live_host_metrics


def test_live_host_metrics_has_keys() -> None:
    m = _live_host_metrics()
    assert "cpu_percent" in m
    assert "ram_percent" in m
    assert "disk_percent" in m
    assert "load_average" in m
    assert "uptime_seconds" in m


@pytest.mark.asyncio
async def test_dashboard_separates_committed_from_actual() -> None:
    settings = MagicMock(
        infra_hostname="ifnotus-1",
        infra_ram_reserved_pct=20,
        infra_storage_reserved_pct=15,
        infra_min_free_storage_gb=20,
        customer_environments_root="/",
        host_disk_warn_pct=80,
        host_disk_high_pct=90,
        host_disk_crit_pct=95,
    )
    session = AsyncMock()
    # count queries
    session.execute = AsyncMock(
        side_effect=[
            MagicMock(scalar_one=MagicMock(return_value=n))
            for n in [3, 5, 2, 1, 1, 4]  # counts
        ]
        + [
            MagicMock(scalar_one=MagicMock(return_value=n))
            for n in [0, 0, 0, 0, 0, 0, 0]  # ops
        ]
    )

    node = MagicMock(id=uuid4(), hostname="ifnotus-1", status="healthy")
    snap = SimpleNamespace(
        node_id=str(node.id),
        hostname="ifnotus-1",
        status="healthy",
        cpu_total=12,
        ram_total_gb=48,
        storage_total_gb=256,
        cpu_reserved_pct=20,
        cpu_used=2.5,
        ram_used=8.0,
        storage_used=40,
        cpu_free=7.1,
        ram_free=30.4,
        storage_free=177,
    )

    svc = StaffCapacityService(settings, session)
    with (
        patch.object(svc._resources, "ensure_primary_node", new=AsyncMock(return_value=node)),
        patch.object(svc._resources, "list_nodes", new=AsyncMock(return_value=[node])),
        patch.object(svc._resources, "snapshot", new=AsyncMock(return_value=snap)),
        patch(
            "app.services.platform.staff_capacity._live_host_metrics",
            return_value={
                "cpu_percent": 12.0,
                "ram_percent": 35.0,
                "ram_used_gb": 16.0,
                "ram_total_gb": 48.0,
                "disk_percent": 40.0,
                "disk_used_gb": 100.0,
                "disk_total_gb": 250.0,
                "disk_free_gb": 150.0,
                "load_average": [0.5, 0.4, 0.3],
                "uptime_seconds": 1000.0,
                "process_count": 200,
            },
        ),
        patch(
            "app.services.platform.staff_capacity.host_storage_pressure",
            return_value={"level": "ok", "used_pct": 40, "free_gb": 150, "block_provisioning": False},
        ),
    ):
        # Re-mock counts/ops methods to avoid brittle execute chain
        svc._counts = AsyncMock(
            return_value={
                "customers": 3,
                "environments": 5,
                "applications": 2,
                "databases": 2,
                "mailboxes": 4,
            }
        )
        svc._ops = AsyncMock(
            return_value={
                "provisioning_jobs": 0,
                "failed_provisioning": 1,
                "ssl_problems": 2,
                "backup_problems": 0,
                "disk_alerts": 0,
                "suspended_accounts": 1,
            }
        )
        data = await svc.dashboard()

    assert data["display_name"] == "Shared Node 01"
    assert data["counts"]["customers"] == 3
    assert data["ops"]["failed_provisioning"] == 1
    # Committed ≠ actual: policy committed RAM is plan sum; live is separate
    assert data["policy"]["ram"]["committed_gb"] == 8.0
    assert data["policy"]["ram"]["actual_used_gb"] == 16.0
    assert data["live"]["cpu_percent"] == 12.0
