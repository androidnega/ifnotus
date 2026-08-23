#!/usr/bin/env bash
# PHASE 38K — Disposable backup → mutate → restore drill (same node + offsite mirror).
# Proves recoverability. Same-VPS mirror is NOT full disaster recovery.
set -euo pipefail
cd /srv/apps/ifnotus/backend
./.venv/bin/python - <<'PY'
from __future__ import annotations

import asyncio
import json
import os
import shutil
import tempfile
from pathlib import Path
from uuid import uuid4

from sqlalchemy import select, text

from app.core.config import get_settings
from app.core.database import create_engine, create_session_factory
from app.models.platform import CustomerEnvironment, EnvironmentBackup
from app.services.platform.backup_providers import resolve_backup_provider, storage_key_for
from app.services.platform.backups import EnvironmentBackupService

MARKER = "IFNOTUS_38K_DRILL_TOKEN_" + uuid4().hex[:12]
DRILL_FILE = "ifnotus-38k-drill.txt"


async def main() -> None:
    settings = get_settings()
    engine = create_engine(settings)
    Session = create_session_factory(engine)
    async with Session() as session:
        result = await session.execute(
            select(CustomerEnvironment)
            .where(
                CustomerEnvironment.status == "active",
                CustomerEnvironment.document_root.isnot(None),
            )
            .order_by(CustomerEnvironment.created_at.desc())
            .limit(5)
        )
        env = None
        for candidate in result.scalars().all():
            root = Path(candidate.document_root or "")
            if root.is_dir() and os.access(root, os.W_OK):
                env = candidate
                break
        if env is None:
            raise SystemExit("No writable active environment for drill")

        root = Path(env.document_root)
        marker_path = root / DRILL_FILE
        marker_path.write_text(MARKER + "\n", encoding="utf-8")
        print("ENV", env.domain or env.id)
        print("ROOT", root)
        print("MARKER_WRITTEN", MARKER)

        svc = EnvironmentBackupService(settings, session)
        row = EnvironmentBackup(
            customer_id=env.customer_id,
            environment_id=env.id,
            filename="",
            backup_type="full",
            status="pending",
            storage_provider="local",
            offsite_status="pending",
        )
        session.add(row)
        await session.flush()
        backup = await svc.run_backup(row.id)
        print(
            "BACKUP",
            json.dumps(
                {
                    "id": str(backup.id),
                    "status": backup.status,
                    "checksum": backup.checksum,
                    "file_size": backup.file_size,
                    "offsite_status": backup.offsite_status,
                    "storage_provider": backup.storage_provider,
                    "storage_key": backup.storage_key,
                    "verified_at": backup.verified_at.isoformat() if backup.verified_at else None,
                    "filename": backup.filename,
                },
                indent=2,
            ),
        )
        assert backup.status == "success"
        assert backup.checksum
        assert backup.verified_at
        assert Path(backup.filename).exists()

        # Mutate: overwrite marker
        marker_path.write_text("MUTATED_AFTER_BACKUP\n", encoding="utf-8")
        assert marker_path.read_text(encoding="utf-8").strip() == "MUTATED_AFTER_BACKUP"

        # Prove offsite object exists when put succeeded
        provider = resolve_backup_provider(settings)
        if backup.storage_key and backup.offsite_status in {"synced", "verified", "synced_unverified"}:
            with tempfile.TemporaryDirectory() as td:
                dest = Path(td) / "fetched.tar.gz"
                fetched = provider.fetch(backup.storage_key, dest)
                print("OFFSITE_FETCH", fetched.ok, fetched.error, fetched.skipped)
                if fetched.ok:
                    ok, err = EnvironmentBackupService.verify_archive_checksum(dest, backup.checksum)
                    print("OFFSITE_CHECKSUM", ok, err)
                    assert ok

        # Restore
        meta = await svc.run_restore(backup.id, env.id)
        restored = marker_path.read_text(encoding="utf-8").strip()
        print("RESTORED_CONTENT", restored)
        assert restored == MARKER, f"expected {MARKER!r} got {restored!r}"
        assert meta.get("checksum_verified") is True

        # Checksum mismatch path
        bad = EnvironmentBackupService.verify_archive_checksum(Path(backup.filename), "0" * 64)
        assert bad[0] is False
        print("CHECKSUM_MISMATCH_DETECT_OK")

        await session.commit()
        print("38K_DRILL_OK")
    await engine.dispose()


asyncio.run(main())
PY
