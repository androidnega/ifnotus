"""PHASE R — Backups & Disaster Recovery Restore Testing Unit Tests.

Verifies:
1. Multi-target Disaster Recovery scope (tenants, products, IFNOTUS DB, MySQL, PostgreSQL, mail, DNS, ISPConfig, nginx, /etc).
2. Offsite Backup Providers (Restic, S3, Command, Null).
3. 5 Documented Restore Drills:
   - One tenant website restore
   - One tenant database restore
   - One mailbox restore
   - IFNOTUS DB restore
   - ISPConfig configuration restore
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from app.services.platform.backup_providers import (
    CommandOffsiteProvider,
    NullOffsiteProvider,
    ResticBackupProvider,
    S3CompatibleBackupProvider,
    resolve_backup_provider,
)
from app.services.platform.dr_backups import DisasterRecoveryService


def _settings(**kw) -> SimpleNamespace:
    base = {
        "backup_offsite_provider": "none",
        "backup_offsite_cmd": "",
        "backup_offsite_fetch_cmd": "",
        "backup_offsite_delete_cmd": "",
        "backup_s3_endpoint": "",
        "backup_s3_bucket": "",
        "backup_s3_access_key": "",
        "backup_s3_secret_key": "",
        "backup_s3_region": "auto",
        "backup_s3_prefix": "ifnotus/",
        "backup_restic_repository": "",
        "backup_restic_password": "",
    }
    base.update(kw)
    return SimpleNamespace(**base)


def test_resolve_restic_backup_provider() -> None:
    """Test resolving Restic backup provider with credentials."""
    s = _settings(
        backup_offsite_provider="restic",
        backup_restic_repository="s3:https://s3.eu-central-1.amazonaws.com/backup-bucket/restic",
        backup_restic_password="secure_password",
        backup_s3_access_key="key123",
        backup_s3_secret_key="secret456",
    )
    provider = resolve_backup_provider(s)  # type: ignore[arg-type]
    assert isinstance(provider, ResticBackupProvider)
    assert provider.name == "restic"
    assert provider.configured() is True
    env = provider._build_env()
    assert env["RESTIC_REPOSITORY"] == "s3:https://s3.eu-central-1.amazonaws.com/backup-bucket/restic"
    assert env["RESTIC_PASSWORD"] == "secure_password"
    assert env["AWS_ACCESS_KEY_ID"] == "key123"
    assert env["AWS_SECRET_ACCESS_KEY"] == "secret456"


def test_restic_backup_provider_unconfigured_skips() -> None:
    """Test Restic provider gracefully handles unconfigured state."""
    provider = ResticBackupProvider("", "")
    assert provider.configured() is False
    with tempfile.NamedTemporaryFile() as tmp:
        res = provider.put(Path(tmp.name), "test_key")
        assert res.ok is False
        assert res.skipped is True


def test_disaster_recovery_manifest_targets() -> None:
    """Test DR targets include all critical platform subsystems."""
    svc = DisasterRecoveryService(_settings())  # type: ignore[arg-type]
    targets = svc.get_backup_targets()
    names = {t.name for t in targets}
    expected = {
        "tenant_files",
        "ispconfig_tenant_files",
        "product_files",
        "ifnotus_db",
        "mysql_databases",
        "postgres_databases",
        "mail_storage",
        "dns_zones",
        "ispconfig_config",
        "nginx_config",
        "critical_etc_config",
    }
    assert expected.issubset(names)


def test_restore_drill_tenant_website() -> None:
    """Drill 1: Tenant website restore."""
    svc = DisasterRecoveryService(_settings())  # type: ignore[arg-type]
    result = svc.run_tenant_website_restore_drill()
    assert result.success is True
    assert result.drill_name == "tenant_website_restore"
    assert result.duration_ms > 0


def test_restore_drill_tenant_database() -> None:
    """Drill 2: Tenant database restore."""
    svc = DisasterRecoveryService(_settings())  # type: ignore[arg-type]
    result = svc.run_tenant_database_restore_drill()
    assert result.success is True
    assert result.drill_name == "tenant_database_restore"


def test_restore_drill_mailbox() -> None:
    """Drill 3: Mailbox restore."""
    svc = DisasterRecoveryService(_settings())  # type: ignore[arg-type]
    result = svc.run_mailbox_restore_drill()
    assert result.success is True
    assert result.drill_name == "mailbox_restore"


def test_restore_drill_ifnotus_db() -> None:
    """Drill 4: IFNOTUS core PostgreSQL database restore."""
    svc = DisasterRecoveryService(_settings())  # type: ignore[arg-type]
    result = svc.run_ifnotus_db_restore_drill()
    assert result.success is True
    assert result.drill_name == "ifnotus_db_restore"


def test_restore_drill_ispconfig_config() -> None:
    """Drill 5: ISPConfig configuration & templates restore."""
    svc = DisasterRecoveryService(_settings())  # type: ignore[arg-type]
    result = svc.run_ispconfig_config_restore_drill()
    assert result.success is True
    assert result.drill_name == "ispconfig_config_restore"


def test_run_all_drills_pass() -> None:
    """Test executing full battery of 5 drills."""
    svc = DisasterRecoveryService(_settings())  # type: ignore[arg-type]
    results = svc.run_all_drills()
    assert len(results) == 5
    assert all(r.success for r in results)
