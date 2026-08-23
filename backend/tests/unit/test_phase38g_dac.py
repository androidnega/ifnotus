"""PHASE 38G — tenant filesystem DAC."""

from __future__ import annotations

import os
import stat
from pathlib import Path
from uuid import uuid4

from app.services.platform.fs_ownership import (
    CUSTOMER_PREFIX_MODE,
    DIR_MODE_SAFE,
    FILE_MODE_SAFE,
    harden_customer_prefixes,
    ownership_plan,
    safe_join,
)
from app.services.platform.unix_identity import DIR_MODE, FILE_MODE, tenant_cannot_access
from app.core.exceptions import ValidationError
import pytest


def test_modes_deny_world_access() -> None:
    assert DIR_MODE & stat.S_IROTH == 0
    assert DIR_MODE & stat.S_IWOTH == 0
    assert DIR_MODE & stat.S_IXOTH == 0
    assert FILE_MODE & stat.S_IROTH == 0
    assert FILE_MODE & stat.S_IWOTH == 0
    assert DIR_MODE == DIR_MODE_SAFE
    assert FILE_MODE == FILE_MODE_SAFE


def test_ownership_plan_not_world() -> None:
    plan = ownership_plan(tenant_uid=20001, web_gid=33, prepare_sftp_jail=True)
    assert plan["world_readable"] is False
    assert plan["world_writable"] is False
    assert plan["sftp_chroot_root_owned"] is True


def test_harden_customer_prefixes(tmp_path: Path) -> None:
    root = tmp_path / "customers"
    cid = uuid4()
    prefix = root / str(cid)
    prefix.mkdir(parents=True)
    # Simulate permissive defaults
    os.chmod(root, 0o755)
    os.chmod(prefix, 0o755)
    # www-data may not exist in unit env — function should still chmod when possible
    result = harden_customer_prefixes(root, customer_id=cid, web_user="root")
    assert result.get("customer_prefix_mode") == oct(CUSTOMER_PREFIX_MODE)
    assert stat.S_IMODE(prefix.stat().st_mode) == CUSTOMER_PREFIX_MODE
    assert stat.S_IMODE(root.stat().st_mode) & stat.S_IXOTH == 0


def test_safe_join_and_cross_tenant(tmp_path: Path) -> None:
    a = tmp_path / "a" / "site"
    b = tmp_path / "b" / "site"
    a.mkdir(parents=True)
    b.mkdir(parents=True)
    (b / "secret.txt").write_text("nope", encoding="utf-8")
    assert tenant_cannot_access(a, b / "secret.txt") is True
    with pytest.raises(ValidationError):
        safe_join(a, "../../b/site/secret.txt")
