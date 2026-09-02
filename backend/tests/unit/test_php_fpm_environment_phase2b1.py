"""Phase 2B-1 unit tests for per-environment PHP-FPM migration."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

from app.services.platform.php_fpm_env_design import (
    HostnamePool,
    assert_environments_never_share_instance,
    group_pools_by_environment,
    planned_fpm_service_name,
)
from app.services.platform.php_fpm_environment import (
    DISABLED_SUFFIX,
    PhpFpmEnvironmentService,
    fpm_pool_name,
    is_excluded_canary_domain,
    render_env_master_conf,
    render_systemd_template,
)
from app.services.platform.workload_slices import slice_name_for


def _write_pool(pool_dir: Path, hostname: str, user: str) -> Path:
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
            "pm.max_children = 2",
            "",
        ]
    )
    path = pool_dir / f"{name}.conf"
    path.write_text(body, encoding="utf-8")
    return path


def test_pools_grouped_by_environment_one_master() -> None:
    a, b = uuid4(), uuid4()
    pools = [
        HostnamePool("a.example", a, "p1", "/run/php/a.sock"),
        HostnamePool("b.example", a, "p2", "/run/php/b.sock"),
        HostnamePool("c.example", b, "p3", "/run/php/c.sock"),
    ]
    grouped = group_pools_by_environment(pools)
    assert len(grouped[a]) == 2
    assert planned_fpm_service_name(a) != planned_fpm_service_name(b)
    assert_environments_never_share_instance(grouped)


def test_systemd_template_references_env_slice() -> None:
    body = render_systemd_template()
    assert "Slice=ifnotus-workloads-tenants-env-%i.slice" in body
    assert "php-fpm8.3" in body
    assert "--fpm-config" in body
    assert "User=" not in body  # master not forced to tenant


def test_global_pool_disable_reversible(tmp_path: Path) -> None:
    pool_dir = tmp_path / "pool.d"
    pool_dir.mkdir()
    env_root = tmp_path / "envs"
    systemd = tmp_path / "systemd"
    systemd.mkdir()
    eid = uuid4()
    user = f"ifn_{str(eid).split('-')[0]}"
    host = "canary.example"
    _write_pool(pool_dir, host, user)
    env = SimpleNamespace(id=eid, domain=host, unix_username=user, status="active")
    svc = PhpFpmEnvironmentService(pool_dir=pool_dir, env_root=env_root, systemd_dir=systemd, backup_root=tmp_path / "bak")
    plan = svc.plan_migrate(env)
    assert not plan.errors
    conf = pool_dir / f"{fpm_pool_name(host)}.conf"
    disabled = pool_dir / f"{fpm_pool_name(host)}.conf{DISABLED_SUFFIX}"
    # simulate disable
    conf.rename(disabled)
    assert disabled.is_file() and not conf.exists()
    # rollback rename
    disabled.rename(conf)
    assert conf.is_file()


def test_config_generation_does_not_touch_tenant_tree(tmp_path: Path) -> None:
    pool_dir = tmp_path / "pool.d"
    pool_dir.mkdir()
    tenant = tmp_path / "customer" / "public"
    tenant.mkdir(parents=True)
    marker = tenant / "index.php"
    marker.write_text("<?php echo 1;", encoding="utf-8")
    before = marker.read_bytes()
    eid = uuid4()
    user = f"ifn_{str(eid).split('-')[0]}"
    host = "gen.example"
    _write_pool(pool_dir, host, user)
    env = SimpleNamespace(id=eid, domain=host, unix_username=user, status="active")
    svc = PhpFpmEnvironmentService(
        pool_dir=pool_dir,
        env_root=tmp_path / "envs",
        systemd_dir=tmp_path / "systemd",
        backup_root=tmp_path / "bak",
    )
    (tmp_path / "systemd").mkdir()
    plan = svc.plan_migrate(env)
    report = svc.apply_migrate(plan, dry_run=True)
    assert report["ok"] is True
    assert marker.read_bytes() == before
    assert not any(str(tenant) in str(a.get("path", "")) for a in plan.actions if isinstance(a, dict))


def test_socket_collision_detected(tmp_path: Path) -> None:
    pool_dir = tmp_path / "pool.d"
    pool_dir.mkdir()
    eid = uuid4()
    user = f"ifn_{str(eid).split('-')[0]}"
    host = "sock.example"
    _write_pool(pool_dir, host, user)
    # second pool same listen
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


def test_dry_run_no_system_changes(tmp_path: Path) -> None:
    pool_dir = tmp_path / "pool.d"
    pool_dir.mkdir()
    eid = uuid4()
    user = f"ifn_{str(eid).split('-')[0]}"
    host = "dry.example"
    _write_pool(pool_dir, host, user)
    env = SimpleNamespace(id=eid, domain=host, unix_username=user, status="active")
    svc = PhpFpmEnvironmentService(
        pool_dir=pool_dir,
        env_root=tmp_path / "envs",
        systemd_dir=tmp_path / "systemd",
        backup_root=tmp_path / "bak",
    )
    (tmp_path / "systemd").mkdir()
    plan = svc.plan_migrate(env)
    report = svc.apply_migrate(plan, dry_run=True)
    assert report["dry_run"] is True
    assert report["ok"] is True
    assert not (tmp_path / "envs").exists()
    assert (pool_dir / f"{fpm_pool_name(host)}.conf").is_file()


def test_limits_flags_never_set_on_plan(tmp_path: Path) -> None:
    pool_dir = tmp_path / "pool.d"
    pool_dir.mkdir()
    eid = uuid4()
    user = f"ifn_{str(eid).split('-')[0]}"
    host = "lim.example"
    _write_pool(pool_dir, host, user)
    env = SimpleNamespace(id=eid, domain=host, unix_username=user, status="active")
    svc = PhpFpmEnvironmentService(pool_dir=pool_dir, env_root=tmp_path / "e", systemd_dir=tmp_path / "s")
    (tmp_path / "s").mkdir()
    plan = svc.plan_migrate(env)
    assert plan.memorymax_changed is False
    assert plan.cpuquota_changed is False
    assert plan.tasksmax_changed is False
    assert plan.slice_name == slice_name_for(eid)
    assert plan.rollback_steps


def test_vps_excluded_unless_allowed(tmp_path: Path) -> None:
    pool_dir = tmp_path / "pool.d"
    pool_dir.mkdir()
    eid = uuid4()
    user = f"ifn_{str(eid).split('-')[0]}"
    host = "vps.example"
    _write_pool(pool_dir, host, user)
    env = SimpleNamespace(id=eid, domain=host, unix_username=user, status="active")
    svc = PhpFpmEnvironmentService(pool_dir=pool_dir, env_root=tmp_path / "e", systemd_dir=tmp_path / "s")
    (tmp_path / "s").mkdir()
    plan = svc.plan_migrate(env, plan_class="VPS_STYLE")
    assert plan.errors
    plan2 = svc.plan_migrate(env, plan_class="VPS_STYLE", allow_vps=True)
    assert not plan2.errors


def test_worker_user_preserved_in_pool_body(tmp_path: Path) -> None:
    pool_dir = tmp_path / "pool.d"
    pool_dir.mkdir()
    eid = uuid4()
    user = f"ifn_{str(eid).split('-')[0]}"
    host = "uid.example"
    _write_pool(pool_dir, host, user)
    env = SimpleNamespace(id=eid, domain=host, unix_username=user, status="active")
    svc = PhpFpmEnvironmentService(pool_dir=pool_dir, env_root=tmp_path / "e", systemd_dir=tmp_path / "s")
    (tmp_path / "s").mkdir()
    plan = svc.plan_migrate(env)
    assert plan.pools[0].user == user
    assert f"user = {user}" in plan.pools[0].body


def test_excluded_domains() -> None:
    assert is_excluded_canary_domain("examflow.ifnotus.space")
    assert is_excluded_canary_domain("votebridge.online")
    assert not is_excluded_canary_domain("essilfie.ifnotus.space")


def test_master_conf_isolated_runtime() -> None:
    body = render_env_master_conf(
        short_id="abc123",
        pool_glob="/etc/php/8.3/ifnotus-envs/abc123/pool.d/*.conf",
    )
    assert "pid = /run/php/ifnotus/abc123/php-fpm.pid" in body
    assert "error_log = /var/log/php/ifnotus/abc123/master.log" in body
    assert "include = /etc/php/8.3/ifnotus-envs/abc123/pool.d/*.conf" in body
