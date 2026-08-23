"""PHASE 38K — backup verification, offsite fetch, checksum gates."""

from __future__ import annotations

import hashlib
from pathlib import Path

from app.services.platform.backup_providers import (
    CommandOffsiteProvider,
    NullOffsiteProvider,
    resolve_backup_provider,
)
from app.services.platform.backups import EnvironmentBackupService


class _Settings:
    def __init__(self, **kwargs):
        self.backup_offsite_provider = kwargs.get("backup_offsite_provider", "none")
        self.backup_offsite_cmd = kwargs.get("backup_offsite_cmd", "")
        self.backup_offsite_fetch_cmd = kwargs.get("backup_offsite_fetch_cmd", "")
        self.backup_offsite_delete_cmd = kwargs.get("backup_offsite_delete_cmd", "")
        self.platform_backup_offsite_cmd = kwargs.get("platform_backup_offsite_cmd", "")
        self.backup_s3_endpoint = ""
        self.backup_s3_bucket = ""
        self.backup_s3_access_key = ""
        self.backup_s3_secret_key = ""
        self.backup_s3_region = "auto"
        self.backup_s3_prefix = "ifnotus/"


def test_command_provider_put_and_fetch(tmp_path: Path) -> None:
    mirror = tmp_path / "mirror"
    mirror.mkdir()
    src = tmp_path / "archive.tar.gz"
    payload = b"ifnotus-38k-payload"
    src.write_bytes(payload)
    put_cmd = f"mkdir -p {mirror} && cp -a {{path}} {mirror}/{{basename}}"
    fetch_cmd = f"cp -a {mirror}/{{basename}} {{path}}"
    p = CommandOffsiteProvider(put_cmd, fetch_cmd=fetch_cmd)
    key = "customers/c/e/archive.tar.gz"
    put = p.put(src, key)
    assert put.ok
    assert (mirror / "archive.tar.gz").exists()
    dest = tmp_path / "fetched.tar.gz"
    fetch = p.fetch(key, dest)
    assert fetch.ok
    assert dest.read_bytes() == payload


def test_command_fetch_missing_cmd_is_explicit() -> None:
    p = CommandOffsiteProvider("echo {path}")
    r = p.fetch("customers/c/e/x.tar.gz", Path("/tmp/x"))
    assert r.skipped
    assert "FETCH_CMD" in (r.error or "")


def test_checksum_mismatch_detected(tmp_path: Path) -> None:
    f = tmp_path / "a.tar.gz"
    f.write_bytes(b"abc")
    good = hashlib.sha256(b"abc").hexdigest()
    ok, _ = EnvironmentBackupService.verify_archive_checksum(f, good)
    assert ok
    bad, err = EnvironmentBackupService.verify_archive_checksum(f, "0" * 64)
    assert not bad
    assert err


def test_missing_remote_object_fetch_fails(tmp_path: Path) -> None:
    mirror = tmp_path / "mirror"
    mirror.mkdir()
    p = CommandOffsiteProvider(
        f"cp -a {{path}} {mirror}/{{basename}}",
        fetch_cmd=f"cp -a {mirror}/{{basename}} {{path}}",
    )
    dest = tmp_path / "out.tar.gz"
    r = p.fetch("customers/c/e/missing.tar.gz", dest)
    assert not r.ok


def test_resolve_wires_fetch_cmd() -> None:
    p = resolve_backup_provider(
        _Settings(  # type: ignore[arg-type]
            backup_offsite_provider="command",
            backup_offsite_cmd="echo put {path}",
            backup_offsite_fetch_cmd="echo fetch {basename}",
        )
    )
    assert isinstance(p, CommandOffsiteProvider)
    assert p._fetch.startswith("echo fetch")


def test_null_provider_still_skips() -> None:
    p = resolve_backup_provider(_Settings())  # type: ignore[arg-type]
    assert isinstance(p, NullOffsiteProvider)
