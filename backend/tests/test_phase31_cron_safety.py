"""PHASE 31 — package-aware cron safety."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from app.core.exceptions import ValidationError
from app.services.platform.env_cron import (
    estimate_min_interval_minutes,
    entitlements_for_plan,
    validate_command,
    validate_schedule,
    EnvironmentCronService,
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
    env = MagicMock(unix_username="u_demo", id="x", domain="demo.test")
    svc = EnvironmentCronService(MagicMock(), MagicMock())
    with patch("app.services.platform.env_cron.shutil.which", side_effect=lambda n: f"/usr/sbin/{n}" if n == "runuser" else None):
        argv = svc._build_argv(env, "php artisan schedule:run")
    assert argv[0].endswith("runuser")
    assert "u_demo" in argv
    assert "bash" in argv
