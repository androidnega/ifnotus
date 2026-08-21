"""safe_join path escape rejection (PHASE 8)."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.core.exceptions import ValidationError
from app.services.platform.fs_ownership import allocate_unix_ids, safe_join


def test_safe_join_allows_nested_relative(tmp_path: Path) -> None:
    root = tmp_path / "site"
    root.mkdir()
    (root / "wp-content").mkdir()
    out = safe_join(root, "wp-content/uploads")
    assert out == (root / "wp-content" / "uploads").resolve()


def test_safe_join_rejects_parent_segments(tmp_path: Path) -> None:
    root = tmp_path / "site"
    root.mkdir()
    with pytest.raises(ValidationError) as exc:
        safe_join(root, "../etc/passwd")
    assert exc.value.code == "path_escape"


def test_safe_join_rejects_absolute(tmp_path: Path) -> None:
    root = tmp_path / "site"
    root.mkdir()
    with pytest.raises(ValidationError):
        safe_join(root, "/etc/passwd")


def test_safe_join_rejects_encoded_traversal(tmp_path: Path) -> None:
    root = tmp_path / "site"
    root.mkdir()
    with pytest.raises(ValidationError):
        safe_join(root, "foo/../../outside")


def test_allocate_unix_ids_in_range_and_stable() -> None:
    env_id = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
    a = allocate_unix_ids(env_id)
    b = allocate_unix_ids(env_id)
    assert a == b
    uid, gid = a
    assert 20000 <= uid <= 49999
    assert 20000 <= gid <= 49999
