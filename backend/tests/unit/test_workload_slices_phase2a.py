"""Phase 2A workload slice hierarchy + env reparent tests."""

from __future__ import annotations

from pathlib import Path
from uuid import UUID, uuid4

from app.services.platform.systemd_env_slice import limits_from_env, slice_name_for
from app.services.platform.workload_slices import (
    CORE_SLICE,
    ENV_SLICE_PREFIX,
    PRODUCTS_SLICE,
    TENANTS_SLICE,
    WORKLOADS_ROOT,
    PHASE_2B_PHP_FPM_RECOMMENDATION,
    SFTP_ACCOUNTING_STATUS,
    WorkloadSliceReconciler,
    examflow_health_classification,
    hierarchy_slice_specs,
    legacy_slice_name_for,
    parse_legacy_slice_limits,
    render_env_slice_unit,
    render_hierarchy_slice_unit,
    render_service_slice_dropin,
    validate_child_limits_vs_parent,
)
from app.services.platform.resource_policy import (
    PlanView,
    classify_plan_resource_class,
    PlanResourceClass,
    resolve_normal_memory_target,
)


def test_hierarchy_names_are_valid_nested() -> None:
    assert WORKLOADS_ROOT == "ifnotus-workloads.slice"
    assert CORE_SLICE.startswith("ifnotus-workloads-")
    assert PRODUCTS_SLICE.startswith("ifnotus-workloads-")
    assert TENANTS_SLICE.startswith("ifnotus-workloads-")
    # Phase 3B-1: core/products nest under priority (encoded in slice names)
    assert CORE_SLICE == "ifnotus-workloads-priority-core.slice"
    assert PRODUCTS_SLICE == "ifnotus-workloads-priority-products.slice"


def test_hierarchy_unit_bodies_enable_accounting() -> None:
    for spec in hierarchy_slice_specs():
        body = render_hierarchy_slice_unit(spec)
        assert "MemoryAccounting=yes" in body
        assert "[Slice]" in body
        # Phase 3B-1: only priority may emit MemoryHigh; tenants keep MemoryMax=30G
        if spec.name == "ifnotus-workloads-priority.slice":
            assert "MemoryHigh=" in body
            assert "MemoryMax=" not in body
        elif spec.name == "ifnotus-workloads-tenants.slice":
            assert "MemoryMax=" in body
            assert "MemoryHigh=" not in body
        else:
            assert "MemoryHigh=" not in body
            assert "MemoryMax=" not in body


def test_core_and_product_dropins() -> None:
    core = render_service_slice_dropin(CORE_SLICE, comment="core")
    prod = render_service_slice_dropin(PRODUCTS_SLICE, comment="products")
    assert f"Slice={CORE_SLICE}" in core
    assert f"Slice={PRODUCTS_SLICE}" in prod


def test_env_slice_nested_under_tenants() -> None:
    eid = UUID("34a9a20e-d00d-4e3c-9d6e-7cf1dc58d19e")
    name = slice_name_for(eid)
    assert name.startswith(ENV_SLICE_PREFIX)
    assert name == "ifnotus-workloads-tenants-env-34a9a20e.slice"
    assert legacy_slice_name_for(eid) == "ifnotus-env-34a9a20e.slice"


def test_legacy_memory_limits_preserved_in_reparent_render() -> None:
    legacy = "\n".join(
        [
            "[Slice]",
            "CPUQuota=20%",
            "MemoryMax=201326592",
            "TasksMax=40",
            "",
        ]
    )
    parsed = parse_legacy_slice_limits(legacy)
    assert parsed["MemoryMax"] == "201326592"
    assert parsed["CPUQuota"] == "20%"
    assert parsed["TasksMax"] == "40"
    body = render_env_slice_unit(
        slice_name="ifnotus-workloads-tenants-env-95c8bba8.slice",
        cpu_quota=parsed["CPUQuota"],
        memory_max=parsed["MemoryMax"],
        tasks_max=parsed["TasksMax"],
    )
    assert "MemoryMax=201326592" in body
    assert "CPUQuota=20%" in body
    assert "TasksMax=40" in body


def test_plan_env_reparent_reads_legacy_file(tmp_path: Path) -> None:
    eid = uuid4()
    short = str(eid).split("-")[0]
    legacy = tmp_path / f"ifnotus-env-{short}.slice"
    legacy.write_text(
        "[Slice]\nCPUQuota=33%\nMemoryMax=123456789\nTasksMax=55\n",
        encoding="utf-8",
    )
    rec = WorkloadSliceReconciler(slice_dir=tmp_path)
    actions = rec.plan_env_reparent(environment_id=eid)
    write = next(a for a in actions if a.action == "write_slice")
    assert write.content is not None
    assert "MemoryMax=123456789" in write.content
    assert "CPUQuota=33%" in write.content
    assert "TasksMax=55" in write.content
    assert slice_name_for(eid) in write.path


def test_domain_names_do_not_affect_slice() -> None:
    eid = uuid4()
    a = slice_name_for(eid)
    b = slice_name_for(eid)
    assert a == b
    # domains are irrelevant to naming
    assert "example.com" not in a


def test_limits_from_env_uses_nested_slice_name() -> None:
    from types import SimpleNamespace

    env = SimpleNamespace(id=uuid4(), cpu_limit=0.2, ram_limit_gb=0.25)
    limits = limits_from_env(env)
    assert limits.slice_name == slice_name_for(env.id)
    assert limits.slice_name.startswith(ENV_SLICE_PREFIX)
    # Phase 2C: unknown/missing plan → conservative shared 2/12 GiB
    assert limits.memory_high_bytes == int(2 * 1024**3)
    assert limits.memory_max_bytes == int(12 * 1024**3)


def test_cron_and_node_wrap_use_nested_slice(monkeypatch) -> None:
    from types import SimpleNamespace

    from app.services.platform.systemd_env_slice import EnvironmentSliceService

    monkeypatch.setattr(
        "app.services.platform.systemd_env_slice.systemd_available",
        lambda: True,
    )
    monkeypatch.setattr(
        "app.services.platform.systemd_env_slice.shutil.which",
        lambda name: f"/usr/bin/{name}" if name in ("systemd-run", "systemctl") else None,
    )
    monkeypatch.setattr(
        EnvironmentSliceService,
        "ensure_slice",
        lambda self, env, plan=None: {"applied": True},
    )
    env = SimpleNamespace(id=uuid4(), cpu_limit=0.5, ram_limit_gb=0.5, unix_uid=1001)
    cmd = EnvironmentSliceService().wrap_command_in_slice("node server.js", env)
    assert f"--slice={slice_name_for(env.id)}" in cmd
    cron = EnvironmentSliceService().wrap_command_in_slice("php artisan schedule:run", env)
    assert f"--slice={slice_name_for(env.id)}" in cron


def test_examflow_not_healthy_as_root() -> None:
    bad = examflow_health_classification(user="root", slice_path="/system.slice/examflow")
    assert bad["healthy"] is False
    assert bad["code"] == "RESOURCE_ISOLATION_VIOLATION"
    good = examflow_health_classification(
        user="ifn_34a9a20e",
        slice_path="/ifnotus-workloads.slice/ifnotus-workloads-tenants.slice/"
        "ifnotus-workloads-tenants-env-34a9a20e.slice",
    )
    assert good["healthy"] is True


def test_php_fpm_phase_2b_recommendation_present() -> None:
    assert PHASE_2B_PHP_FPM_RECOMMENDATION["production_php_architecture_changed"] is True
    assert PHASE_2B_PHP_FPM_RECOMMENDATION["recommendation"] == "A-env"
    assert SFTP_ACCOUNTING_STATUS["changed"] is True
    assert SFTP_ACCOUNTING_STATUS["accounting_supported"] == "PHASE_2B4_PAM_ATTACH"


def test_vps_not_converted_by_slice_phase() -> None:
    vps = PlanView(slug="cloud-vps", name="Cloud VPS", price_monthly=170, ram_gb=8, storage_gb=100)
    assert classify_plan_resource_class(vps) == PlanResourceClass.VPS_STYLE
    assert resolve_normal_memory_target(vps) == 8.0


def test_child_parent_limit_validation() -> None:
    assert validate_child_limits_vs_parent(
        child_memory_max_bytes=201326592,
        parent_memory_max_bytes=None,
    ) == []
    errs = validate_child_limits_vs_parent(
        child_memory_max_bytes=40 * 1024**3,
        parent_memory_max_bytes=30 * 1024**3,
    )
    assert errs


def test_resolve_slice_cgroup_prefers_leaf(tmp_path, monkeypatch) -> None:
    from app.services.platform import workload_slices as ws

    root = tmp_path / "cgroup"
    # Parent ifnotus.slice must not win over leaf env slice.
    (root / "ifnotus.slice").mkdir(parents=True)
    leaf = (
        root
        / "ifnotus.slice"
        / "ifnotus-workloads.slice"
        / "ifnotus-workloads-tenants.slice"
        / "ifnotus-workloads-tenants-env.slice"
        / "ifnotus-workloads-tenants-env-34a9a20e.slice"
    )
    leaf.mkdir(parents=True)
    monkeypatch.setattr(ws, "_CGROUP_ROOT", root)

    class _Empty:
        stdout = ""

    monkeypatch.setattr(ws.subprocess, "run", lambda *a, **k: _Empty())
    got = ws.resolve_slice_cgroup_path("ifnotus-workloads-tenants-env-34a9a20e.slice")
    assert got == leaf
    assert ws.resolve_slice_cgroup_path("missing-env.slice") is None
    from app.services.platform.workload_slices import classify_process_hierarchy

    bad = classify_process_hierarchy(
        cgroup_path="0::/system.slice/ifnotus-api.service",
        expected="core",
    )
    assert bad["ok"] is False
    assert bad["escaped_workload_hierarchy"] is True
    assert bad["code"] == "WORKLOAD_OUTSIDE_EXPECTED_HIERARCHY"

    good = classify_process_hierarchy(
        cgroup_path=(
            "0::/ifnotus-workloads.slice/ifnotus-workloads-priority.slice/"
            "ifnotus-workloads-priority-core.slice/ifnotus-api.service"
        ),
        expected="core",
    )
    assert good["ok"] is True
    assert good["code"] is None

    infra = classify_process_hierarchy(
        cgroup_path="0::/system.slice/nginx.service",
        expected="infrastructure",
    )
    assert infra["ok"] is True
