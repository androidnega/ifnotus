"""Unit tests for per-environment systemd/cgroup slice helpers (Phase E)."""

from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

from app.services.platform.systemd_env_slice import (
    EnvironmentSliceService,
    limits_from_env,
    slice_name_for,
)


def test_slice_name_is_stable_and_safe() -> None:
    eid = uuid4()
    name = slice_name_for(eid)
    assert name.startswith("ifnotus-env-")
    assert name.endswith(".slice")
    assert slice_name_for(eid) == name
    assert ".." not in name
    assert "/" not in name


def test_limits_from_env_maps_vcpu_and_ram() -> None:
    env = SimpleNamespace(
        id=uuid4(),
        cpu_limit=0.2,
        ram_limit_gb=0.25,
    )
    limits = limits_from_env(env, plan=None)
    assert limits.cpu_quota_percent == 20
    assert limits.memory_max_bytes == int(0.25 * 1024 * 1024 * 1024)
    assert limits.tasks_max >= 16
    assert limits.slice_name == slice_name_for(env.id)


def test_unit_body_contains_enforcement_directives() -> None:
    env = SimpleNamespace(id=uuid4(), cpu_limit=1.0, ram_limit_gb=1.0)
    limits = limits_from_env(env)
    body = EnvironmentSliceService._unit_body(limits)
    assert f"CPUQuota={limits.cpu_quota_percent}%" in body
    assert f"MemoryMax={limits.memory_max_bytes}" in body
    assert f"TasksMax={limits.tasks_max}" in body
    assert "[Slice]" in body


def test_ensure_slice_skips_without_systemd(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.services.platform.systemd_env_slice.systemd_available",
        lambda: False,
    )
    env = SimpleNamespace(id=uuid4(), cpu_limit=0.5, ram_limit_gb=0.5)
    result = EnvironmentSliceService().ensure_slice(env)
    assert result.get("skipped") == "systemd_unavailable"
    assert "applied" not in result


def test_wrap_command_passthrough_without_systemd_run(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.services.platform.systemd_env_slice.systemd_available",
        lambda: True,
    )
    monkeypatch.setattr(
        "app.services.platform.systemd_env_slice.shutil.which",
        lambda name: None if name == "systemd-run" else f"/usr/bin/{name}",
    )
    env = SimpleNamespace(id=uuid4(), cpu_limit=0.5, ram_limit_gb=0.5, unix_uid=1001)
    cmd = EnvironmentSliceService().wrap_command_in_slice("php artisan schedule:run", env)
    assert cmd == "php artisan schedule:run"


def test_wrap_command_prefixes_systemd_run(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.services.platform.systemd_env_slice.systemd_available",
        lambda: True,
    )

    def _which(name: str):
        if name in ("systemd-run", "systemctl"):
            return f"/usr/bin/{name}"
        return None

    monkeypatch.setattr("app.services.platform.systemd_env_slice.shutil.which", _which)
    monkeypatch.setattr(
        EnvironmentSliceService,
        "ensure_slice",
        lambda self, env, plan=None: {"applied": True, "slice": slice_name_for(env.id)},
    )
    env = SimpleNamespace(id=uuid4(), cpu_limit=0.5, ram_limit_gb=0.5, unix_uid=1001)
    cmd = EnvironmentSliceService().wrap_command_in_slice("node server.js", env)
    assert cmd.startswith("systemd-run ")
    assert f"--slice={slice_name_for(env.id)}" in cmd
    assert "--uid=1001" in cmd
    assert cmd.endswith("-- node server.js")
