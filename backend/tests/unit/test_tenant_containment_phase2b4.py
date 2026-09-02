"""Phase 2B-4 tests: legacy www-data containment, SFTP mapping, containment status."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

from app.services.platform.php_fpm_environment import PhpFpmEnvironmentService, fpm_pool_name
from app.services.platform.tenant_containment import (
    resolve_slice_for_unix_user,
    slice_from_unix_username,
)


def _write_pool(pool_dir: Path, hostname: str, user: str) -> Path:
    name = fpm_pool_name(hostname)
    body = "\n".join(
        [
            f"[{name}]",
            f"user = {user}",
            f"group = {user}",
            f"listen = /run/php/{name}.sock",
            "pm = ondemand",
            "pm.max_children = 2",
            "",
        ]
    )
    path = pool_dir / f"{name}.conf"
    path.write_text(body, encoding="utf-8")
    return path


def test_legacy_www_data_allowed_without_identity_change(tmp_path: Path) -> None:
    pool_dir = tmp_path / "pool.d"
    pool_dir.mkdir()
    eid = uuid4()
    user = f"ifn_{str(eid).split('-')[0]}"
    host = "legacy.example"
    _write_pool(pool_dir, host, "www-data")
    env = SimpleNamespace(id=eid, domain=host, unix_username=user, status="active")
    svc = PhpFpmEnvironmentService(pool_dir=pool_dir, env_root=tmp_path / "e", systemd_dir=tmp_path / "s")
    (tmp_path / "s").mkdir()
    blocked = svc.plan_migrate(env, require_tenant_unix_user=True)
    assert blocked.errors
    plan = svc.plan_migrate(env, require_tenant_unix_user=True, allow_legacy_www_data=True)
    assert not plan.errors
    assert any("LEGACY_IDENTITY_DEBT" in w for w in plan.warnings)
    assert plan.pools[0].user == "www-data"


def test_mixed_user_same_env_one_master(tmp_path: Path) -> None:
    pool_dir = tmp_path / "pool.d"
    pool_dir.mkdir()
    eid = uuid4()
    user = f"ifn_{str(eid).split('-')[0]}"
    _write_pool(pool_dir, "a.example", user)
    _write_pool(pool_dir, "www.a.example", "www-data")
    env = SimpleNamespace(
        id=eid,
        domain="a.example",
        unix_username=user,
        status="active",
        domains=[SimpleNamespace(domain_name="www.a.example")],
    )
    svc = PhpFpmEnvironmentService(pool_dir=pool_dir, env_root=tmp_path / "e", systemd_dir=tmp_path / "s")
    (tmp_path / "s").mkdir()
    plan = svc.plan_migrate(env, require_tenant_unix_user=True, allow_legacy_www_data=True)
    assert not plan.errors
    assert len(plan.pools) == 2
    assert plan.service_name.count("@") == 1


def test_cross_env_mixed_pool_rejected(tmp_path: Path) -> None:
    pool_dir = tmp_path / "pool.d"
    pool_dir.mkdir()
    eid = uuid4()
    user = f"ifn_{str(eid).split('-')[0]}"
    host = "x.example"
    _write_pool(pool_dir, host, "ifn_otherenv")
    env = SimpleNamespace(id=eid, domain=host, unix_username=user, status="active")
    svc = PhpFpmEnvironmentService(pool_dir=pool_dir, env_root=tmp_path / "e", systemd_dir=tmp_path / "s")
    (tmp_path / "s").mkdir()
    plan = svc.plan_migrate(env, require_tenant_unix_user=True, allow_legacy_www_data=True)
    assert any("CROSS_TENANT" in e for e in plan.errors)


def test_root_pool_rejected(tmp_path: Path) -> None:
    pool_dir = tmp_path / "pool.d"
    pool_dir.mkdir()
    eid = uuid4()
    user = f"ifn_{str(eid).split('-')[0]}"
    host = "root.example"
    _write_pool(pool_dir, host, "root")
    env = SimpleNamespace(id=eid, domain=host, unix_username=user, status="active")
    svc = PhpFpmEnvironmentService(pool_dir=pool_dir, env_root=tmp_path / "e", systemd_dir=tmp_path / "s")
    (tmp_path / "s").mkdir()
    plan = svc.plan_migrate(env, require_tenant_unix_user=True, allow_legacy_www_data=True)
    assert any("ROOT_PHP_POOL_SECURITY_VIOLATION" in e for e in plan.errors)


def test_sftp_username_to_slice_mapping() -> None:
    assert slice_from_unix_username("ifn_abefc27e") == "ifnotus-workloads-tenants-env-abefc27e.slice"
    assert slice_from_unix_username("root") is None
    assert slice_from_unix_username("ifn_abefc27e/../x") is None


def test_sftp_command_injection_resistance(tmp_path: Path) -> None:
    bad = resolve_slice_for_unix_user("ifn_abc; rm -rf /", map_path=tmp_path / "missing.json")
    assert bad["ok"] is False
    bad2 = resolve_slice_for_unix_user("ifn_abc/../../etc", map_path=tmp_path / "m.json")
    assert bad2["ok"] is False


def test_sftp_unknown_user_rejection(tmp_path: Path) -> None:
    mp = tmp_path / "map.json"
    mp.write_text('{"ifn_known": {"slice": "ifnotus-workloads-tenants-env-known.slice"}}', encoding="utf-8")
    got = resolve_slice_for_unix_user("ifn_unknown1", map_path=mp)
    assert got["ok"] is False
    assert got["error"] == "unknown_user"
    ok = resolve_slice_for_unix_user("ifn_known", map_path=mp)
    assert ok["ok"] is True
    assert ok["slice"].endswith("known.slice")


def test_sftp_attach_runs_as_root_into_leaf_scope() -> None:
    from app.services.platform.tenant_containment import ensure_pam_sshd_attach, render_sftp_attach_script

    script = render_sftp_attach_script()
    assert "sftp-sessions" in script
    assert "sleep infinity" not in script
    assert "ForceCommand/internal-sftp" in script
    assert ") >/dev/null 2>&1 &" in script
    dry = ensure_pam_sshd_attach(dry_run=True)
    assert dry["ok"]
    pam_line = dry["actions"][0]["would_ensure_pam"]
    assert "pam_exec.so" in pam_line
    assert " seteuid " not in f" {pam_line} "


def test_no_customer_fs_mutation_on_legacy_plan(tmp_path: Path) -> None:
    pool_dir = tmp_path / "pool.d"
    pool_dir.mkdir()
    tenant = tmp_path / "public_html"
    tenant.mkdir()
    marker = tenant / "index.php"
    marker.write_text("keep", encoding="utf-8")
    before = marker.read_bytes()
    eid = uuid4()
    user = f"ifn_{str(eid).split('-')[0]}"
    host = "fs.example"
    _write_pool(pool_dir, host, "www-data")
    env = SimpleNamespace(id=eid, domain=host, unix_username=user, status="active")
    svc = PhpFpmEnvironmentService(
        pool_dir=pool_dir, env_root=tmp_path / "e", systemd_dir=tmp_path / "s", backup_root=tmp_path / "b"
    )
    (tmp_path / "s").mkdir()
    plan = svc.plan_migrate(env, require_tenant_unix_user=True, allow_legacy_www_data=True)
    report = svc.apply_migrate(plan, dry_run=True)
    assert report["ok"]
    assert marker.read_bytes() == before
