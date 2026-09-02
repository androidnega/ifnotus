"""Phase 2B-3 unit tests for PHP-FPM mass rollout orchestration."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

from app.services.platform.php_fpm_environment import (
    DISABLED_SUFFIX,
    PhpFpmEnvironmentService,
    fpm_pool_name,
)
from app.services.platform.php_fpm_rollout import (
    CLASS_ELIGIBLE,
    CLASS_POOL_MISMATCH,
    CLASS_VPS,
    IDENTITY_CROSS,
    IDENTITY_LEGACY_WWW,
    IDENTITY_ROOT,
    IDENTITY_SAFE_IFN,
    PhpFpmRolloutCheckpoint,
    PhpFpmRolloutService,
    classify_pool_identity,
    recommended_tasksmax,
    tasksmax_warning,
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


def test_pool_identity_classification() -> None:
    assert classify_pool_identity(expected_unix="ifn_abc", pool_user="ifn_abc") == IDENTITY_SAFE_IFN
    assert classify_pool_identity(expected_unix="ifn_abc", pool_user="www-data") == IDENTITY_LEGACY_WWW
    assert classify_pool_identity(expected_unix="ifn_abc", pool_user="root") == IDENTITY_ROOT
    assert classify_pool_identity(expected_unix="ifn_abc", pool_user="ifn_other") == IDENTITY_CROSS


def test_www_data_rejected_for_rollout(tmp_path: Path) -> None:
    pool_dir = tmp_path / "pool.d"
    pool_dir.mkdir()
    eid = uuid4()
    user = f"ifn_{str(eid).split('-')[0]}"
    host = "wwwdata.example"
    _write_pool(pool_dir, host, "www-data")
    env = SimpleNamespace(id=eid, domain=host, unix_username=user, status="active")
    fpm = PhpFpmEnvironmentService(pool_dir=pool_dir, env_root=tmp_path / "e", systemd_dir=tmp_path / "s")
    (tmp_path / "s").mkdir()
    plan = fpm.plan_migrate(env, require_tenant_unix_user=True)
    assert plan.errors
    assert any("LEGACY_SHARED_USER" in e or "www-data" in e for e in plan.errors)


def test_root_pool_rejected(tmp_path: Path) -> None:
    pool_dir = tmp_path / "pool.d"
    pool_dir.mkdir()
    eid = uuid4()
    user = f"ifn_{str(eid).split('-')[0]}"
    host = "root.example"
    _write_pool(pool_dir, host, "root")
    env = SimpleNamespace(id=eid, domain=host, unix_username=user, status="active")
    fpm = PhpFpmEnvironmentService(pool_dir=pool_dir, env_root=tmp_path / "e", systemd_dir=tmp_path / "s")
    (tmp_path / "s").mkdir()
    plan = fpm.plan_migrate(env, require_tenant_unix_user=True)
    assert any("ROOT_PHP_POOL" in e for e in plan.errors)


def test_cross_tenant_rejected(tmp_path: Path) -> None:
    pool_dir = tmp_path / "pool.d"
    pool_dir.mkdir()
    eid = uuid4()
    user = f"ifn_{str(eid).split('-')[0]}"
    host = "x.example"
    _write_pool(pool_dir, host, "ifn_someoneelse")
    env = SimpleNamespace(id=eid, domain=host, unix_username=user, status="active")
    fpm = PhpFpmEnvironmentService(pool_dir=pool_dir, env_root=tmp_path / "e", systemd_dir=tmp_path / "s")
    (tmp_path / "s").mkdir()
    plan = fpm.plan_migrate(env, require_tenant_unix_user=True)
    assert any("CROSS_TENANT" in e for e in plan.errors)


def test_safe_ifn_accepted(tmp_path: Path) -> None:
    pool_dir = tmp_path / "pool.d"
    pool_dir.mkdir()
    eid = uuid4()
    user = f"ifn_{str(eid).split('-')[0]}"
    host = "ok.example"
    _write_pool(pool_dir, host, user)
    env = SimpleNamespace(id=eid, domain=host, unix_username=user, status="active")
    fpm = PhpFpmEnvironmentService(pool_dir=pool_dir, env_root=tmp_path / "e", systemd_dir=tmp_path / "s")
    (tmp_path / "s").mkdir()
    plan = fpm.plan_migrate(env, require_tenant_unix_user=True)
    assert not plan.errors


def test_vps_excluded(tmp_path: Path) -> None:
    pool_dir = tmp_path / "pool.d"
    pool_dir.mkdir()
    eid = uuid4()
    user = f"ifn_{str(eid).split('-')[0]}"
    host = "vps.example"
    _write_pool(pool_dir, host, user)
    env = SimpleNamespace(id=eid, domain=host, unix_username=user, status="active")
    fpm = PhpFpmEnvironmentService(pool_dir=pool_dir, env_root=tmp_path / "e", systemd_dir=tmp_path / "s")
    (tmp_path / "s").mkdir()
    rollout = PhpFpmRolloutService(fpm=fpm, checkpoint=PhpFpmRolloutCheckpoint(tmp_path / "state.json"), pool_dir=pool_dir)
    row = rollout.classify_environment(env, plan_slug="cloud-vps")
    assert row.classification == CLASS_VPS


def test_checkpoint_resume(tmp_path: Path) -> None:
    cp = PhpFpmRolloutCheckpoint(tmp_path / "ck.json")
    state = cp.load()
    cp.set_env(state, "e1", status="VERIFIED", short_id="aaaa")
    cp.save(state)
    loaded = cp.load()
    assert loaded["environments"]["e1"]["status"] == "VERIFIED"


def test_select_batch_skips_verified(tmp_path: Path) -> None:
    pool_dir = tmp_path / "pool.d"
    pool_dir.mkdir()
    fpm = PhpFpmEnvironmentService(pool_dir=pool_dir, env_root=tmp_path / "e", systemd_dir=tmp_path / "s")
    (tmp_path / "s").mkdir()
    cp = PhpFpmRolloutCheckpoint(tmp_path / "ck.json")
    svc = PhpFpmRolloutService(fpm=fpm, checkpoint=cp, pool_dir=pool_dir)
    rows = []
    for _ in range(3):
        eid = uuid4()
        user = f"ifn_{str(eid).split('-')[0]}"
        host = f"{str(eid).split('-')[0]}.example"
        _write_pool(pool_dir, host, user)
        env = SimpleNamespace(id=eid, domain=host, unix_username=user, status="active")
        row = svc.classify_environment(env)
        assert row.classification == CLASS_ELIGIBLE
        rows.append(row)
    state = cp.load()
    cp.set_env(state, rows[0].environment_id, status="VERIFIED")
    cp.save(state)
    batch = svc.select_batch(rows, batch_size=5, state=state)
    assert rows[0].environment_id not in {r.environment_id for r in batch}
    assert len(batch) == 2


def test_tasksmax_warning_and_recommendation() -> None:
    assert tasksmax_warning(tasks_max=32, theoretical_peak=30) == "TASKSMAX_WARNING"
    assert tasksmax_warning(tasks_max=40, theoretical_peak=7) is None
    assert recommended_tasksmax(pm_max_children=4) >= 15


def test_multi_domain_one_master(tmp_path: Path) -> None:
    pool_dir = tmp_path / "pool.d"
    pool_dir.mkdir()
    eid = uuid4()
    user = f"ifn_{str(eid).split('-')[0]}"
    for h in ("a.example", "b.example"):
        _write_pool(pool_dir, h, user)
    env = SimpleNamespace(
        id=eid,
        domain="a.example",
        unix_username=user,
        status="active",
        domains=[SimpleNamespace(domain_name="b.example")],
    )
    fpm = PhpFpmEnvironmentService(pool_dir=pool_dir, env_root=tmp_path / "e", systemd_dir=tmp_path / "s")
    (tmp_path / "s").mkdir()
    plan = fpm.plan_migrate(env, require_tenant_unix_user=True)
    assert len(plan.pools) == 2
    assert plan.service_name.count("@") == 1


def test_dry_run_no_fs_mutation(tmp_path: Path) -> None:
    pool_dir = tmp_path / "pool.d"
    pool_dir.mkdir()
    tenant = tmp_path / "public_html"
    tenant.mkdir()
    marker = tenant / "index.php"
    marker.write_text("x", encoding="utf-8")
    before = marker.read_bytes()
    eid = uuid4()
    user = f"ifn_{str(eid).split('-')[0]}"
    host = "dry.example"
    _write_pool(pool_dir, host, user)
    env = SimpleNamespace(id=eid, domain=host, unix_username=user, status="active")
    fpm = PhpFpmEnvironmentService(
        pool_dir=pool_dir, env_root=tmp_path / "e", systemd_dir=tmp_path / "s", backup_root=tmp_path / "b"
    )
    (tmp_path / "s").mkdir()
    svc = PhpFpmRolloutService(
        fpm=fpm, checkpoint=PhpFpmRolloutCheckpoint(tmp_path / "ck.json"), pool_dir=pool_dir
    )

    class _Ok:
        returncode = 0
        stdout = "inactive\n"
        stderr = ""

    svc._systemctl = lambda *a, **k: _Ok()  # type: ignore[method-assign]
    svc.http_status = lambda host: "200"  # type: ignore[method-assign]
    result = svc.migrate_one(env, dry_run=True)
    assert result["ok"] is True
    assert marker.read_bytes() == before
    assert (pool_dir / f"{fpm_pool_name(host)}.conf").is_file()


def test_duplicate_pool_still_errors(tmp_path: Path) -> None:
    pool_dir = tmp_path / "pool.d"
    pool_dir.mkdir()
    eid = uuid4()
    user = f"ifn_{str(eid).split('-')[0]}"
    host = "dup.example"
    _write_pool(pool_dir, host, user)
    other = pool_dir / "other.conf"
    other.write_text(
        f"[other]\nuser = {user}\ngroup = {user}\nlisten = /run/php/{fpm_pool_name(host)}.sock\n",
        encoding="utf-8",
    )
    env = SimpleNamespace(id=eid, domain=host, unix_username=user, status="active")
    fpm = PhpFpmEnvironmentService(pool_dir=pool_dir, env_root=tmp_path / "e", systemd_dir=tmp_path / "s")
    (tmp_path / "s").mkdir()
    plan = fpm.plan_migrate(env, require_tenant_unix_user=True)
    assert any("socket collision" in e for e in plan.errors)


def test_mismatch_classification(tmp_path: Path) -> None:
    pool_dir = tmp_path / "pool.d"
    pool_dir.mkdir()
    eid = uuid4()
    user = f"ifn_{str(eid).split('-')[0]}"
    host = "mm.example"
    _write_pool(pool_dir, host, "www-data")
    env = SimpleNamespace(id=eid, domain=host, unix_username=user, status="active")
    fpm = PhpFpmEnvironmentService(pool_dir=pool_dir, env_root=tmp_path / "e", systemd_dir=tmp_path / "s")
    (tmp_path / "s").mkdir()
    svc = PhpFpmRolloutService(
        fpm=fpm, checkpoint=PhpFpmRolloutCheckpoint(tmp_path / "ck.json"), pool_dir=pool_dir
    )

    class _Ok:
        returncode = 0
        stdout = "inactive\n"
        stderr = ""

    svc._systemctl = lambda *a, **k: _Ok()  # type: ignore[method-assign]
    row = svc.classify_environment(env)
    assert row.classification == CLASS_POOL_MISMATCH
