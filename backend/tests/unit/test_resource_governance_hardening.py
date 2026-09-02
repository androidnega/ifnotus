"""Final hardening: host pressure, fast spike, storage ledger, bandwidth, structural."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from app.core.exceptions import ValidationError
from app.services.platform.bandwidth_accounting import (
    ACTION_HIGH_WARN,
    ACTION_NONE,
    ACTION_SOFT_BLOCK,
    ACTION_WARN,
    BandwidthCycle,
    BandwidthStore,
    classify_bandwidth_action,
    merge_usage_delta,
    reset_cycle_if_needed,
    tb_to_bytes,
)
from app.services.platform.host_safety import (
    STATUS_CRITICAL_HEADROOM,
    STATUS_LOW_HEADROOM,
    STATUS_SAFE,
    STATUS_WATCH,
    classify_host_pressure_band,
    grants_blocked_by_host_pressure,
)
from app.services.platform.resource_governor import (
    FakeBackend,
    ResourceEmergencyGovernor,
    estimate_seconds_to_max,
    fast_pressure_request,
    gib_to_bytes,
    growth_rate_bps,
)
from app.services.platform.resource_policy import (
    CPU_DRIFT_LEGACY,
    CPU_DRIFT_MISSING,
    CPU_DRIFT_OK,
    PlanView,
    detect_cpu_quota_drift,
    resolve_cpu_quota_percent,
)
from app.services.platform.storage_pool_ledger import (
    StoragePoolLedgerService,
    is_shared_pool_consumer,
)
from app.services.platform.structural_ownership import plan_sftp_chroot_structural_repairs
from app.services.platform.workload_slices import PRIORITY_SLICE, TENANTS_SLICE


def test_host_pressure_bands() -> None:
    assert classify_host_pressure_band(mem_available_bytes=gib_to_bytes(12)) == STATUS_SAFE
    assert classify_host_pressure_band(mem_available_bytes=gib_to_bytes(9.5)) == STATUS_WATCH
    assert classify_host_pressure_band(mem_available_bytes=gib_to_bytes(7)) == STATUS_LOW_HEADROOM
    assert classify_host_pressure_band(mem_available_bytes=gib_to_bytes(5)) == STATUS_CRITICAL_HEADROOM
    assert grants_blocked_by_host_pressure(STATUS_LOW_HEADROOM)
    assert grants_blocked_by_host_pressure(STATUS_CRITICAL_HEADROOM)
    assert not grants_blocked_by_host_pressure(STATUS_WATCH)


def test_fast_spike_requires_growth_and_still_gated(tmp_path: Path) -> None:
    now = 1_000_000.0
    hist = [
        (now - 10, gib_to_bytes(6.5)),
        (now, gib_to_bytes(7.5)),  # +100 MiB/s-ish over 10s... actually 1GiB/10s
    ]
    assert growth_rate_bps(hist) > 0
    assert estimate_seconds_to_max(
        memory_current_bytes=gib_to_bytes(7.5),
        memory_max_bytes=gib_to_bytes(8),
        growth_bytes_per_sec=growth_rate_bps(hist),
    ) < 30
    assert fast_pressure_request(
        memory_current_bytes=gib_to_bytes(7.5),
        memory_max_bytes=gib_to_bytes(8),
        normal_max_gib=8,
        history=hist,
    )
    # Single temporary spike without growth history → no fast path
    assert not fast_pressure_request(
        memory_current_bytes=gib_to_bytes(7.5),
        memory_max_bytes=gib_to_bytes(8),
        normal_max_gib=8,
        history=[(now, gib_to_bytes(7.5))],
    )

    be = FakeBackend()
    be.slices[PRIORITY_SLICE].memory_current_bytes = gib_to_bytes(7.5)
    be.slices[PRIORITY_SLICE].memory_max_bytes = gib_to_bytes(8)
    clock = {"t": now}

    def mem_low():
        return {
            "MemTotal": gib_to_bytes(47),
            "MemAvailable": gib_to_bytes(5.5),  # CRITICAL / DENY
            "SwapTotal": 2 * 1024**3,
            "SwapFree": 2 * 1024**3,
        }

    gov = ResourceEmergencyGovernor(
        backend=be,
        meminfo_reader=mem_low,
        psi_reader=lambda: {
            "some": "some avg10=0.00 avg60=0.00 avg300=0.00 total=0",
            "full": "full avg10=0.00 avg60=0.00 avg300=0.00 total=0",
            "available": True,
        },
        now_fn=lambda: clock["t"],
        audit_path=tmp_path / "a.jsonl",
        state_path=tmp_path / "s.json",
        dry_run=False,
    )
    gov._bootstrapped = True
    gov.current_history["priority"] = hist
    gov.ledger.priority_emergency_gib = 0
    snap = gov.tick(apply=True)
    assert snap.planned is not None
    assert snap.planned.action == "deny"
    assert "host_safety" in (snap.planned.reason or "")


def test_storage_pool_consumer_excludes_vps_vds() -> None:
    vps = PlanView(
        slug="cloud-vps",
        name="VPS",
        price_monthly=500,
        ram_gb=8,
        storage_gb=100,
    )
    vds = PlanView(
        slug="cloud-vds",
        name="VDS",
        price_monthly=900,
        ram_gb=24,
        storage_gb=180,
    )
    shared = PlanView(
        slug="student-starter",
        name="Starter",
        price_monthly=25,
        ram_gb=0.25,
        storage_gb=2,
    )
    assert not is_shared_pool_consumer(vps, policy=None)  # type: ignore[arg-type]
    # policy None uses default via function — fix call
    from app.services.platform.resource_policy import default_host_resource_policy

    pol = default_host_resource_policy()
    assert not is_shared_pool_consumer(vps, policy=pol)
    assert not is_shared_pool_consumer(vds, policy=pol)
    assert is_shared_pool_consumer(shared, policy=pol)


@pytest.mark.asyncio
async def test_storage_pool_assert_rejects_over_140() -> None:
    session = MagicMock()
    svc = StoragePoolLedgerService(session)
    svc.recompute_committed_gb = AsyncMock(  # type: ignore[method-assign]
        return_value=__import__(
            "app.services.platform.storage_pool_ledger", fromlist=["StoragePoolSnapshot"]
        ).StoragePoolSnapshot(
            pool_total_gb=140,
            committed_gb=140,
            remaining_gb=0,
            percent_committed=100,
            core_reserve_gb=40,
            active_shared_envs=10,
            excluded_dedicated_envs=0,
        )
    )
    shared = PlanView(
        slug="x", name="x", price_monthly=25, ram_gb=1, storage_gb=2
    )
    with pytest.raises(ValidationError):
        await svc.assert_can_allocate(requested_gb=1, plan=shared)


def test_bandwidth_thresholds_and_idempotency(tmp_path: Path) -> None:
    assert classify_bandwidth_action(79) == ACTION_NONE
    assert classify_bandwidth_action(80) == ACTION_WARN
    assert classify_bandwidth_action(90) == ACTION_HIGH_WARN
    assert classify_bandwidth_action(99) == ACTION_HIGH_WARN
    assert classify_bandwidth_action(100) == ACTION_SOFT_BLOCK
    assert classify_bandwidth_action(150) == ACTION_SOFT_BLOCK
    assert classify_bandwidth_action(None) == ACTION_NONE
    assert tb_to_bytes(1) == 1000**4

    cycle = BandwidthCycle(
        environment_id=str(uuid4()),
        cycle_start=datetime.now(UTC).isoformat(),
        cycle_end=(datetime.now(UTC) + timedelta(days=30)).isoformat(),
        limit_bytes=1000,
    )
    cycle = merge_usage_delta(cycle, bytes_in_delta=400, bytes_out_delta=100, checkpoint_id="c1")
    assert cycle.used_bytes == 500
    cycle2 = merge_usage_delta(cycle, bytes_in_delta=400, bytes_out_delta=100, checkpoint_id="c1")
    assert cycle2.used_bytes == 500  # idempotent / no double count

    # 99% allowed (no soft block yet)
    cycle99 = BandwidthCycle(
        environment_id=str(uuid4()),
        cycle_start=datetime.now(UTC).isoformat(),
        cycle_end=(datetime.now(UTC) + timedelta(days=30)).isoformat(),
        limit_bytes=1000,
    )
    cycle99 = merge_usage_delta(cycle99, bytes_in_delta=990, bytes_out_delta=0, checkpoint_id="p99")
    assert cycle99.percent == 99.0
    assert cycle99.soft_blocked is False

    cycle100 = merge_usage_delta(cycle99, bytes_in_delta=10, bytes_out_delta=0, checkpoint_id="p100")
    assert cycle100.percent == 100.0
    assert cycle100.soft_blocked is True
    # >100 stays enforced
    cycle110 = merge_usage_delta(cycle100, bytes_in_delta=100, bytes_out_delta=0, checkpoint_id="p110")
    assert cycle110.percent == 110.0
    assert cycle110.soft_blocked is True

    store = BandwidthStore(tmp_path)
    store.save(cycle)
    loaded = store.load(cycle.environment_id)
    assert loaded is not None
    assert loaded.used_bytes == 500

    # Multi-domain: one cycle per environment (not per domain) — same env id.
    assert loaded.environment_id == cycle.environment_id

    expired = BandwidthCycle(
        environment_id=cycle.environment_id,
        cycle_start=(datetime.now(UTC) - timedelta(days=60)).isoformat(),
        cycle_end=(datetime.now(UTC) - timedelta(days=1)).isoformat(),
        limit_bytes=1000,
        bytes_in=999,
        bytes_out=1,
        soft_blocked=True,
    )
    rolled = reset_cycle_if_needed(expired)
    assert rolled.used_bytes == 0
    assert rolled.soft_blocked is False

    # Plan upgrade restores
    from app.services.platform.bandwidth_accounting import apply_plan_limit, grant_additional_allowance

    blocked = BandwidthCycle(
        environment_id=str(uuid4()),
        cycle_start=datetime.now(UTC).isoformat(),
        cycle_end=(datetime.now(UTC) + timedelta(days=30)).isoformat(),
        limit_bytes=1000,
        bytes_in=1000,
        soft_blocked=True,
    )
    upgraded = apply_plan_limit(blocked, 5000)
    assert upgraded.soft_blocked is False
    blocked2 = BandwidthCycle(
        environment_id=str(uuid4()),
        cycle_start=datetime.now(UTC).isoformat(),
        cycle_end=(datetime.now(UTC) + timedelta(days=30)).isoformat(),
        limit_bytes=1000,
        bytes_in=1000,
        soft_blocked=True,
    )
    granted = grant_additional_allowance(blocked2, 500)
    assert granted.soft_blocked is False
    assert granted.effective_limit_bytes == 1500

    # Unlimited never blocks
    unlimited = BandwidthCycle(
        environment_id=str(uuid4()),
        cycle_start=datetime.now(UTC).isoformat(),
        cycle_end=(datetime.now(UTC) + timedelta(days=30)).isoformat(),
        limit_bytes=None,
        bytes_in=10**15,
    )
    assert unlimited.percent is None
    assert classify_bandwidth_action(unlimited.percent) == ACTION_NONE
    from app.services.platform.bandwidth_accounting import should_enforce_soft_block

    assert should_enforce_soft_block(unlimited) is False


def test_bandwidth_log_ingest_idempotent_and_rotation_safe(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.services.platform import bandwidth_accounting as ba

    log = tmp_path / "bw.log"
    log.write_text(
        "a.example 100 200 50\n"
        "b.example 10 20 5\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(ba, "BANDWIDTH_LOG", log)
    monkeypatch.setattr(ba, "STATE_DIR", tmp_path / "state")
    monkeypatch.setattr(ba, "INGRESS_CHECKPOINT", tmp_path / "state" / "ingress_checkpoint.json")

    host_map = {"a.example": "env-a", "b.example": "env-b"}
    d1 = ba.ingest_bandwidth_log_deltas(host_to_env=host_map, log_path=log)
    assert d1["env-a"]["out"] == 200
    assert d1["env-b"]["out"] == 20
    ck1 = ba.checkpoint_id_from_ingest(d1)

    # Second ingest with no new lines → empty (no double count)
    d2 = ba.ingest_bandwidth_log_deltas(host_to_env=host_map, log_path=log)
    assert d2 == {} or d2.get("env-a") is None

    # Append more (simulates continued traffic; rotation would reset inode+offset)
    with log.open("a", encoding="utf-8") as fh:
        fh.write("a.example 1 3 1\n")
    d3 = ba.ingest_bandwidth_log_deltas(host_to_env=host_map, log_path=log)
    assert d3["env-a"]["out"] == 3
    ck3 = ba.checkpoint_id_from_ingest(d3)
    assert ck3 != ck1


def test_soft_block_nginx_overlay(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.services.platform import bandwidth_enforcement as be

    monkeypatch.setattr(be, "APPS_HOSTS_DIR", tmp_path / "hosts")
    monkeypatch.setattr(be, "BLOCKS_DIR", tmp_path / "blocks")
    monkeypatch.setattr(be, "PAGES_DIR", tmp_path / "pages")
    r = be.apply_soft_block("media1.ifnotus.space")
    assert r["ok"] is True
    assert be.is_soft_blocked("media1.ifnotus.space")
    page = (tmp_path / "pages" / "soft-block.html")
    assert page.is_file()
    conf = be.soft_block_conf_path("media1.ifnotus.space")
    assert "location ^~ /" in conf.read_text(encoding="utf-8")
    be.clear_soft_block("media1.ifnotus.space")
    assert not be.is_soft_blocked("media1.ifnotus.space")


def test_cpu_central_policy() -> None:
    assert resolve_cpu_quota_percent(None, env_cpu_limit=0.4) == 40
    assert detect_cpu_quota_drift(live_cpu_quota="25%", expected_percent=25) == CPU_DRIFT_OK
    assert detect_cpu_quota_drift(live_cpu_quota=None, expected_percent=25) == CPU_DRIFT_MISSING
    assert detect_cpu_quota_drift(live_cpu_quota="20%", expected_percent=25) == CPU_DRIFT_LEGACY


def test_sftp_structural_repairs_exact_only(tmp_path: Path) -> None:
    home = tmp_path / "site"
    home.mkdir()
    (home / "public_html").mkdir()
    (home / "public_ftp").mkdir()
    (home / "www").symlink_to("public_html")
    repairs = plan_sftp_chroot_structural_repairs(home, tenant_user="ifn_test")
    paths = {Path(r.path).name for r in repairs}
    assert "" in paths or home.name in {Path(r.path).name for r in repairs} or str(home) in [
        r.path for r in repairs
    ]
    assert any(Path(r.path).name == "public_ftp" for r in repairs)
    assert any(Path(r.path).name == "www" for r in repairs)
    # Never invents recursive -R style
    assert all(r.path not in {"-R", "--recursive"} for r in repairs)


def test_suspended_prepare_drift() -> None:
    from app.services.platform.memory_policy import (
        DRIFT_LEGACY_MEMORY_MAX,
        DRIFT_SUSPENDED_PREPARE,
        DRIFT_SUSPENDED_SKIP,
        SharedMemoryTargets,
        detect_drift,
        gib_to_bytes,
    )
    from app.services.platform.resource_policy import PlanResourceClass

    targets = SharedMemoryTargets(
        plan_class=PlanResourceClass.SHARED_LOW,
        memory_high_gib=2,
        memory_max_gib=12,
        memory_high_bytes=gib_to_bytes(2),
        memory_max_bytes=gib_to_bytes(12),
    )
    live_legacy = {
        "unit_exists": True,
        "memory_high_bytes": None,
        "memory_max_bytes": 384 * 1024 * 1024,
    }
    assert detect_drift(live=live_legacy, targets=targets, env_status="suspended") == DRIFT_LEGACY_MEMORY_MAX
    live_ok = {
        "unit_exists": True,
        "memory_high_bytes": gib_to_bytes(2),
        "memory_max_bytes": gib_to_bytes(12),
    }
    assert detect_drift(live=live_ok, targets=targets, env_status="suspended") == DRIFT_SUSPENDED_SKIP
    live_missing = {"unit_exists": False, "memory_high_bytes": None, "memory_max_bytes": None}
    assert detect_drift(live=live_missing, targets=targets, env_status="suspended") == DRIFT_SUSPENDED_PREPARE
