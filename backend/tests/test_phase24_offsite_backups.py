"""PHASE 24 — BackupProvider + plan backup language."""

from pathlib import Path

from app.services.platform.backup_providers import (
    CommandOffsiteProvider,
    NullOffsiteProvider,
    resolve_backup_provider,
    storage_key_for,
)
from app.services.platform.plan_matrix import MATRIX, features_for


class _Settings:
    def __init__(self, **kwargs):
        self.backup_offsite_provider = kwargs.get("backup_offsite_provider", "none")
        self.backup_offsite_cmd = kwargs.get("backup_offsite_cmd", "")
        self.platform_backup_offsite_cmd = kwargs.get("platform_backup_offsite_cmd", "")
        self.backup_s3_endpoint = kwargs.get("backup_s3_endpoint", "")
        self.backup_s3_bucket = kwargs.get("backup_s3_bucket", "")
        self.backup_s3_access_key = kwargs.get("backup_s3_access_key", "")
        self.backup_s3_secret_key = kwargs.get("backup_s3_secret_key", "")
        self.backup_s3_region = kwargs.get("backup_s3_region", "auto")
        self.backup_s3_prefix = kwargs.get("backup_s3_prefix", "ifnotus/")


def test_null_provider_when_unconfigured() -> None:
    p = resolve_backup_provider(_Settings())  # type: ignore[arg-type]
    assert isinstance(p, NullOffsiteProvider)
    result = p.put(Path("/tmp/x"), "k")
    assert result.skipped
    assert not result.ok


def test_command_provider_from_settings() -> None:
    p = resolve_backup_provider(
        _Settings(backup_offsite_provider="command", backup_offsite_cmd="echo {path} {key}")
    )  # type: ignore[arg-type]
    assert isinstance(p, CommandOffsiteProvider)
    assert p.configured()


def test_legacy_platform_cmd_used_as_fallback() -> None:
    p = resolve_backup_provider(
        _Settings(platform_backup_offsite_cmd="rsync -az {dir}/ remote:/bak/")
    )  # type: ignore[arg-type]
    assert isinstance(p, CommandOffsiteProvider)


def test_storage_key_layout() -> None:
    key = storage_key_for("cust", "env", "/srv/backups/env_abc.tar.gz")
    assert key == "customers/cust/env/env_abc.tar.gz"


def test_plan_matrix_exposes_backup_package_fields() -> None:
    # student-pro has auto_backups limited / yes depending on matrix — check any pack with retention
    feats = features_for(None)
    # features_for(None) returns empty-ish via missing plan — use MATRIX directly
    pro = MATRIX["student-pro"]
    assert "backup_enabled" in pro
    assert pro["backup_enabled"] is True
    assert pro["backup_frequency"] in {"daily", "manual"}
    assert pro.get("backup_retention") == pro.get("retention_days")
    assert "customer_restore" in pro


def test_starter_without_auto_backups_is_manual_frequency() -> None:
    starter = MATRIX["student-starter"]
    assert starter["auto_backups"] == "no"
    assert starter["backup_frequency"] == "manual"
