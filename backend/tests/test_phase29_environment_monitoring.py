"""PHASE 29 — per-environment monitoring snapshots."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from app.services.platform.environment_monitoring import EnvironmentMonitoringService


@pytest.mark.asyncio
async def test_limited_monitoring_omits_cpu_memory() -> None:
    env = MagicMock(
        id=uuid4(),
        domain="demo.example.com",
        document_root="/srv/sites/demo",
        storage_limit_gb=10,
        cpu_limit=Decimal("1"),
        ram_limit_gb=Decimal("2"),
        health_status="healthy",
        status="active",
        ssl_expiry=datetime.now(UTC) + timedelta(days=90),
        unix_username="u_demo",
    )
    plan = MagicMock()
    session = AsyncMock()
    session.execute = AsyncMock(
        side_effect=[
            MagicMock(scalar_one=MagicMock(return_value=2)),
            MagicMock(scalar_one=MagicMock(return_value=1)),
            MagicMock(scalar_one=MagicMock(return_value=1)),
        ]
    )

    settings = MagicMock(mail_vmail_dir="/var/vmail")
    svc = EnvironmentMonitoringService(settings, session)

    with patch(
        "app.services.platform.environment_monitoring.usage_snapshot",
        return_value={
            "storage_used_bytes": 1000,
            "storage_used_gb": 0.001,
            "storage_limit_gb": 10,
            "storage_pct": 0.1,
            "file_count": 5,
            "storage_status": "ok",
        },
    ):
        snap = await svc.snapshot(env, plan, full=False)

    assert snap["level"] == "limited"
    assert snap["disk"]["used_bytes"] == 1000
    assert "cpu" not in snap
    assert "memory" not in snap
    assert snap["backups"]["success_count"] == 2


@pytest.mark.asyncio
async def test_full_monitoring_includes_process_and_db_totals() -> None:
    env = MagicMock(
        id=uuid4(),
        domain="full.example.com",
        document_root="/srv/sites/full",
        storage_limit_gb=20,
        cpu_limit=Decimal("2"),
        ram_limit_gb=Decimal("4"),
        health_status="healthy",
        status="active",
        ssl_expiry=None,
        unix_username="u_full",
    )
    plan = MagicMock()
    session = AsyncMock()
    session.execute = AsyncMock(
        side_effect=[
            MagicMock(scalar_one=MagicMock(return_value=0)),
            MagicMock(scalar_one=MagicMock(return_value=0)),
            MagicMock(scalar_one=MagicMock(return_value=0)),
        ]
    )
    settings = MagicMock(mail_vmail_dir="/var/vmail")
    svc = EnvironmentMonitoringService(settings, session)

    db_row = MagicMock(size_mb=12.5)
    with (
        patch(
            "app.services.platform.environment_monitoring.usage_snapshot",
            return_value={
                "storage_used_bytes": 5000,
                "storage_used_gb": 0.005,
                "storage_limit_gb": 20,
                "storage_pct": 0.2,
                "file_count": 10,
                "storage_status": "ok",
            },
        ),
        patch(
            "app.services.platform.environment_monitoring.environment_live_stats",
            return_value={
                "process_count": 3,
                "memory_rss_mb": 128.0,
                "cpu_percent": 4.5,
                "available": True,
            },
        ),
        patch(
            "app.services.platform.environment_monitoring.EnvironmentDatabaseService"
        ) as db_svc_cls,
    ):
        db_svc_cls.return_value.list_databases = AsyncMock(return_value=[db_row])
        snap = await svc.snapshot(env, plan, full=True)

    assert snap["level"] == "full"
    assert snap["cpu"]["percent"] == 4.5
    assert snap["memory"]["rss_mb"] == 128.0
    assert snap["databases"]["total_size_mb"] == 12.5
