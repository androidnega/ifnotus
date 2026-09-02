"""Unit tests for Phase J resource status model."""

from __future__ import annotations

from types import SimpleNamespace

from app.services.platform.resource_status import STATUS_LABELS, build_resource_statuses


def _settings(**kw):
    return SimpleNamespace(os_user_quota_enabled=True, customer_environments_root="/var/www", **kw)


def test_disk_enforced_when_os_quota_hard() -> None:
    env = SimpleNamespace(
        id="00000000-0000-0000-0000-000000000001",
        provider="legacy",
        storage_limit_gb=5,
        cpu_limit=0.2,
        ram_limit_gb=0.25,
        provider_meta={},
    )
    out = build_resource_statuses(
        env=env,
        plan=None,
        settings=_settings(),
        disk={"storage_used_bytes": 100, "storage_pct": 1.0},
        os_quota={"hard_enforced": True, "applied": True, "message": "OS user hard quota applied"},
        live={"available": True, "memory_mb": 10, "process_count": 2},
        slice_applied={"applied": True, "slice": "ifnotus-env-abc.slice", "tasks_max": 40},
    )
    assert out["disk"]["status"] == "enforced"
    assert out["disk"]["label"] == STATUS_LABELS["enforced"]
    assert out["cpu"]["enforced"] is True
    assert out["memory"]["enforced"] is True
    # No plan bandwidth → treated as UNLIMITED / monitored
    assert out["bandwidth"]["status"] == "monitored"
    assert out["bandwidth"]["enforced"] is False
    assert out["resources_enforced"] is True


def test_disk_reported_only_without_os_quota() -> None:
    env = SimpleNamespace(
        id="00000000-0000-0000-0000-000000000002",
        provider="legacy",
        storage_limit_gb=10,
        cpu_limit=1,
        ram_limit_gb=1,
        provider_meta={},
    )
    out = build_resource_statuses(
        env=env,
        plan=SimpleNamespace(bandwidth_tb=1.0),
        settings=_settings(),
        disk={"storage_used_bytes": 0, "storage_pct": 0},
        os_quota={"hard_enforced": False, "soft_tracking_only": True},
        live={"available": False},
        slice_applied={"skipped": "systemd_unavailable"},
        prlimit_available=True,
    )
    # storage_gb > 0 ⇒ panel-level disk enforcement flag in status model
    assert out["disk"]["enforced"] is True
    assert out["cpu"]["status"] == "allocated"
    assert out["processes"]["enforced"] is True  # prlimit fallback
    assert out["bandwidth"]["enforced"] is True
    assert out["bandwidth"]["status"] == "enforced"
    assert out["resources_enforced"] is True


def test_unlimited_bandwidth_never_enforced() -> None:
    env = SimpleNamespace(
        id="00000000-0000-0000-0000-000000000099",
        provider="legacy",
        storage_limit_gb=1,
        cpu_limit=0.2,
        ram_limit_gb=0.25,
        provider_meta={},
    )
    out = build_resource_statuses(
        env=env,
        plan=SimpleNamespace(bandwidth_tb=0),
        settings=_settings(),
        disk={},
        os_quota={"hard_enforced": True},
        live={"available": True},
        slice_applied={"applied": True, "slice": "x"},
    )
    assert out["bandwidth"]["enforced"] is False
    assert out["bandwidth"]["status"] == "monitored"


def test_ispconfig_disk_enforced_flag() -> None:
    env = SimpleNamespace(
        id="00000000-0000-0000-0000-000000000003",
        provider="ispconfig",
        storage_limit_gb=2,
        cpu_limit=0.5,
        ram_limit_gb=0.5,
        provider_meta={"quota_enforced": True},
    )
    out = build_resource_statuses(
        env=env,
        plan=None,
        settings=_settings(),
        disk={"storage_pct": 5},
        os_quota={},
        live={"available": True},
        slice_applied={"applied": True, "slice": "ifnotus-env-x.slice"},
    )
    assert out["disk"]["enforced"] is True
    assert "ISPConfig" in (out["disk"].get("detail") or "")
