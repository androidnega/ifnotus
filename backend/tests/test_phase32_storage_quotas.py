"""PHASE 32 — real storage quotas."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from app.services.platform.environment_storage import (
    host_storage_pressure,
    should_block_provisioning,
    should_block_storage_upgrade,
)
from app.services.platform.usage import usage_snapshot


def test_usage_tiers_80_90_95(tmp_path) -> None:
    # 9 MB of 10 MB plan ≈ 90%
    f = tmp_path / "big.bin"
    f.write_bytes(b"x" * (9 * 1024 * 1024))
    # limit 0.01 GB = ~10.48 MB
    snap = usage_snapshot(tmp_path, 0.01)
    assert snap["storage_pct"] >= 80
    assert snap["storage_status"] in {"warning", "high", "critical", "over"}


def test_host_pressure_blocks_at_critical() -> None:
    settings = SimpleNamespace(
        customer_environments_root="/",
        host_disk_warn_pct=80,
        host_disk_high_pct=90,
        host_disk_crit_pct=95,
        infra_min_free_storage_gb=20,
    )
    with patch(
        "app.services.platform.environment_storage.shutil.disk_usage",
        return_value=SimpleNamespace(total=1000, used=960, free=40),
    ):
        # free_gb tiny → critical via min_free
        snap = host_storage_pressure(settings)  # type: ignore[arg-type]
    assert snap["level"] == "critical"
    assert should_block_provisioning(settings, pressure=snap) is True  # type: ignore[arg-type]


def test_storage_upgrade_blocked_when_high() -> None:
    settings = SimpleNamespace(
        customer_environments_root="/",
        host_disk_warn_pct=80,
        host_disk_high_pct=90,
        host_disk_crit_pct=95,
        infra_min_free_storage_gb=20,
    )
    pressure = {
        "level": "high",
        "block_provisioning": False,
        "block_storage_upgrades": True,
        "free_gb": 30,
        "min_free_gb": 20,
    }
    assert should_block_storage_upgrade(settings, extra_gb=5, pressure=pressure) is True  # type: ignore[arg-type]
    assert should_block_storage_upgrade(settings, extra_gb=0, pressure=pressure) is False  # type: ignore[arg-type]


def test_setquota_invoked_when_available(tmp_path) -> None:
    from app.services.platform.environment_storage import apply_os_user_quota

    settings = MagicMock(os_user_quota_enabled=True)
    with (
        patch("app.services.platform.environment_storage.quota_tools_present", return_value=True),
        patch(
            "app.services.platform.environment_storage._detect_mount",
            return_value=("/", "ext4"),
        ),
        patch(
            "app.services.platform.environment_storage.mount_supports_usrquota",
            return_value=True,
        ),
        patch(
            "app.services.platform.environment_storage.quotas_actively_on",
            return_value=True,
        ),
        patch("app.services.platform.environment_storage.subprocess.run") as run,
    ):
        run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        result = apply_os_user_quota(
            settings,
            username="u_demo",
            home=tmp_path,
            storage_limit_gb=5,
        )
    assert result["applied"] is True
    assert result["hard_enforced"] is True
    assert run.called
