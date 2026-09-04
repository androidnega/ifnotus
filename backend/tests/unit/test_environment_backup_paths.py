"""Environment backup path + archive size safety."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

from app.services.platform.backups import EnvironmentBackupService, _BACKUP_SKIP_DIR_NAMES


def test_backup_root_prefers_platform_absolute(tmp_path: Path, monkeypatch) -> None:
    settings = SimpleNamespace(operations_backup_dir=".ifnotus/backups")
    svc = EnvironmentBackupService(settings, session=None)  # type: ignore[arg-type]
    # Force package path resolution via monkeypatch on Path used in method — call as-is
    # and assert it returns an absolute path ending in .ifnotus/backups
    root = svc._backup_root()
    assert root.is_absolute()
    assert root.name == "backups"
    assert "ifnotus" in str(root).lower() or root.as_posix().endswith(".ifnotus/backups")


def test_backup_skip_dir_names_cover_common_bloat() -> None:
    assert "node_modules" in _BACKUP_SKIP_DIR_NAMES
    assert ".git" in _BACKUP_SKIP_DIR_NAMES
    assert ".venv" in _BACKUP_SKIP_DIR_NAMES


def test_archive_path_resolves_absolute(tmp_path: Path) -> None:
    settings = SimpleNamespace(operations_backup_dir=str(tmp_path / "bak"))
    svc = EnvironmentBackupService(settings, session=None)  # type: ignore[arg-type]
    customer_id = uuid4()
    dest = svc._backup_dir(customer_id)
    archive = dest / "site.tar.gz"
    archive.write_bytes(b"abc")
    row = SimpleNamespace(
        filename=str(archive),
        customer_id=customer_id,
        storage_key=None,
    )
    found = svc._archive_path(row)  # type: ignore[arg-type]
    assert found == archive.resolve()


def test_archive_path_resolves_basename(tmp_path: Path) -> None:
    settings = SimpleNamespace(operations_backup_dir=str(tmp_path / "bak"))
    svc = EnvironmentBackupService(settings, session=None)  # type: ignore[arg-type]
    customer_id = uuid4()
    dest = svc._backup_dir(customer_id)
    archive = dest / "legacy.tar.gz"
    archive.write_bytes(b"xyz")
    row = SimpleNamespace(
        filename="legacy.tar.gz",
        customer_id=customer_id,
        storage_key=None,
    )
    found = svc._archive_path(row)  # type: ignore[arg-type]
    assert found == archive.resolve()
