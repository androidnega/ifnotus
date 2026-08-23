"""PHASE 38F — OS user quota capability and setquota builder."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

from app.services.platform.environment_storage import (
    apply_os_user_quota,
    build_setquota_argv,
    mount_supports_usrquota,
    os_quota_runtime_ready,
)


def test_build_setquota_argv_maps_gb_to_kb() -> None:
    argv = build_setquota_argv(username="ifn_abc", mount="/", storage_limit_gb=1, warn_pct=80)
    assert argv[:3] == ["setquota", "-u", "ifn_abc"]
    soft_kb, hard_kb = int(argv[3]), int(argv[4])
    assert hard_kb == 1 * 1024 * 1024
    assert soft_kb == int(hard_kb * 0.8)
    assert argv[-1] == "/"


def test_mount_supports_usrquota_tokens() -> None:
    with patch(
        "app.services.platform.environment_storage._mount_options",
        return_value="rw,relatime,usrquota",
    ):
        assert mount_supports_usrquota("/") is True
    with patch(
        "app.services.platform.environment_storage._mount_options",
        return_value="rw,relatime,discard",
    ):
        assert mount_supports_usrquota("/") is False


def test_apply_reports_soft_only_when_mount_not_ready(tmp_path: Path) -> None:
    settings = MagicMock(os_user_quota_enabled=True)
    with (
        patch("app.services.platform.environment_storage.quota_tools_present", return_value=True),
        patch(
            "app.services.platform.environment_storage._detect_mount",
            return_value=("/", "ext4"),
        ),
        patch(
            "app.services.platform.environment_storage.mount_supports_usrquota",
            return_value=False,
        ),
    ):
        result = apply_os_user_quota(
            settings,
            username="ifn_x",
            home=tmp_path,
            storage_limit_gb=2,
        )
    assert result["applied"] is False
    assert result["hard_enforced"] is False
    assert result["soft_tracking_only"] is True
    assert "usrquota" in result["message"]


def test_apply_success_sets_hard_enforced(tmp_path: Path) -> None:
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
        patch("app.services.platform.environment_storage.subprocess.run") as run,
    ):
        run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        result = apply_os_user_quota(
            settings,
            username="ifn_x",
            home=tmp_path,
            storage_limit_gb=2,
        )
    assert result["applied"] is True
    assert result["hard_enforced"] is True
    assert result["soft_tracking_only"] is False


def test_runtime_ready_respects_settings_off(tmp_path: Path) -> None:
    settings = MagicMock(
        os_user_quota_enabled=False,
        customer_environments_root=str(tmp_path),
    )
    with patch(
        "app.services.platform.environment_storage._detect_mount",
        return_value=("/", "ext4"),
    ):
        probe = os_quota_runtime_ready(settings, tmp_path)
    assert probe["ready"] is False
    assert probe["settings_enabled"] is False
