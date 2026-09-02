"""Phase 2B-2 unit tests: monitoring SoT, drift, TasksMax, multi-pool, rollback."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

from app.services.platform.php_fpm_environment import (
    DISABLED_SUFFIX,
    DRIFT_STATES,
    STATE_BROKEN_ENV_FPM,
    STATE_DUPLICATE_POOL,
    STATE_GLOBAL_LEGACY,
    STATE_MIGRATED_HEALTHY,
    STATE_PARTIAL_MIGRATION,
    STATE_SOCKET_CONFLICT,
    STATE_STALE_DISABLED,
    PhpFpmEnvironmentService,
    diagnose_migration_state,
    estimate_tasksmax_risk,
    fpm_pool_name,
)
from app.services.platform.workload_slices import (
    MEMORY_ACCOUNTING_NOTE,
    read_cgroup_memory_current,
    resolve_slice_cgroup_path,
    slice_name_for,
)


def _write_pool(pool_dir: Path, hostname: str, user: str, *, max_children: int = 2) -> Path:
    name = fpm_pool_name(hostname)
    body = "\n".join(
        [
            f"[{name}]",
            f"user = {user}",
            f"group = {user}",
            f"listen = /run/php/{name}.sock",
            "listen.owner = www-data",
            "listen.group = www-data",
            "listen.mode = 0660",
            "pm = ondemand",
            f"pm.max_children = {max_children}",
            "pm.process_idle_timeout = 10s",
            "pm.max_requests = 500",
            "",
        ]
    )
    path = pool_dir / f"{name}.conf"
    path.write_text(body, encoding="utf-8")
    return path


def test_memory_current_is_source_of_truth(tmp_path: Path) -> None:
    cg = tmp_path / "slice"
    cg.mkdir()
    (cg / "memory.current").write_text("12687744\n", encoding="utf-8")
    assert read_cgroup_memory_current(cg) == 12687744
    assert "memory.current" in MEMORY_ACCOUNTING_NOTE
    assert "RSS" in MEMORY_ACCOUNTING_NOTE


def test_resolve_slice_uses_systemctl_control_group(tmp_path, monkeypatch) -> None:
    from app.services.platform import workload_slices as ws

    root = tmp_path / "cgroup"
    leaf = (
        root
        / "ifnotus.slice"
        / "ifnotus-workloads.slice"
        / "ifnotus-workloads-tenants.slice"
        / "ifnotus-workloads-tenants-env.slice"
        / "ifnotus-workloads-tenants-env-b731c89a.slice"
    )
    leaf.mkdir(parents=True)
    monkeypatch.setattr(ws, "_CGROUP_ROOT", root)

    class _Proc:
        stdout = "/ifnotus.slice/ifnotus-workloads.slice/ifnotus-workloads-tenants.slice/ifnotus-workloads-tenants-env.slice/ifnotus-workloads-tenants-env-b731c89a.slice\n"

    def fake_run(cmd, **kwargs):  # noqa: ANN001
        assert cmd[0] == "systemctl"
        return _Proc()

    monkeypatch.setattr(ws.subprocess, "run", fake_run)
    got = resolve_slice_cgroup_path("ifnotus-workloads-tenants-env-b731c89a.slice")
    assert got == leaf
    # Must not resolve legacy ifnotus-env-* as the new name
    assert "ifnotus-env-b731c89a" not in str(got)


def test_multi_pool_env_one_master(tmp_path: Path) -> None:
    pool_dir = tmp_path / "pool.d"
    pool_dir.mkdir()
    eid = uuid4()
    user = f"ifn_{str(eid).split('-')[0]}"
    for host in ("a.example", "b.example", "sub.c.example"):
        _write_pool(pool_dir, host, user)
    env = SimpleNamespace(
        id=eid,
        domain="a.example",
        unix_username=user,
        status="active",
        domains=[
            SimpleNamespace(domain_name="b.example"),
            SimpleNamespace(domain_name="sub.c.example"),
        ],
    )
    svc = PhpFpmEnvironmentService(pool_dir=pool_dir, env_root=tmp_path / "e", systemd_dir=tmp_path / "s")
    (tmp_path / "s").mkdir()
    plan = svc.plan_migrate(env)
    assert not plan.errors
    assert len(plan.pools) == 3
    assert plan.service_name == f"ifnotus-php-fpm@{str(eid).split('-')[0]}.service"
    assert plan.slice_name == slice_name_for(eid)
    # Domain count does not create more masters
    assert plan.service_name.count("@") == 1


def test_socket_duplicate_detection(tmp_path: Path) -> None:
    pool_dir = tmp_path / "pool.d"
    pool_dir.mkdir()
    eid = uuid4()
    user = f"ifn_{str(eid).split('-')[0]}"
    host = "dup.example"
    _write_pool(pool_dir, host, user)
    other = pool_dir / "ifnotus-other.conf"
    other.write_text(
        f"[ifnotus-other]\nuser = www-data\ngroup = www-data\nlisten = /run/php/{fpm_pool_name(host)}.sock\n",
        encoding="utf-8",
    )
    env = SimpleNamespace(id=eid, domain=host, unix_username=user, status="active")
    svc = PhpFpmEnvironmentService(pool_dir=pool_dir, env_root=tmp_path / "e", systemd_dir=tmp_path / "s")
    (tmp_path / "s").mkdir()
    plan = svc.plan_migrate(env)
    assert any("socket collision" in e for e in plan.errors)


def test_partial_migration_and_drift_states() -> None:
    assert diagnose_migration_state(
        env_unit_active=True,
        global_pools_active=["p1"],
        global_pools_disabled=["p2"],
        sockets_exist=[True],
        socket_conflicts=[],
        duplicate_pool_names=[],
    ) == STATE_PARTIAL_MIGRATION
    assert diagnose_migration_state(
        env_unit_active=True,
        global_pools_active=[],
        global_pools_disabled=["p1"],
        sockets_exist=[True],
        socket_conflicts=[],
        duplicate_pool_names=[],
    ) == STATE_MIGRATED_HEALTHY
    assert diagnose_migration_state(
        env_unit_active=False,
        global_pools_active=["p1"],
        global_pools_disabled=[],
        sockets_exist=[True],
        socket_conflicts=[],
        duplicate_pool_names=[],
    ) == STATE_GLOBAL_LEGACY
    assert diagnose_migration_state(
        env_unit_active=True,
        global_pools_active=[],
        global_pools_disabled=["p1"],
        sockets_exist=[False],
        socket_conflicts=[],
        duplicate_pool_names=[],
    ) == STATE_BROKEN_ENV_FPM
    assert diagnose_migration_state(
        env_unit_active=False,
        global_pools_active=[],
        global_pools_disabled=["p1"],
        sockets_exist=[],
        socket_conflicts=[],
        duplicate_pool_names=[],
    ) == STATE_STALE_DISABLED
    assert diagnose_migration_state(
        env_unit_active=True,
        global_pools_active=["p1"],
        global_pools_disabled=[],
        sockets_exist=[True],
        socket_conflicts=[],
        duplicate_pool_names=[],
    ) == STATE_DUPLICATE_POOL
    assert diagnose_migration_state(
        env_unit_active=True,
        global_pools_active=[],
        global_pools_disabled=["p1"],
        sockets_exist=[True],
        socket_conflicts=["/run/php/x.sock"],
        duplicate_pool_names=[],
    ) == STATE_SOCKET_CONFLICT
    for s in (
        STATE_MIGRATED_HEALTHY,
        STATE_GLOBAL_LEGACY,
        STATE_PARTIAL_MIGRATION,
        STATE_SOCKET_CONFLICT,
        STATE_DUPLICATE_POOL,
        STATE_BROKEN_ENV_FPM,
        STATE_STALE_DISABLED,
    ):
        assert s in DRIFT_STATES


def test_rollback_restores_global_pool(tmp_path: Path, monkeypatch) -> None:
    pool_dir = tmp_path / "pool.d"
    pool_dir.mkdir()
    eid = uuid4()
    user = f"ifn_{str(eid).split('-')[0]}"
    host = "rb.example"
    _write_pool(pool_dir, host, user)
    name = fpm_pool_name(host)
    conf = pool_dir / f"{name}.conf"
    disabled = pool_dir / f"{name}.conf{DISABLED_SUFFIX}"
    conf.rename(disabled)
    env = SimpleNamespace(id=eid, domain=host, unix_username=user, status="active")
    svc = PhpFpmEnvironmentService(
        pool_dir=pool_dir,
        env_root=tmp_path / "e",
        systemd_dir=tmp_path / "s",
        backup_root=tmp_path / "bak",
    )
    (tmp_path / "s").mkdir()
    plan = svc.plan_migrate(env)

    class _Ok:
        returncode = 0
        stdout = ""
        stderr = ""

    monkeypatch.setattr(svc, "_systemctl", lambda *a, **k: _Ok())
    monkeypatch.setattr(svc, "_global_fpm_test", lambda: (True, "ok"))
    report = svc.rollback(plan)
    assert report["ok"] is True
    assert conf.is_file()
    assert not disabled.exists()


def test_remigration_after_rollback(tmp_path: Path, monkeypatch) -> None:
    pool_dir = tmp_path / "pool.d"
    pool_dir.mkdir()
    eid = uuid4()
    user = f"ifn_{str(eid).split('-')[0]}"
    host = "re.example"
    _write_pool(pool_dir, host, user)
    env = SimpleNamespace(id=eid, domain=host, unix_username=user, status="active")
    fake_php = tmp_path / "php-fpm8.3"
    fake_php.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    fake_php.chmod(0o755)
    svc = PhpFpmEnvironmentService(
        pool_dir=pool_dir,
        env_root=tmp_path / "envs",
        systemd_dir=tmp_path / "s",
        backup_root=tmp_path / "bak",
        php_bin=fake_php,
    )
    (tmp_path / "s").mkdir()
    plan = svc.plan_migrate(env)
    assert not plan.errors
    for a in plan.actions:
        if a.get("action") == "ensure_dirs":
            a["paths"] = [str(tmp_path / "run"), str(tmp_path / "log")]

    class _Ok:
        returncode = 0
        stdout = "active\n"
        stderr = ""

    monkeypatch.setattr(svc, "_systemctl", lambda *a, **k: _Ok())
    monkeypatch.setattr(svc, "validate_config", lambda *_a, **_k: (True, "ok"))
    monkeypatch.setattr(svc, "_global_fpm_test", lambda: (True, "ok"))
    report = svc.apply_migrate(plan, dry_run=False)
    assert report["ok"] is True
    assert (pool_dir / f"{fpm_pool_name(host)}.conf{DISABLED_SUFFIX}").is_file()
    rb = svc.rollback(plan)
    assert rb["ok"]
    assert (pool_dir / f"{fpm_pool_name(host)}.conf").is_file()
    plan2 = svc.plan_migrate(env)
    for a in plan2.actions:
        if a.get("action") == "ensure_dirs":
            a["paths"] = [str(tmp_path / "run"), str(tmp_path / "log")]
    report2 = svc.apply_migrate(plan2, dry_run=False)
    assert report2["ok"] is True
    assert (pool_dir / f"{fpm_pool_name(host)}.conf{DISABLED_SUFFIX}").is_file()


def test_tasksmax_risk_calculation() -> None:
    ok = estimate_tasksmax_risk(tasks_max=32, pm_max_children=2)
    assert ok["risk"] is False
    assert ok["code"] is None
    risky = estimate_tasksmax_risk(tasks_max=32, pm_max_children=28, has_node_runtime=True)
    assert risky["risk"] is True
    assert risky["code"] == "TASKSMAX_RISK"


def test_dry_run_mutation_free(tmp_path: Path) -> None:
    pool_dir = tmp_path / "pool.d"
    pool_dir.mkdir()
    eid = uuid4()
    user = f"ifn_{str(eid).split('-')[0]}"
    host = "dry2.example"
    _write_pool(pool_dir, host, user)
    before = sorted(p.name for p in pool_dir.iterdir())
    env = SimpleNamespace(id=eid, domain=host, unix_username=user, status="active")
    svc = PhpFpmEnvironmentService(
        pool_dir=pool_dir,
        env_root=tmp_path / "envs",
        systemd_dir=tmp_path / "s",
        backup_root=tmp_path / "bak",
    )
    (tmp_path / "s").mkdir()
    plan = svc.plan_migrate(env)
    report = svc.apply_migrate(plan, dry_run=True)
    assert report["dry_run"] is True
    assert sorted(p.name for p in pool_dir.iterdir()) == before
    assert not (tmp_path / "envs").exists()


def test_customer_filesystem_untouched(tmp_path: Path) -> None:
    pool_dir = tmp_path / "pool.d"
    pool_dir.mkdir()
    tenant = tmp_path / "sites" / "public_html"
    tenant.mkdir(parents=True)
    marker = tenant / "index.php"
    marker.write_text("<?php // customer\n", encoding="utf-8")
    before = marker.stat().st_mtime_ns
    content = marker.read_bytes()
    eid = uuid4()
    user = f"ifn_{str(eid).split('-')[0]}"
    host = "fs.example"
    _write_pool(pool_dir, host, user)
    env = SimpleNamespace(id=eid, domain=host, unix_username=user, status="active")
    svc = PhpFpmEnvironmentService(
        pool_dir=pool_dir,
        env_root=tmp_path / "e",
        systemd_dir=tmp_path / "s",
        backup_root=tmp_path / "bak",
    )
    (tmp_path / "s").mkdir()
    plan = svc.plan_migrate(env)
    svc.apply_migrate(plan, dry_run=True)
    assert marker.read_bytes() == content
    assert marker.stat().st_mtime_ns == before
    assert all("/public_html" not in str(a) for a in plan.actions)


def test_fpm_grouping_independent_of_domain_count(tmp_path: Path) -> None:
    pool_dir = tmp_path / "pool.d"
    pool_dir.mkdir()
    eid = uuid4()
    user = f"ifn_{str(eid).split('-')[0]}"
    hosts = [f"h{i}.example" for i in range(5)]
    for h in hosts:
        _write_pool(pool_dir, h, user)
    env = SimpleNamespace(
        id=eid,
        domain=hosts[0],
        unix_username=user,
        status="active",
        domains=[SimpleNamespace(domain_name=h) for h in hosts[1:]],
    )
    svc = PhpFpmEnvironmentService(pool_dir=pool_dir, env_root=tmp_path / "e", systemd_dir=tmp_path / "s")
    (tmp_path / "s").mkdir()
    plan = svc.plan_migrate(env)
    assert len(plan.pools) == 5
    assert plan.service_name == f"ifnotus-php-fpm@{str(eid).split('-')[0]}.service"


def test_vps_vds_excluded(tmp_path: Path) -> None:
    pool_dir = tmp_path / "pool.d"
    pool_dir.mkdir()
    eid = uuid4()
    user = f"ifn_{str(eid).split('-')[0]}"
    host = "vds.example"
    _write_pool(pool_dir, host, user)
    env = SimpleNamespace(id=eid, domain=host, unix_username=user, status="active")
    svc = PhpFpmEnvironmentService(pool_dir=pool_dir, env_root=tmp_path / "e", systemd_dir=tmp_path / "s")
    (tmp_path / "s").mkdir()
    assert svc.plan_migrate(env, plan_class="VPS_STYLE").errors
    assert svc.plan_migrate(env, plan_class="VDS_STYLE").errors
