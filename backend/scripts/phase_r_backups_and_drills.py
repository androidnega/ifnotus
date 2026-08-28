#!/usr/bin/env python3
"""PHASE R — Backups & Restore Testing Verification Script.

Verifies:
1. Fast local backups + encrypted offsite mirroring (Restic, S3, Command).
2. Disaster Recovery Targets scope:
   - tenant files
   - product files
   - IFNOTUS DB
   - MySQL
   - PostgreSQL
   - mail
   - DNS
   - ISPConfig DB/config
   - nginx
   - critical /etc config
3. 5 Documented Restore Drills:
   - One tenant website restore
   - One tenant database restore
   - One mailbox restore
   - IFNOTUS DB restore
   - ISPConfig configuration restore
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace

# Add backend to path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.platform.backup_providers import (
    CommandOffsiteProvider,
    NullOffsiteProvider,
    ResticBackupProvider,
    S3CompatibleBackupProvider,
    resolve_backup_provider,
)
from app.services.platform.dr_backups import DisasterRecoveryService


def main() -> int:
    print("=" * 70)
    print("PHASE R — BACKUPS & RESTORE TESTING VERIFICATION")
    print("=" * 70)

    # 1. Backup Providers
    print("\n[1] Pluggable Offsite Backup Providers:")
    s_null = SimpleNamespace(backup_offsite_provider="none")
    assert isinstance(resolve_backup_provider(s_null), NullOffsiteProvider)  # type: ignore[arg-type]
    print("  ✓ Null / Local-only provider")

    s_cmd = SimpleNamespace(backup_offsite_provider="command", backup_offsite_cmd="echo put")
    assert isinstance(resolve_backup_provider(s_cmd), CommandOffsiteProvider)  # type: ignore[arg-type]
    print("  ✓ Command provider (rsync / rclone / script)")

    s_s3 = SimpleNamespace(backup_offsite_provider="s3", backup_s3_bucket="dr-backups")
    assert isinstance(resolve_backup_provider(s_s3), S3CompatibleBackupProvider)  # type: ignore[arg-type]
    print("  ✓ S3 / Object Storage provider")

    s_restic = SimpleNamespace(
        backup_offsite_provider="restic",
        backup_restic_repository="/srv/backups/restic",
        backup_restic_password="secret_password",
    )
    p_restic = resolve_backup_provider(s_restic)  # type: ignore[arg-type]
    assert isinstance(p_restic, ResticBackupProvider)
    assert p_restic.configured() is True
    print("  ✓ Restic Encrypted Offsite provider (repository & password configured)")

    # 2. Disaster Recovery Scope
    print("\n[2] Disaster Recovery Targets Scope:")
    svc = DisasterRecoveryService(s_restic)  # type: ignore[arg-type]
    targets = svc.get_backup_targets()
    for t in targets:
        print(f"  - [{t.category.upper()}] {t.name}: {t.description} ({t.path_or_source})")

    names = {t.name for t in targets}
    required = {
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
    assert required.issubset(names)
    print("  ✓ All 11 platform subsystems mapped in DR backup inventory")

    # 3. Documented Restore Drills
    print("\n[3] Executing 5 Documented Restore Drills:")
    drills = svc.run_all_drills()
    for d in drills:
        status_icon = "✓" if d.success else "✗"
        print(f"  {status_icon} [{d.drill_name}] {d.target}: {d.details} ({d.duration_ms:.1f}ms)")
        assert d.success, f"Drill {d.drill_name} failed!"

    print("\n" + "=" * 70)
    print("PHASE R VERIFICATION: PASS")
    print("=" * 70)
    return 0


if __name__ == "__main__":
    sys.exit(main())
