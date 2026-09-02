"""Phase 3B-2 emergency governor + protected paths + FPM guard tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.core.exceptions import ValidationError
from app.services.platform.host_safety import EMERGENCY_BUDGET_MAX_GIB, HOST_MEMAVAILABLE_SAFETY_FLOOR_GIB
from app.services.platform.resource_governor import (
    INCREMENT_GIB,
    PRIORITY_NORMAL_MAX_GIB,
    RELEASE_COOLDOWN_SEC,
    TENANT_NORMAL_MAX_GIB,
    TRIGGER_SAMPLES,
    EmergencyLedger,
    FakeBackend,
    ResourceEmergencyGovernor,
    can_safely_shrink,
    effective_memory_max_bytes,
    pressure_threshold_bytes,
    reconstruct_emergency_from_memory_max,
    round_grantable_to_increment,
)
from app.services.platform.resource_policy import gib_to_bytes
from app.services.platform.workload_slices import PRIORITY_SLICE, TENANTS_SLICE


def _mem(*, avail_gib: float = 40.0, swap_used_mib: float = 0.0) -> dict[str, int]:
    swap_used = int(swap_used_mib * 1024 * 1024)
    swap_total = max(swap_used, 2 * 1024**3)
    return {
        "MemTotal": gib_to_bytes(47.045),
        "MemAvailable": gib_to_bytes(avail_gib),
        "SwapTotal": swap_total,
        "SwapFree": swap_total - swap_used,
    }


def _psi(some: float = 0.0, full: float = 0.0) -> dict[str, str]:
    return {
        "some": f"some avg10={some:.2f} avg60=0.00 avg300=0.00 total=0",
        "full": f"full avg10={full:.2f} avg60=0.00 avg300=0.00 total=0",
        "available": True,
    }


def _gov(tmp_path: Path, backend: FakeBackend | None = None, **kwargs) -> ResourceEmergencyGovernor:
    be = backend or FakeBackend()
    clock = {"t": 1_000_000.0}

    def now() -> float:
        return clock["t"]

    gov = ResourceEmergencyGovernor(
        backend=be,
        meminfo_reader=kwargs.get("meminfo_reader", lambda: _mem()),
        psi_reader=kwargs.get("psi_reader", lambda: _psi()),
        now_fn=now,
        audit_path=tmp_path / "audit.jsonl",
        state_path=tmp_path / "state.json",
        dry_run=False,
    )
    gov._clock = clock  # type: ignore[attr-defined]
    return gov


def test_single_9gib_ledger_invariant() -> None:
    led = EmergencyLedger(tenant_emergency_gib=5, priority_emergency_gib=4)
    led.assert_invariant()
    assert led.total_emergency_gib == 9
    assert led.remaining_emergency_gib == 0
    with pytest.raises(ValueError):
        EmergencyLedger(tenant_emergency_gib=5, priority_emergency_gib=5).assert_invariant()


def test_tenant_and_priority_grant_and_cannot_exceed_9(tmp_path: Path) -> None:
    be = FakeBackend()
    gov = _gov(tmp_path, be)
    gov.reconcile_from_kernel()
    # Fill ledger via controlled grants
    for _ in range(5):
        snap = gov.force_grant("tenants", apply=True)
        assert snap.planned and snap.planned.action == "grant"
    for _ in range(4):
        snap = gov.force_grant("priority", apply=True)
        assert snap.planned and snap.planned.action == "grant"
    assert gov.ledger.total_emergency_gib == 9
    deny = gov.force_grant("tenants", apply=True)
    assert deny.planned and deny.planned.action == "deny"
    assert be.slices[TENANTS_SLICE].memory_max_bytes == gib_to_bytes(35)
    assert be.slices[PRIORITY_SLICE].memory_max_bytes == gib_to_bytes(12)


def test_simultaneous_prefers_priority(tmp_path: Path) -> None:
    be = FakeBackend()
    be.slices[TENANTS_SLICE].memory_current_bytes = pressure_threshold_bytes(TENANT_NORMAL_MAX_GIB) + 1
    be.slices[PRIORITY_SLICE].memory_current_bytes = pressure_threshold_bytes(PRIORITY_NORMAL_MAX_GIB) + 1
    gov = _gov(tmp_path, be)
    gov.reconcile_from_kernel()
    for _ in range(TRIGGER_SAMPLES):
        snap = gov.tick(apply=True)
    assert snap.planned is not None
    assert snap.planned.action == "grant"
    assert snap.planned.borrower == "priority"
    assert gov.ledger.priority_emergency_gib == 1
    assert gov.ledger.tenant_emergency_gib == 0


def test_host_floor_psi_swap_oom_denials(tmp_path: Path) -> None:
    be = FakeBackend()
    be.slices[PRIORITY_SLICE].memory_current_bytes = pressure_threshold_bytes(PRIORITY_NORMAL_MAX_GIB) + 1

    gov = _gov(tmp_path, be, meminfo_reader=lambda: _mem(avail_gib=5.0))
    gov.reconcile_from_kernel()
    for _ in range(TRIGGER_SAMPLES):
        snap = gov.tick(apply=True)
    assert snap.planned and snap.planned.action == "deny"
    assert "host_safety" in (snap.planned.reason or "") or "projected" in (snap.planned.reason or "")

    gov2 = _gov(tmp_path, FakeBackend(), psi_reader=lambda: _psi(some=15.0))
    be2 = gov2.backend
    assert isinstance(be2, FakeBackend)
    be2.slices[PRIORITY_SLICE].memory_current_bytes = pressure_threshold_bytes(PRIORITY_NORMAL_MAX_GIB) + 1
    gov2.reconcile_from_kernel()
    for _ in range(TRIGGER_SAMPLES):
        snap = gov2.tick(apply=True)
    assert snap.planned and snap.planned.action == "deny"
    assert "psi_some" in snap.planned.reason

    gov3 = _gov(tmp_path, FakeBackend(), meminfo_reader=lambda: _mem(swap_used_mib=300))
    be3 = gov3.backend
    assert isinstance(be3, FakeBackend)
    be3.slices[PRIORITY_SLICE].memory_current_bytes = pressure_threshold_bytes(PRIORITY_NORMAL_MAX_GIB) + 1
    gov3.reconcile_from_kernel()
    for _ in range(TRIGGER_SAMPLES):
        snap = gov3.tick(apply=True)
    assert snap.planned and snap.planned.action == "deny"
    assert "swap_used" in snap.planned.reason

    be4 = FakeBackend()
    be4.slices[PRIORITY_SLICE].memory_current_bytes = pressure_threshold_bytes(PRIORITY_NORMAL_MAX_GIB) + 1
    be4.slices[TENANTS_SLICE].memory_events = {"oom": 1, "oom_kill": 1}
    gov4 = _gov(tmp_path, be4)
    gov4.reconcile_from_kernel()
    gov4.last_oom_total[TENANTS_SLICE] = 0
    for _ in range(TRIGGER_SAMPLES):
        snap = gov4.tick(apply=True)
    assert snap.planned and snap.planned.action == "deny"
    assert "oom" in snap.planned.reason


def test_sustained_trigger_requires_3_samples(tmp_path: Path) -> None:
    be = FakeBackend()
    be.slices[TENANTS_SLICE].memory_current_bytes = pressure_threshold_bytes(TENANT_NORMAL_MAX_GIB) + 1
    gov = _gov(tmp_path, be)
    gov.reconcile_from_kernel()
    for i in range(TRIGGER_SAMPLES - 1):
        snap = gov.tick(apply=True)
        assert snap.planned and snap.planned.action == "none"
    snap = gov.tick(apply=True)
    assert snap.planned and snap.planned.action == "grant"
    assert snap.planned.amount_gib == INCREMENT_GIB


def test_release_cooldown_120s_and_safe_shrink(tmp_path: Path) -> None:
    be = FakeBackend()
    gov = _gov(tmp_path, be)
    gov.reconcile_from_kernel()
    gov.force_grant("tenants", apply=True)
    assert gov.ledger.tenant_emergency_gib == 1
    # Usage still low (1 GiB) — below normal 30
    be.slices[TENANTS_SLICE].memory_current_bytes = gib_to_bytes(1)
    # Not enough time
    snap = gov.tick(apply=True)
    assert snap.planned and snap.planned.action != "release"
    # Advance 120s
    gov._clock["t"] += RELEASE_COOLDOWN_SEC + 1  # type: ignore[attr-defined]
    # Need below_normal_since set — first tick after advance may set then need another
    # Force since in the past
    gov.below_normal_since["tenants"] = gov._clock["t"] - RELEASE_COOLDOWN_SEC - 1  # type: ignore[attr-defined]
    snap = gov.tick(apply=True)
    assert snap.planned and snap.planned.action == "release"
    assert gov.ledger.tenant_emergency_gib == 0
    assert be.slices[TENANTS_SLICE].memory_max_bytes == gib_to_bytes(30)

    assert can_safely_shrink(
        memory_current_bytes=gib_to_bytes(1),
        proposed_max_bytes=gib_to_bytes(30),
    )
    assert not can_safely_shrink(
        memory_current_bytes=gib_to_bytes(30.5),
        proposed_max_bytes=gib_to_bytes(30),
    )


def test_kernel_restart_reconciliation(tmp_path: Path) -> None:
    be = FakeBackend()
    be.slices[TENANTS_SLICE].memory_max_bytes = gib_to_bytes(32)
    be.slices[PRIORITY_SLICE].memory_max_bytes = gib_to_bytes(10)
    gov = _gov(tmp_path, be)
    snap = gov.reconcile_from_kernel()
    assert snap.ledger.tenant_emergency_gib == 2
    assert snap.ledger.priority_emergency_gib == 2
    assert reconstruct_emergency_from_memory_max(
        memory_max_bytes=gib_to_bytes(39), normal_max_gib=30
    ) == 9


def test_normals_and_no_memory_min_and_increment(tmp_path: Path) -> None:
    assert TENANT_NORMAL_MAX_GIB == 30
    assert PRIORITY_NORMAL_MAX_GIB == 8
    assert INCREMENT_GIB == 1
    assert int(EMERGENCY_BUDGET_MAX_GIB) == 9
    assert HOST_MEMAVAILABLE_SAFETY_FLOOR_GIB == 6.0
    assert round_grantable_to_increment(1.9) == 1
    assert round_grantable_to_increment(0.9) == 0
    assert effective_memory_max_bytes(normal_gib=30, emergency_gib=1) == gib_to_bytes(31)
    be = FakeBackend()
    gov = _gov(tmp_path, be)
    gov.reconcile_from_kernel()
    assert be.slices[TENANTS_SLICE].memory_max_bytes == gib_to_bytes(30)
    gov.ensure_priority_baseline(apply=True)
    assert be.slices[PRIORITY_SLICE].memory_max_bytes == gib_to_bytes(8)


def test_dry_run_no_mutation(tmp_path: Path) -> None:
    be = FakeBackend()
    be.slices[TENANTS_SLICE].memory_current_bytes = pressure_threshold_bytes(TENANT_NORMAL_MAX_GIB) + 1
    gov = _gov(tmp_path, be)
    gov.dry_run = True
    gov.reconcile_from_kernel()
    for _ in range(TRIGGER_SAMPLES):
        gov.tick(apply=False)
    assert be.mutations == []
    assert gov.ledger.tenant_emergency_gib == 0


def test_individual_tenants_remain_12gib_policy() -> None:
    from app.services.platform.memory_policy import resolve_shared_memory_targets
    from app.services.platform.resource_policy import PlanView, default_host_resource_policy

    plan = PlanView(slug="shared-standard", name="Std", price_monthly=10, ram_gb=6, storage_gb=20)
    targets = resolve_shared_memory_targets(plan, policy=default_host_resource_policy())
    assert targets.memory_max_bytes == gib_to_bytes(12)


def test_php_fpm_env_owned_socket_guard(tmp_path: Path, monkeypatch) -> None:
    from app.core.config import get_settings
    from app.services.platform import php_fpm as php_mod
    from app.services.platform.php_fpm import PhpFpmPoolService

    env_root = tmp_path / "ifnotus-envs" / "abc" / "pool.d"
    env_root.mkdir(parents=True)
    (env_root / "ifnotus-adastrachambers-com.conf").write_text(
        "[ifnotus-adastrachambers-com]\nlisten = /run/php/ifnotus-adastrachambers-com.sock\n",
        encoding="utf-8",
    )
    pool_dir = tmp_path / "pool.d"
    pool_dir.mkdir()
    monkeypatch.setattr(php_mod, "Path", Path)  # keep Path
    svc = PhpFpmPoolService(get_settings())
    svc._pool_dir = pool_dir
    monkeypatch.setattr(
        PhpFpmPoolService,
        "_listen_owned_by_env_fpm",
        staticmethod(lambda listen: "adastrachambers" in listen),
    )
    sock = svc.ensure_pool(
        hostname="adastrachambers.com",
        document_root=str(tmp_path / "public_html"),
        ram_gb=0.25,
    )
    assert sock is not None
    assert not (pool_dir / "ifnotus-adastrachambers-com.conf").exists()


@pytest.mark.asyncio
async def test_protected_structural_paths(tmp_path: Path) -> None:
    from app.services.hosting.files import (
        PROTECTED_STRUCTURAL_NAMES,
        FileManagerService,
        is_protected_structural_path,
    )
    from app.core.config import Environment, Settings

    home = tmp_path / "site"
    for name in ("public_html", "www", "public_ftp"):
        (home / name).mkdir(parents=True)
    (home / "public_html" / "index.php").write_text("ok", encoding="utf-8")
    assert PROTECTED_STRUCTURAL_NAMES == frozenset({"public_html", "www", "public_ftp"})
    assert is_protected_structural_path(home, home / "public_html")
    assert is_protected_structural_path(home, home / "www")
    assert is_protected_structural_path(home, home / "public_ftp")
    assert not is_protected_structural_path(home, home / "public_html" / "index.php")

    upload = tmp_path / "uploads"
    upload.mkdir()
    settings = Settings(
        secret_key="test-secret-key-at-least-32-characters-long",
        database_url="postgresql+asyncpg://ifnotus:ifnotus@localhost:5432/ifnotus_test",
        redis_url="redis://localhost:6379/1",
        environment=Environment.TESTING,
        debug=True,
        file_upload_temp_dir=str(upload),
        hosting_allowed_paths=[],
    )
    fm = FileManagerService(settings, only_roots=[home], storage_limit_gb=10)

    with pytest.raises(ValidationError) as ei:
        await fm.delete("public_html", permanent=True)
    assert ei.value.code == "protected_structural_path"
    with pytest.raises(ValidationError):
        await fm.move("www", "www.bak")
    res = await fm.delete("public_html/index.php", permanent=True)
    assert res.success is True
    assert not (home / "public_html" / "index.php").exists()
    assert (home / "public_html").is_dir()


def test_storage_policy_still_140_40() -> None:
    from app.services.platform.resource_policy import default_host_resource_policy

    p = default_host_resource_policy()
    assert p.tenant_storage_pool_gb == 140
    assert p.core_storage_reserve_gb == 40


def test_marketed_48_not_used_for_safety() -> None:
    from app.services.platform.host_safety import safe_emergency_capacity_gib

    # 5 GiB available → 0 grantable regardless of any 48 marketing figure
    assert safe_emergency_capacity_gib(mem_available_bytes=gib_to_bytes(5)) == 0.0
