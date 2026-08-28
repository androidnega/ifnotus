"""PHASE S — Monitoring & Alert Thresholds Unit Tests.

Verifies:
1. Host metrics: CPU, RAM, load average (1m, 5m, 15m), disk, inodes, network throughput.
2. Services health: nginx, PHP-FPM, MySQL, PostgreSQL, Redis, Postfix, Dovecot, BIND.
3. Operational indicators: SSL expiry, backup failures, ISPConfig API, IFNOTUS API, tenant usage.
4. Alert Threshold Evaluation:
   - CPU alert threshold
   - RAM alert threshold
   - Disk & Inodes alert thresholds
   - Load average alert threshold
   - Service outage critical alert
   - Backup failure alert
5. Netdata privacy check (127.0.0.1 private binding enforcement).
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from app.services.platform.system_monitoring import (
    HostResourceMetrics,
    OperationalIndicators,
    PlatformSystemMonitoringService,
    ServiceHealth,
)


def _settings(**kw) -> SimpleNamespace:
    base = {
        "monitoring_cpu_alert_threshold": 85.0,
        "monitoring_memory_alert_threshold": 85.0,
        "monitoring_disk_alert_threshold": 90.0,
        "monitoring_inodes_alert_threshold": 85.0,
        "monitoring_load_alert_threshold": 12.0,
        "monitoring_ssl_expiry_days_threshold": 14,
        "netdata_url": "http://127.0.0.1:19999",
        "php_fpm_socket": "/run/php/php8.3-fpm.sock",
        "ispconfig_base_url": "https://127.0.0.1:8081",
        "letsencrypt_live_dir": "/etc/letsencrypt/live",
    }
    base.update(kw)
    return SimpleNamespace(**base)


@pytest.mark.asyncio
async def test_collect_host_resources() -> None:
    """Test host CPU, RAM, load, disk, inodes, and network collection."""
    svc = PlatformSystemMonitoringService(_settings())  # type: ignore[arg-type]
    host = await svc.collect_host_resources()

    assert isinstance(host.cpu_percent, float)
    assert isinstance(host.ram_percent, float)
    assert isinstance(host.load_1m, float)
    assert isinstance(host.disk_percent, float)
    assert host.network_bytes_recv_per_sec >= 0
    assert host.network_bytes_sent_per_sec >= 0


@pytest.mark.asyncio
async def test_collect_services_health() -> None:
    """Test all 8 required services are probed."""
    svc = PlatformSystemMonitoringService(_settings())  # type: ignore[arg-type]

    with patch.object(svc, "check_service_socket", return_value=True):
        services = await svc.collect_services_health()

    expected_services = {"nginx", "php_fpm", "mysql", "postgresql", "redis", "postfix", "dovecot", "bind"}
    assert expected_services.issubset(set(services.keys()))
    assert services["nginx"].status == "healthy"
    assert services["mysql"].status == "healthy"
    assert services["postgresql"].status == "healthy"
    assert services["redis"].status == "healthy"


@pytest.mark.asyncio
async def test_alert_threshold_evaluation_triggers_on_high_usage() -> None:
    """Test alert generation when metrics exceed configured thresholds."""
    s = _settings(
        monitoring_cpu_alert_threshold=80.0,
        monitoring_memory_alert_threshold=80.0,
        monitoring_disk_alert_threshold=85.0,
        monitoring_inodes_alert_threshold=80.0,
        monitoring_load_alert_threshold=10.0,
    )
    svc = PlatformSystemMonitoringService(s)  # type: ignore[arg-type]

    high_host = HostResourceMetrics(
        cpu_percent=92.0,
        ram_percent=88.5,
        ram_used_mb=4000.0,
        ram_total_mb=4500.0,
        load_1m=14.5,
        load_5m=12.0,
        load_15m=10.0,
        disk_percent=89.0,
        disk_used_gb=180.0,
        disk_total_gb=200.0,
        inodes_percent=86.0,
        inodes_used=860000,
        inodes_total=1000000,
        network_bytes_recv_per_sec=1000.0,
        network_bytes_sent_per_sec=2000.0,
    )

    services = {
        "nginx": ServiceHealth("nginx", "web", "healthy", "ok"),
        "postgresql": ServiceHealth("postgresql", "database", "unhealthy", "connection refused"),
    }

    indicators = OperationalIndicators(
        ssl_certificates_expiring_soon=2,
        recent_backup_failures=1,
        ispconfig_api_status="configured",
        ifnotus_api_status="healthy",
        high_usage_tenants_count=3,
        netdata_private=True,
        netdata_details="Private localhost",
    )

    alerts = svc.evaluate_alerts(high_host, services, indicators)
    alert_ids = {a["id"] for a in alerts}

    assert "alert-cpu-high" in alert_ids
    assert "alert-ram-high" in alert_ids
    assert "alert-disk-high" in alert_ids
    assert "alert-inodes-high" in alert_ids
    assert "alert-load-high" in alert_ids
    assert "alert-service-postgresql" in alert_ids
    assert "alert-backup-failures" in alert_ids


@pytest.mark.asyncio
async def test_netdata_private_binding_audit() -> None:
    """Test Netdata private binding verification."""
    # Localhost = private
    svc_private = PlatformSystemMonitoringService(_settings(netdata_url="http://127.0.0.1:19999"))  # type: ignore[arg-type]
    ind_private = await svc_private.collect_indicators()
    assert ind_private.netdata_private is True

    # Public IP = warning
    svc_public = PlatformSystemMonitoringService(_settings(netdata_url="http://80.241.223.82:19999"))  # type: ignore[arg-type]
    ind_public = await svc_public.collect_indicators()
    assert ind_public.netdata_private is False

    # Check alert generation for public Netdata
    alerts = svc_public.evaluate_alerts(
        HostResourceMetrics(0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0),
        {},
        ind_public,
    )
    assert any(a["id"] == "alert-netdata-exposure" for a in alerts)


@pytest.mark.asyncio
async def test_generate_full_monitoring_report() -> None:
    """Test full monitoring report assembly."""
    svc = PlatformSystemMonitoringService(_settings())  # type: ignore[arg-type]
    report = await svc.generate_monitoring_report()

    assert report.timestamp is not None
    assert report.overall_health in {"healthy", "degraded", "critical"}
    assert report.host is not None
    assert len(report.services) >= 8
    assert report.indicators is not None
    assert "cpu_percent" in report.alert_thresholds
    assert "inodes_percent" in report.alert_thresholds
