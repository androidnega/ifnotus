"""Phase 2C memory policy unit tests."""

from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

from app.services.platform.memory_policy import (
    DRIFT_DEDICATED_POLICY_REQUIRED,
    DRIFT_LEGACY_MEMORY_MAX,
    DRIFT_PLAN_CLASSIFICATION_REVIEW,
    DRIFT_POLICY_OK,
    USAGE_BURSTING,
    USAGE_NEAR_HARD_LIMIT,
    USAGE_NORMAL,
    USAGE_OOM,
    classify_usage_band,
    detect_drift,
    gib_to_bytes,
    render_env_slice_unit_with_high,
    resolve_shared_memory_targets,
)
from app.services.platform.resource_policy import PlanResourceClass, PlanView, default_host_resource_policy
from app.services.platform.systemd_env_slice import limits_from_env
from app.services.platform.workload_slices import TENANTS_SLICE, validate_child_limits_vs_parent


def _plan(slug: str, *, price: float, ram: float = 0.25) -> PlanView:
    return PlanView(slug=slug, name=slug, price_monthly=price, ram_gb=ram, storage_gb=2.0, features={})


def test_shared_low_memory_high_2_gib() -> None:
    t = resolve_shared_memory_targets(_plan("personal", price=25))
    assert t.plan_class == PlanResourceClass.SHARED_LOW
    assert t.memory_high_gib == 2.0
    assert t.memory_high_bytes == gib_to_bytes(2)


def test_shared_standard_memory_high_6_gib() -> None:
    t = resolve_shared_memory_targets(_plan("elite", price=100))
    assert t.plan_class == PlanResourceClass.SHARED_STANDARD
    assert t.memory_high_gib == 6.0


def test_shared_memory_max_12_gib() -> None:
    for price in (25, 100, 150):
        t = resolve_shared_memory_targets(_plan("x", price=price))
        assert t.memory_max_gib == 12.0
        assert t.memory_max_bytes == gib_to_bytes(12)


def test_no_memory_min_in_unit_body() -> None:
    body = render_env_slice_unit_with_high(
        slice_name="ifnotus-workloads-tenants-env-abc.slice",
        cpu_quota="25%",
        memory_high=str(gib_to_bytes(2)),
        memory_max=str(gib_to_bytes(12)),
        tasks_max="40",
    )
    assert "MemoryHigh=" in body
    assert "MemoryMax=" in body
    assert "MemoryMin=" not in body


def test_parent_target_is_30_gib() -> None:
    policy = default_host_resource_policy()
    assert policy.tenant_normal_pool_gb == 30.0
    assert TENANTS_SLICE == "ifnotus-workloads-tenants.slice"
    assert gib_to_bytes(30) == 30 * 1024**3


def test_domain_count_does_not_alter_memory() -> None:
    t1 = resolve_shared_memory_targets(_plan("a", price=30))
    t2 = resolve_shared_memory_targets(_plan("a", price=30))
    assert t1.memory_high_bytes == t2.memory_high_bytes
    assert t1.memory_max_bytes == t2.memory_max_bytes


def test_vps_vds_excluded_from_shared() -> None:
    vps = resolve_shared_memory_targets(_plan("cloud-vps", price=170, ram=8))
    assert DRIFT_DEDICATED_POLICY_REQUIRED in vps.warnings
    assert vps.plan_class == PlanResourceClass.VPS_STYLE
    vds = resolve_shared_memory_targets(_plan("cloud-vds", price=750, ram=24))
    assert vds.plan_class == PlanResourceClass.VDS_STYLE


def test_unknown_plan_conservative_2_gib() -> None:
    t = resolve_shared_memory_targets(None)
    assert t.memory_high_gib == 2.0
    assert t.memory_max_gib == 12.0
    assert DRIFT_PLAN_CLASSIFICATION_REVIEW in t.warnings
    assert t.source == "unknown_conservative"


def test_limits_from_env_uses_policy_not_legacy_ram() -> None:
    env = SimpleNamespace(id=uuid4(), cpu_limit=0.25, ram_limit_gb=0.25)
    plan = SimpleNamespace(
        slug="student-pro",
        name="Student Pro",
        price_monthly=30,
        ram_gb=0.25,
        storage_gb=2,
        features={},
    )
    limits = limits_from_env(env, plan)
    assert limits.memory_high_bytes == gib_to_bytes(2)
    assert limits.memory_max_bytes == gib_to_bytes(12)
    assert limits.cpu_quota_percent == 25


def test_legacy_drift_detection() -> None:
    targets = resolve_shared_memory_targets(_plan("x", price=25))
    live = {
        "unit_exists": True,
        "memory_high_bytes": None,
        "memory_max_bytes": 268435456,
    }
    assert detect_drift(live=live, targets=targets, env_status="active") == DRIFT_LEGACY_MEMORY_MAX
    live_ok = {
        "unit_exists": True,
        "memory_high_bytes": targets.memory_high_bytes,
        "memory_max_bytes": targets.memory_max_bytes,
    }
    assert detect_drift(live=live_ok, targets=targets, env_status="active") == DRIFT_POLICY_OK


def test_usage_band_semantics() -> None:
    high = gib_to_bytes(2)
    mx = gib_to_bytes(12)
    assert classify_usage_band(current_bytes=100_000_000, memory_high_bytes=high, memory_max_bytes=mx) == USAGE_NORMAL
    assert classify_usage_band(current_bytes=high + 1, memory_high_bytes=high, memory_max_bytes=mx) == USAGE_BURSTING
    assert (
        classify_usage_band(current_bytes=int(mx * 0.95), memory_high_bytes=high, memory_max_bytes=mx)
        == USAGE_NEAR_HARD_LIMIT
    )
    assert classify_usage_band(current_bytes=1, memory_high_bytes=high, memory_max_bytes=mx, oom_kill=1) == USAGE_OOM


def test_child_under_parent_30() -> None:
    errs = validate_child_limits_vs_parent(
        child_memory_max_bytes=gib_to_bytes(12),
        parent_memory_max_bytes=gib_to_bytes(30),
    )
    assert errs == []


def test_cpu_quota_preserved_in_limits() -> None:
    env = SimpleNamespace(id=uuid4(), cpu_limit=0.5, ram_limit_gb=0.25)
    plan = SimpleNamespace(
        slug="p", name="p", price_monthly=150, ram_gb=1.0, storage_gb=5, features={}
    )
    limits = limits_from_env(env, plan)
    assert limits.cpu_quota_percent == 50
    assert limits.memory_high_bytes == gib_to_bytes(6)
