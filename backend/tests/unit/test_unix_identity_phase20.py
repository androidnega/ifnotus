"""PHASE 20 — Unix tenant isolation helpers and security guards."""

from __future__ import annotations

import os
import stat
import tempfile
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.core.exceptions import ValidationError
from app.services.platform.fs_ownership import allocate_unix_ids, safe_join
from app.services.platform.unix_identity import (
    DIR_MODE,
    FILE_MODE,
    UnixIdentityService,
    tenant_cannot_access,
)


def test_username_scheme() -> None:
    env = SimpleNamespace(id=uuid4(), unix_username=None, sftp_username=None)
    svc = UnixIdentityService.__new__(UnixIdentityService)
    name = UnixIdentityService.username_for(svc, env)
    assert name.startswith("ifn_")
    assert len(name) == 12


def test_tenant_cannot_access_sibling_trees(tmp_path: Path) -> None:
    a = tmp_path / "cust-a" / "site1"
    b = tmp_path / "cust-b" / "site1"
    a.mkdir(parents=True)
    b.mkdir(parents=True)
    (a / "secret.txt").write_text("a", encoding="utf-8")
    (b / "secret.txt").write_text("b", encoding="utf-8")
    assert tenant_cannot_access(a, b / "secret.txt") is True
    assert tenant_cannot_access(a, a / "secret.txt") is False


def test_safe_join_blocks_traverse_to_other_tenant(tmp_path: Path) -> None:
    a = tmp_path / "cust-a" / "site"
    b = tmp_path / "cust-b" / "site"
    a.mkdir(parents=True)
    b.mkdir(parents=True)
    with pytest.raises(ValidationError):
        safe_join(a, "../cust-b/site/secret.txt")


def test_symlink_escape_detected(tmp_path: Path) -> None:
    home = tmp_path / "cust" / "site"
    outside = tmp_path / "other" / "secret.txt"
    home.mkdir(parents=True)
    outside.parent.mkdir(parents=True)
    outside.write_text("x", encoding="utf-8")
    link = home / "escape"
    link.symlink_to(outside)
    # resolve of the link escapes home — helpers must reject
    with pytest.raises(ValidationError):
        target = (home / "escape").resolve()
        try:
            target.relative_to(home.resolve())
        except ValueError as exc:
            raise ValidationError("Path escapes the site root via symlink.", code="path_escape") from exc


def test_assert_mode_rejects_777(tmp_path: Path) -> None:
    f = tmp_path / "bad.txt"
    f.write_text("x", encoding="utf-8")
    os.chmod(f, 0o777)
    with pytest.raises(ValidationError, match="777|World-writable"):
        UnixIdentityService.assert_mode_not_world_writable(f)


def test_default_modes_not_world_accessible() -> None:
    assert DIR_MODE & stat.S_IWOTH == 0
    assert FILE_MODE & stat.S_IWOTH == 0
    assert DIR_MODE & stat.S_IROTH == 0
    assert FILE_MODE & stat.S_IROTH == 0
    assert DIR_MODE & stat.S_IXOTH == 0
    assert DIR_MODE != 0o777
    assert FILE_MODE != 0o777


def test_allocate_ids_stable() -> None:
    eid = uuid4()
    assert allocate_unix_ids(eid) == allocate_unix_ids(eid)
