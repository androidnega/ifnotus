"""PHASE 31 + 38B — package-aware cron safety; never execute as worker/root."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from app.core.exceptions import AppException, ValidationError
from app.services.platform.env_cron import (
    EnvironmentCronService,
    estimate_min_interval_minutes,
    entitlements_for_plan,
    validate_command,
    validate_schedule,
)


def test_estimate_interval_star_slash() -> None:
    assert estimate_min_interval_minutes("*/15 * * * *") == 15
    assert estimate_min_interval_minutes("*/5 * * * *") == 5
    assert estimate_min_interval_minutes("* * * * *") == 1


def test_validate_schedule_rejects_too_frequent() -> None:
    with pytest.raises(ValidationError, match="at least 15"):
        validate_schedule("* * * * *", min_interval_minutes=15)
    assert validate_schedule("*/15 * * * *", min_interval_minutes=15) == "*/15 * * * *"


def test_starter_entitlements() -> None:
    plan = SimpleNamespace(
        slug="student-starter",
        features={"matrix_key": "student-starter"},
    )
    ent = entitlements_for_plan(plan)  # type: ignore[arg-type]
    assert ent.max_jobs == 2
    assert ent.min_interval_minutes == 15


def test_pro_entitlements() -> None:
    plan = SimpleNamespace(
        slug="student-pro",
        features={"matrix_key": "student-pro"},
    )
    ent = entitlements_for_plan(plan)  # type: ignore[arg-type]
    assert ent.max_jobs == 10
    assert ent.min_interval_minutes == 5


def test_validate_command_blocks_shell_metachar() -> None:
    with pytest.raises(ValidationError):
        validate_command("php artisan; rm -rf /")


def test_build_argv_uses_runuser() -> None:
    env = MagicMock(unix_username="u_demo", id="x", domain="demo.test", status="active")
    svc = EnvironmentCronService(MagicMock(), MagicMock())
    with (
        patch("app.services.platform.env_cron.shutil.which", side_effect=lambda n: f"/usr/sbin/{n}" if n == "runuser" else None),
        patch("pwd.getpwnam", return_value=SimpleNamespace(pw_name="u_demo")),
    ):
        argv = svc._build_argv(env, "php artisan schedule:run")
    assert argv[0].endswith("runuser")
    assert "u_demo" in argv
    assert "bash" in argv
    # Never a bare worker bash -lc without runuser/sudo
    assert argv[0] != "bash"


def test_build_argv_rejects_missing_unix_user() -> None:
    env = MagicMock(unix_username="", id="x", domain="demo.test", status="active")
    svc = EnvironmentCronService(MagicMock(), MagicMock())
    with pytest.raises(AppException, match="Unix user"):
        svc._build_argv(env, "php -v")


def test_build_argv_rejects_unknown_unix_user() -> None:
    env = MagicMock(unix_username="ifn_missing", id="x", domain="demo.test", status="active")
    svc = EnvironmentCronService(MagicMock(), MagicMock())
    with patch("pwd.getpwnam", side_effect=KeyError("ifn_missing")):
        with pytest.raises(AppException, match="does not exist"):
            svc._build_argv(env, "php -v")


def test_build_argv_rejects_when_helpers_missing() -> None:
    env = MagicMock(unix_username="u_demo", id="x", domain="demo.test", status="active")
    svc = EnvironmentCronService(MagicMock(), MagicMock())
    with (
        patch("pwd.getpwnam", return_value=SimpleNamespace(pw_name="u_demo")),
        patch("app.services.platform.env_cron.shutil.which", return_value=None),
    ):
        with pytest.raises(AppException, match="runuser"):
            svc._build_argv(env, "php -v")


def test_run_job_rejects_suspended_environment(tmp_path) -> None:
    env = SimpleNamespace(
        id="e1",
        unix_username="u_demo",
        domain="demo.test",
        status="suspended",
        document_root=str(tmp_path),
    )
    svc = EnvironmentCronService(MagicMock(), MagicMock())
    svc._load = MagicMock(return_value=[{"id": "j1", "command": "php -v", "schedule": "0 * * * *", "enabled": True}])  # type: ignore[method-assign]
    with pytest.raises(AppException, match="not active"):
        svc.run_job(env, "j1")  # type: ignore[arg-type]
