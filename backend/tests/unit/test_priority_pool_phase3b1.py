"""Phase 3B-1 priority pool + host safety unit tests."""

from __future__ import annotations

from app.services.platform.host_safety import (
    EMERGENCY_BUDGET_MAX_GIB,
    HOST_MEMAVAILABLE_SAFETY_FLOOR_GIB,
    STATUS_CRITICAL_PRESSURE,
    STATUS_DENY_BURST,
    STATUS_REDUCED_HEADROOM,
    STATUS_SAFE,
    classify_host_safety_status,
    safe_emergency_capacity_gib,
)
from app.services.platform.resource_policy import gib_to_bytes
from app.services.platform.workload_slices import (
    ADDITIONAL_FIRST_PARTY_UNITS,
    CORE_SLICE,
    FIRST_PARTY_UNITS,
    PLATFORM_CORE_UNITS,
    PRIORITY_CORE_SLICE,
    PRIORITY_MEMORY_HIGH,
    PRIORITY_MEMORY_HIGH_BYTES,
    PRIORITY_PRODUCTS_SLICE,
    PRIORITY_SLICE,
    PRODUCTS_SLICE,
    TENANTS_SLICE,
    WORKLOADS_ROOT,
    classify_process_hierarchy,
    hierarchy_slice_specs,
    render_hierarchy_slice_unit,
    render_service_slice_dropin,
)


def test_priority_hierarchy_names_valid() -> None:
    assert PRIORITY_SLICE.startswith("ifnotus-workloads-")
    assert PRIORITY_CORE_SLICE.startswith("ifnotus-workloads-priority-")
    assert PRIORITY_PRODUCTS_SLICE.startswith("ifnotus-workloads-priority-")
    assert CORE_SLICE == PRIORITY_CORE_SLICE
    assert PRODUCTS_SLICE == PRIORITY_PRODUCTS_SLICE
    names = {s.name for s in hierarchy_slice_specs()}
    assert WORKLOADS_ROOT in names
    assert PRIORITY_SLICE in names
    assert PRIORITY_CORE_SLICE in names
    assert PRIORITY_PRODUCTS_SLICE in names
    assert TENANTS_SLICE in names


def test_core_and_products_map_under_priority() -> None:
    assert all(u.endswith(".service") for u in PLATFORM_CORE_UNITS)
    assert "ifnotus-api.service" in PLATFORM_CORE_UNITS
    assert "votebridge.service" in FIRST_PARTY_UNITS
    assert "quizsnap.service" in FIRST_PARTY_UNITS
    core = render_service_slice_dropin(PRIORITY_CORE_SLICE, comment="core")
    prod = render_service_slice_dropin(PRIORITY_PRODUCTS_SLICE, comment="prod")
    assert f"Slice={PRIORITY_CORE_SLICE}" in core
    assert f"Slice={PRIORITY_PRODUCTS_SLICE}" in prod


def test_additional_first_party_units() -> None:
    assert "documento.service" in ADDITIONAL_FIRST_PARTY_UNITS
    assert "cliq_tech_hangout.service" in ADDITIONAL_FIRST_PARTY_UNITS
    assert "gunicorn-ceeu.service" in ADDITIONAL_FIRST_PARTY_UNITS


def test_priority_memory_high_8_gib_no_min_no_max() -> None:
    assert PRIORITY_MEMORY_HIGH_BYTES == gib_to_bytes(8)
    assert PRIORITY_MEMORY_HIGH == str(PRIORITY_MEMORY_HIGH_BYTES)
    spec = next(s for s in hierarchy_slice_specs() if s.name == PRIORITY_SLICE)
    body = render_hierarchy_slice_unit(spec)
    assert f"MemoryHigh={PRIORITY_MEMORY_HIGH}" in body
    assert "MemoryMin=" not in body
    # Phase 3B-1: no hard MemoryMax on priority parent
    assert "MemoryMax=" not in body


def test_tenants_remain_outside_priority() -> None:
    path = (
        "0::/ifnotus.slice/ifnotus-workloads.slice/"
        "ifnotus-workloads-tenants.slice/ifnotus-workloads-tenants-env-abc.slice"
    )
    got = classify_process_hierarchy(cgroup_path=path, expected="tenants")
    assert got["ok"] is True
    assert got["under_priority"] is False
    pri = classify_process_hierarchy(cgroup_path=path, expected="priority")
    assert pri["ok"] is False


def test_tenants_memory_max_30_gib_unchanged() -> None:
    from app.services.platform.workload_slices import TENANTS_MEMORY_MAX, TENANTS_MEMORY_MAX_BYTES

    assert TENANTS_MEMORY_MAX_BYTES == gib_to_bytes(30)
    spec = next(s for s in hierarchy_slice_specs() if s.name == TENANTS_SLICE)
    body = render_hierarchy_slice_unit(spec)
    assert f"MemoryMax={TENANTS_MEMORY_MAX}" in body
    assert "MemoryMin=" not in body


def test_infra_outside_priority() -> None:
    path = "0::/system.slice/nginx.service"
    got = classify_process_hierarchy(cgroup_path=path, expected="infrastructure")
    assert got["ok"] is True
    assert got["under_priority"] is False
    assert got["under_tenants"] is False


def test_core_requires_priority_core_path() -> None:
    path = (
        "0::/ifnotus-workloads.slice/ifnotus-workloads-priority.slice/"
        "ifnotus-workloads-priority-core.slice/ifnotus-api.service"
    )
    assert classify_process_hierarchy(cgroup_path=path, expected="core")["ok"] is True
    legacy = "0::/ifnotus-workloads.slice/ifnotus-workloads-core.slice/ifnotus-api.service"
    # Legacy path no longer counted as ok for expected=core (must be under priority-core)
    assert classify_process_hierarchy(cgroup_path=legacy, expected="core")["ok"] is False


def test_safe_emergency_capacity_uses_memavailable_not_48() -> None:
    # 10 GiB available, 6 GiB floor → 4 GiB host spare; budget 9 → min=4
    cap = safe_emergency_capacity_gib(
        mem_available_bytes=gib_to_bytes(10),
        safety_floor_gib=6,
        emergency_allocated_gib=0,
        emergency_budget_max_gib=9,
    )
    assert cap == 4.0
    # Budget remaining 2 GiB caps grant
    cap2 = safe_emergency_capacity_gib(
        mem_available_bytes=gib_to_bytes(40),
        safety_floor_gib=6,
        emergency_allocated_gib=7,
        emergency_budget_max_gib=9,
    )
    assert cap2 == 2.0
    assert HOST_MEMAVAILABLE_SAFETY_FLOOR_GIB == 6.0
    assert EMERGENCY_BUDGET_MAX_GIB == 9.0
    # Never invent capacity from marketed 48
    assert safe_emergency_capacity_gib(mem_available_bytes=gib_to_bytes(5), safety_floor_gib=6) == 0.0


def test_host_safety_status_bands() -> None:
    assert classify_host_safety_status(mem_available_bytes=gib_to_bytes(40)) == STATUS_SAFE
    # <6 GiB floor → CRITICAL; 6–8 → DENY_BURST (LOW_HEADROOM); 8–10 → REDUCED (WATCH)
    assert classify_host_safety_status(mem_available_bytes=gib_to_bytes(5)) == STATUS_CRITICAL_PRESSURE
    assert classify_host_safety_status(mem_available_bytes=gib_to_bytes(7)) == STATUS_DENY_BURST
    assert classify_host_safety_status(mem_available_bytes=gib_to_bytes(9)) == STATUS_REDUCED_HEADROOM
    assert (
        classify_host_safety_status(mem_available_bytes=gib_to_bytes(2), psi_some_avg10=25.0)
        == STATUS_CRITICAL_PRESSURE
    )
