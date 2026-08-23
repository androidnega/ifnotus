"""PHASE 38E — SSH/SFTP Unix identity is separate from legacy FTP."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from app.services.platform.ftp import EnvironmentFtpService
from app.services.platform.ssh_access import EnvironmentSshService


def test_ftp_username_never_equals_unix(test_settings) -> None:
    env_id = uuid4()
    short = str(env_id).replace("-", "")[:10]
    unix = f"u{short}"
    env = SimpleNamespace(
        id=env_id,
        ftp_username=unix,  # legacy collision
        unix_username=unix,
        sftp_username=unix,
    )
    svc = EnvironmentFtpService(test_settings, MagicMock())
    name = svc._username_for(env)  # noqa: SLF001
    assert name != unix
    assert name.startswith("ftp") or name.startswith("u")


def test_ftp_username_keeps_dedicated_identity(test_settings) -> None:
    env = SimpleNamespace(
        id=uuid4(),
        ftp_username="u_dedicated_ftp",
        unix_username="ifn_abc12345",
        sftp_username="ifn_abc12345",
    )
    svc = EnvironmentFtpService(test_settings, MagicMock())
    assert svc._username_for(env) == "u_dedicated_ftp"  # noqa: SLF001


def test_ssh_status_reports_shared_sftp_and_separate_ftp(test_settings) -> None:
    env = SimpleNamespace(
        id=uuid4(),
        unix_username="ifn_abc12345",
        sftp_username="ifn_abc12345",
        ftp_username="u_dedicated_ftp",
        ssh_password_encrypted="x",
        sftp_password_encrypted="x",
    )
    svc = EnvironmentSshService(test_settings, MagicMock())
    payload = svc.status_payload(env, allowed=True, reveal=False)
    assert payload["username"] == "ifn_abc12345"
    assert payload["shares_password_with_sftp"] is True
    assert payload["passwords_differ_from_ftp"] is True
    assert "FTP uses a separate" in payload["hint"]


def test_ssh_status_does_not_use_ftp_username(test_settings) -> None:
    env = SimpleNamespace(
        id=uuid4(),
        unix_username=None,
        sftp_username=None,
        ftp_username="u_only_ftp",
        ssh_password_encrypted=None,
        sftp_password_encrypted=None,
    )
    svc = EnvironmentSshService(test_settings, MagicMock())
    payload = svc.status_payload(env, allowed=True)
    assert payload["username"] is None
    assert payload["enabled"] is False
