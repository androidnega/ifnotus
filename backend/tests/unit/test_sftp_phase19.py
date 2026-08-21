"""PHASE 19 — Real SFTP helpers and entitlement policy."""

from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.services.platform.plan_matrix import capabilities_for, ssh_mode, sftp_enabled
from app.services.platform.sftp_access import EnvironmentSftpService


def test_username_scheme_ifn_prefix() -> None:
    env_id = uuid4()
    env = SimpleNamespace(id=env_id, sftp_username=None)
    # Bind unbound method style
    name = EnvironmentSftpService.username_for(EnvironmentSftpService.__new__(EnvironmentSftpService), env)  # type: ignore[arg-type]
    assert name.startswith("ifn_")
    assert len(name) == 12


def test_validate_public_key_accepts_ed25519() -> None:
    key = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIFakeKeyMaterialForUnitTestOnly comment"
    out = EnvironmentSftpService.validate_public_key(key)
    assert out.startswith("ssh-ed25519")


def test_validate_public_key_rejects_garbage() -> None:
    from app.core.exceptions import ValidationError

    with pytest.raises(ValidationError):
        EnvironmentSftpService.validate_public_key("not-a-key")


def test_capabilities_expose_sftp_and_ssh_keys() -> None:
    plan = SimpleNamespace(
        slug="student-starter",
        name="Student",
        price_monthly=50,
        features={},
    )
    caps = capabilities_for(plan)
    assert caps["on"]["sftp"] is True
    assert caps["on"]["sftp.enabled"] is True
    assert caps["sftp"]["enabled"] is True
    assert "ssh.mode" in caps["on"]
    assert caps["ssh"]["mode"] in {"no", "limited", "jail", "root"}


def test_root_allowed_only_off_shared_node() -> None:
    from app.services.platform.plan_matrix import sellable_on_shared_node

    vps = SimpleNamespace(
        slug="cloud-vps",
        name="Cloud VPS",
        price_monthly=200,
        features={"matrix_key": "cloud-vps"},
    )
    assert sellable_on_shared_node(vps) is False
    assert ssh_mode(vps) == "root"
    caps = capabilities_for(vps)
    assert caps["on"]["root"] is True

    managed = SimpleNamespace(
        slug="student-pro",
        name="Student Pro",
        price_monthly=100,
        features={"matrix_key": "student-pro"},
    )
    assert sellable_on_shared_node(managed) is True
    assert ssh_mode(managed) != "root"
    assert capabilities_for(managed)["on"]["root"] is False


def test_sftp_enabled_helper() -> None:
    plan = SimpleNamespace(slug="personal", name="Personal", price_monthly=80, features={})
    assert sftp_enabled(plan) is True
