"""Unit tests for Phase 1 centralized resource policy (no live system / DB mutation)."""

from __future__ import annotations

from copy import deepcopy

from app.services.platform.resource_policy import (
    HostResourcePolicy,
    IsolationSeverity,
    PlanCompatibility,
    PlanResourceClass,
    PlanView,
    StoragePoolSupport,
    WorkloadClass,
    bytes_to_gib,
    classify_plan_resource_class,
    classify_workload_unit,
    default_host_resource_policy,
    evaluate_plan_compatibility,
    gib_to_bytes,
    isolation_blockers,
    known_workload_units,
    resolve_burst_memory_limit,
    resolve_environment_resource_policy,
    resolve_normal_memory_target,
    resource_policy_status_report,
    supports_shared_storage_pool,
    validate_resource_policy,
)


def _plan(
    slug: str,
    *,
    price: float,
    ram: float = 0.25,
    storage: float = 2.0,
    name: str | None = None,
    features: dict | None = None,
) -> PlanView:
    return PlanView(
        slug=slug,
        name=name or slug,
        price_monthly=price,
        ram_gb=ram,
        storage_gb=storage,
        features=features or {},
    )


def test_ram_policy_totals_exactly_48() -> None:
    policy = default_host_resource_policy()
    assert policy.physical_ram_gb == 48
    assert policy.total_allocated_ram_gb() == 48
    assert (
        policy.os_safety_reserve_gb
        + policy.core_normal_gb
        + policy.tenant_normal_pool_gb
        + policy.emergency_pool_gb
        == 48
    )
    snap = policy.snapshot()
    assert snap["host_ram_gb"] == 48
    assert snap["tenant_storage_pool_gb"] == 140
    assert snap["core_storage_reserve_gb"] == 40


def test_invalid_totals_fail_validation() -> None:
    bad = HostResourcePolicy(
        physical_ram_gb=48,
        os_safety_reserve_gb=1,
        core_normal_gb=8,
        tenant_normal_pool_gb=30,
        emergency_pool_gb=20,  # over capacity
    )
    result = validate_resource_policy(bad)
    assert result.ok is False
    assert any(e.code == "ram_over_capacity" for e in result.errors)

    zero_pool = HostResourcePolicy(tenant_normal_pool_gb=0)
    assert validate_resource_policy(zero_pool).ok is False


def test_shared_plan_below_100_resolves_to_2_gib() -> None:
    plan = _plan("personal-launch", price=25, ram=0.1875, storage=2)
    assert classify_plan_resource_class(plan) == PlanResourceClass.SHARED_LOW
    assert resolve_normal_memory_target(plan) == 2.0


def test_shared_plan_100_plus_resolves_to_6_gib() -> None:
    plan = _plan("student-elite", price=100, ram=0.75, storage=5)
    assert classify_plan_resource_class(plan) == PlanResourceClass.SHARED_STANDARD
    assert resolve_normal_memory_target(plan) == 6.0

    business = _plan("business-hosting", price=150, ram=1.0, storage=8)
    assert resolve_normal_memory_target(business) == 6.0


def test_shared_burst_max_is_12_gib() -> None:
    plan = _plan("student-pro", price=70, ram=0.5)
    burst, dedicated = resolve_burst_memory_limit(plan)
    assert dedicated is False
    assert burst == 12.0


def test_vps_vds_not_blindly_converted_to_shared_targets() -> None:
    vps = _plan("cloud-vps", price=170, ram=8.0, storage=100)
    vds = _plan("cloud-vds", price=750, ram=24.0, storage=180)

    assert classify_plan_resource_class(vps) == PlanResourceClass.VPS_STYLE
    assert classify_plan_resource_class(vds) == PlanResourceClass.VDS_STYLE

    assert resolve_normal_memory_target(vps) == 8.0
    assert resolve_normal_memory_target(vds) == 24.0

    burst_vps, ded_vps = resolve_burst_memory_limit(vps)
    burst_vds, ded_vds = resolve_burst_memory_limit(vds)
    assert ded_vps is True and ded_vds is True
    assert burst_vps == 8.0
    assert burst_vds == 24.0
    assert burst_vps != 12.0
    assert burst_vds != 12.0


def test_custom_domain_does_not_alter_environment_policy() -> None:
    plan = _plan("personal-launch", price=25, ram=0.1875)
    with_sub = resolve_environment_resource_policy(
        plan=plan,
        environment_id="env-1",
        domain_names=["customer.ifnotus.space"],
    )
    with_custom = resolve_environment_resource_policy(
        plan=plan,
        environment_id="env-1",
        domain_names=["customerdomain.com"],
    )
    assert with_sub.memory.normal_target_ram_gb == with_custom.memory.normal_target_ram_gb == 2.0
    assert with_sub.memory.burst_ceiling_ram_gb == with_custom.memory.burst_ceiling_ram_gb
    assert with_sub.storage.plan_storage_quota_gb == with_custom.storage.plan_storage_quota_gb


def test_multiple_domains_do_not_multiply_ram() -> None:
    plan = _plan("business-hosting", price=150, ram=1.0, storage=8)
    one = resolve_environment_resource_policy(
        plan=plan, environment_id="env-x", domain_names=["a.example.com"]
    )
    many = resolve_environment_resource_policy(
        plan=plan,
        environment_id="env-x",
        domain_names=[f"d{i}.example.com" for i in range(20)],
    )
    assert one.domain_count == 1
    assert many.domain_count == 20
    assert one.memory.normal_target_ram_gb == many.memory.normal_target_ram_gb == 6.0
    assert one.memory.burst_ceiling_ram_gb == many.memory.burst_ceiling_ram_gb == 12.0
    assert one.storage.plan_storage_quota_gb == many.storage.plan_storage_quota_gb == 8.0


def test_storage_shared_pool_and_core_reserve() -> None:
    policy = default_host_resource_policy()
    assert policy.tenant_storage_pool_gb == 140
    assert policy.core_storage_reserve_gb == 40


def test_cloud_vds_180_flagged_dedicated() -> None:
    vds = _plan("cloud-vds", price=750, ram=24.0, storage=180)
    assert evaluate_plan_compatibility(vds) == PlanCompatibility.DEDICATED_POLICY_REQUIRED
    assert supports_shared_storage_pool(vds) == StoragePoolSupport.REQUIRES_DEDICATED_POLICY


def test_votebridge_quizsnap_first_party() -> None:
    vb = classify_workload_unit("votebridge")
    qs = classify_workload_unit("quizsnap.service")
    assert vb is not None and vb.workload_class == WorkloadClass.FIRST_PARTY_PRODUCT
    assert qs is not None and qs.workload_class == WorkloadClass.FIRST_PARTY_PRODUCT


def test_ifnotus_api_worker_platform_core() -> None:
    api = classify_workload_unit("ifnotus-api.service")
    worker = classify_workload_unit("ifnotus-worker")
    assert api is not None and api.workload_class == WorkloadClass.PLATFORM_CORE
    assert worker is not None and worker.workload_class == WorkloadClass.PLATFORM_CORE


def test_examflow_isolation_violation() -> None:
    unit = classify_workload_unit("examflow-ifnotus.service")
    assert unit is not None
    assert unit.workload_class == WorkloadClass.UNCLASSIFIED
    assert unit.isolation_violation is True
    blockers = isolation_blockers()
    assert any(b.code == "RESOURCE_ISOLATION_VIOLATION" for b in blockers)
    assert any(b.severity == IsolationSeverity.BLOCKER for b in blockers)


def test_live_plan_ram_values_not_mutated() -> None:
    """Resolver must not mutate caller plan objects (stand-in for HostingPlan rows)."""
    plan = _plan("personal-launch", price=25, ram=0.1875, storage=2)
    before = deepcopy(plan)
    _ = resolve_normal_memory_target(plan)
    _ = resolve_burst_memory_limit(plan)
    _ = resolve_environment_resource_policy(
        plan=plan, domain_names=["a.ifnotus.space", "b.com"]
    )
    assert plan.ram_gb == before.ram_gb == 0.1875
    assert plan.storage_gb == before.storage_gb == 2.0
    assert plan.price_monthly == before.price_monthly


def test_php_fpm_requires_tenant_worker_assignment() -> None:
    php = classify_workload_unit("php-fpm-master")
    assert php is not None
    assert php.workload_class == WorkloadClass.SYSTEM_INFRASTRUCTURE
    assert php.requires_tenant_worker_assignment is True


def test_gib_helpers_binary() -> None:
    assert gib_to_bytes(1) == 1024**3
    assert bytes_to_gib(gib_to_bytes(2)) == 2.0


def test_burst_exceeds_pool_warns_but_default_ok() -> None:
    policy = default_host_resource_policy()
    result = validate_resource_policy(policy)
    assert result.ok is True
    # Default: burst 12 < tenant pool 30 — no warning required.
    assert not any(w.code == "burst_exceeds_tenant_pool" for w in result.warnings)

    # If burst were raised above the parent pool, warn (emergency borrowing needed later).
    high_burst = HostResourcePolicy(tenant_individual_burst_max_gb=40)
    warned = validate_resource_policy(high_burst)
    assert warned.ok is True
    assert any(w.code == "burst_exceeds_tenant_pool" for w in warned.warnings)


def test_compatible_shared_plans() -> None:
    for slug, price, ram, storage in [
        ("personal-launch", 25, 0.1875, 2),
        ("student-starter", 30, 0.25, 2),
        ("student-developer", 55, 0.375, 8),
        ("student-pro", 70, 0.5, 4),
        ("student-elite", 100, 0.75, 5),
        ("business-hosting", 150, 1.0, 8),
        ("macho-power", 300, 2.0, 15),
    ]:
        plan = _plan(slug, price=price, ram=ram, storage=storage)
        assert evaluate_plan_compatibility(plan) == PlanCompatibility.COMPATIBLE_SHARED


def test_status_report_includes_known_workloads() -> None:
    report = resource_policy_status_report()
    assert report["policy"]["host_ram_gb"] == 48
    keys = {u["key"] for u in report["workloads"]["platform_core"]}
    assert "ifnotus-api" in keys
    assert any(u["isolation_violation"] for u in report["workloads"]["isolation_violations"])
    assert len(known_workload_units()) >= 8
