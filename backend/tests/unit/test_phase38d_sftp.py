"""PHASE 38D — Real SFTP sshd drop-in + jail layout."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.core.exceptions import AppException
from app.services.platform.sftp_access import (
    SFTP_CONTENT_DIR,
    SFTP_GROUP,
    EnvironmentSftpService,
)


def test_render_sshd_dropin_has_match_chroot_no_duplicate_subsystem(test_settings) -> None:
    text = EnvironmentSftpService.render_sshd_dropin()
    assert f"Match Group {SFTP_GROUP},!ifnotus-ssh" in text
    assert "ChrootDirectory %h" in text
    assert f"ForceCommand internal-sftp -d /{SFTP_CONTENT_DIR}" in text
    assert "Subsystem sftp" not in [
        line.strip() for line in text.splitlines() if not line.strip().startswith("#")
    ]


def test_jail_paths_flat_docroot(test_settings, tmp_path: Path) -> None:
    customer_id = uuid4()
    root = tmp_path / "customers"
    env_dir = root / str(customer_id) / "site.example"
    env_dir.mkdir(parents=True)
    (env_dir / "index.html").write_text("ok", encoding="utf-8")
    settings = test_settings.model_copy(update={"customer_environments_root": str(root)})
    svc = EnvironmentSftpService(settings, session=None)  # type: ignore[arg-type]
    env = SimpleNamespace(customer_id=customer_id, document_root=str(env_dir), id=uuid4())
    chroot, content = svc.jail_paths(env)  # type: ignore[arg-type]
    assert chroot == env_dir.resolve()
    assert content == (env_dir / SFTP_CONTENT_DIR).resolve()


def test_jail_paths_already_public(test_settings, tmp_path: Path) -> None:
    customer_id = uuid4()
    root = tmp_path / "customers"
    content = root / str(customer_id) / "site.example" / "public"
    content.mkdir(parents=True)
    settings = test_settings.model_copy(update={"customer_environments_root": str(root)})
    svc = EnvironmentSftpService(settings, session=None)  # type: ignore[arg-type]
    env = SimpleNamespace(customer_id=customer_id, document_root=str(content), id=uuid4())
    chroot, got = svc.jail_paths(env)  # type: ignore[arg-type]
    assert got == content.resolve()
    assert chroot == content.parent.resolve()


def test_jail_paths_rejects_outside_tenant(test_settings, tmp_path: Path) -> None:
    root = tmp_path / "customers"
    root.mkdir()
    other = tmp_path / "other" / "site"
    other.mkdir(parents=True)
    settings = test_settings.model_copy(update={"customer_environments_root": str(root)})
    svc = EnvironmentSftpService(settings, session=None)  # type: ignore[arg-type]
    env = SimpleNamespace(customer_id=uuid4(), document_root=str(other), id=uuid4())
    with pytest.raises(AppException) as exc:
        svc.jail_paths(env)  # type: ignore[arg-type]
    assert exc.value.code == "sftp_home_outside_tenant"


def test_ensure_jail_layout_migrates_flat_tree(test_settings, tmp_path: Path) -> None:
    customer_id = uuid4()
    root = tmp_path / "customers"
    env_dir = root / str(customer_id) / "site.example"
    env_dir.mkdir(parents=True)
    (env_dir / "index.html").write_text("hello", encoding="utf-8")
    settings = test_settings.model_copy(update={"customer_environments_root": str(root)})
    svc = EnvironmentSftpService(settings, session=None)  # type: ignore[arg-type]
    env = SimpleNamespace(customer_id=customer_id, document_root=str(env_dir), id=uuid4())
    chroot, content = svc.ensure_jail_layout(env)  # type: ignore[arg-type]
    assert chroot == env_dir.resolve()
    assert content == (env_dir / "public").resolve()
    assert (content / "index.html").read_text(encoding="utf-8") == "hello"
    assert env.document_root == str(content)
