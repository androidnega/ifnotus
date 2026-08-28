#!/usr/bin/env python3
"""PHASE S — Monitoring & Alert Thresholds Verification Script.

Verifies:
1. Host resource monitoring (CPU, RAM, load 1m/5m/15m, disk, inodes, network).
2. Service availability (nginx, PHP-FPM, MySQL, PostgreSQL, Redis, Postfix, Dovecot, BIND).
3. Operational indicators (SSL expiry, backup failures, ISPConfig API, IFNOTUS API, tenant usage).
4. Alert threshold enforcement and evaluation engine.
5. Netdata private localhost binding audit.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace

# Add backend to path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.platform.system_monitoring import (
    HostResourceMetrics,
    OperationalIndicators,
    PlatformSystemMonitoringService,
    ServiceHealth,
)


async def async_main() -> int:
    print("=" * 70)
    print("PHASE S — SYSTEM MONITORING & ALERT THRESHOLDS VERIFICATION")
    print("=" * 70)

    settings = SimpleNamespace(
        monitoring_cpu_alert_threshold=85.0,
        monitoring_memory_alert_threshold=85.0,
        monitoring_disk_alert_threshold=90.0,
        monitoring_inodes_alert_threshold=85.0,
        monitoring_load_alert_threshold=12.0,
        monitoring_ssl_expiry_days_threshold=14,
        netdata_url="http://127.0.0.1:19999",
        php_fpm_socket="/run/php/php8.3-fpm.sock",
        ispconfig_base_url="https://127.0.0.1:8081",
        letsencrypt_live_dir="/etc/letsencrypt/live",
    )

    svc = PlatformSystemMonitoringService(settings)  # type: ignore[arg-type]

    # 1. Host Resources
    print("\n[1] Host Resource Metrics:")
    host = await svc.collect_host_resources()
    print(f"  ✓ CPU: {host.cpu_percent}%")
    print(f"  ✓ RAM: {host.ram_percent}% ({host.ram_used_mb}MB / {host.ram_total_mb}MB)")
    print(f"  ✓ Load average: 1m={host.load_1m}, 5m={host.load_5m}, 15m={host.load_15m}")
    print(f"  ✓ Disk: {host.disk_percent}% ({host.disk_used_gb}GB / {host.disk_total_gb}GB)")
    if host.inodes_percent is not None:
        print(f"  ✓ Inodes: {host.inodes_percent}% ({host.inodes_used} / {host.inodes_total})")
    print(f"  ✓ Network: rx={host.network_bytes_recv_per_sec}B, tx={host.network_bytes_sent_per_sec}B")

    # 2. Managed Services Health
    print("\n[2] Managed Services Health Checks:")
    services = await svc.collect_services_health()
    for sname, sinfo in services.items():
        port_info = f" (port {sinfo.port})" if sinfo.port else ""
        print(f"  - [{sinfo.category.upper()}] {sinfo.name}{port_info}: {sinfo.status} — {sinfo.details}")

    required_services = {"nginx", "php_fpm", "mysql", "postgresql", "redis", "postfix", "dovecot", "bind"}
    assert required_services.issubset(set(services.keys()))
    print("  ✓ All 8 required core services integrated in health matrix")

    # 3. Operational Indicators
    print("\n[3] Operational Indicators & Netdata Privacy:")
    indicators = await svc.collect_indicators()
    print(f"  ✓ SSL certificates expiring soon: {indicators.ssl_certificates_expiring_soon}")
    print(f"  ✓ Recent backup failures: {indicators.recent_backup_failures}")
    print(f"  ✓ ISPConfig API status: {indicators.ispconfig_api_status}")
    print(f"  ✓ IFNOTUS API status: {indicators.ifnotus_api_status}")
    print(f"  ✓ Netdata private binding: {indicators.netdata_private} ({indicators.netdata_details})")
    assert indicators.netdata_private is True

    # 4. Alert Threshold Evaluation
    print("\n[4] Alert Threshold Evaluation Engine:")
    high_host = HostResourceMetrics(
        cpu_percent=91.0,
        ram_percent=89.0,
        ram_used_mb=3500.0,
        ram_total_mb=4000.0,
        load_1m=15.0,
        load_5m=12.0,
        load_15m=10.0,
        disk_percent=92.0,
        disk_used_gb=184.0,
        disk_total_gb=200.0,
        inodes_percent=88.0,
        inodes_used=880000,
        inodes_total=1000000,
        network_bytes_recv_per_sec=1000.0,
        network_bytes_sent_per_sec=2000.0,
    )

    test_services = {
        "postgresql": ServiceHealth("postgresql", "database", "unhealthy", "Connection refused"),
    }
    test_indicators = OperationalIndicators(
        ssl_certificates_expiring_soon=3,
        recent_backup_failures=2,
        ispconfig_api_status="configured",
        ifnotus_api_status="healthy",
        high_usage_tenants_count=1,
        netdata_private=True,
        netdata_details="Private localhost",
    )

    alerts = svc.evaluate_alerts(high_host, test_services, test_indicators)
    alert_ids = {a["id"] for a in alerts}
    print(f"  ✓ Generated {len(alerts)} alerts against breached thresholds:")
    for a in alerts:
        print(f"    * [{a.get('severity', '').upper()}] {a.get('title')}: {a.get('value')}")

    assert "alert-cpu-high" in alert_ids
    assert "alert-ram-high" in alert_ids
    assert "alert-disk-high" in alert_ids
    assert "alert-inodes-high" in alert_ids
    assert "alert-load-high" in alert_ids
    assert "alert-service-postgresql" in alert_ids
    assert "alert-backup-failures" in alert_ids

    # 5. Full Monitoring Report
    print("\n[5] End-to-End Monitoring Report Assembly:")
    report = await svc.generate_monitoring_report()
    print(f"  ✓ Overall health: {report.overall_health.upper()}")
    print(f"  ✓ Thresholds defined: {list(report.alert_thresholds.keys())}")

    print("\n" + "=" * 70)
    print("PHASE S VERIFICATION: PASS")
    print("=" * 70)
    return 0


def main() -> int:
    return asyncio.run(async_main())


if __name__ == "__main__":
    sys.exit(main())
