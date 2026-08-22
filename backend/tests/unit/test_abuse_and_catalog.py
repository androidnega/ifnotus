"""Host disk pressure / abuse gate (PHASE 16)."""

from __future__ import annotations

from types import SimpleNamespace

from app.services.platform.abuse import evaluate_disk_pressure, should_block_provisioning


def test_should_block_only_when_critical() -> None:
    settings = SimpleNamespace(host_disk_warn_pct=80, host_disk_crit_pct=95)
    assert should_block_provisioning(settings, pressure={"level": "ok", "block_provisioning": False}) is False
    assert should_block_provisioning(settings, pressure={"level": "warning", "block_provisioning": False}) is False
    assert should_block_provisioning(settings, pressure={"level": "critical", "block_provisioning": True}) is True


def test_evaluate_disk_pressure_has_expected_keys() -> None:
    settings = SimpleNamespace(
        customer_environments_root="/",
        host_disk_warn_pct=80,
        host_disk_high_pct=90,
        host_disk_crit_pct=95,
        infra_min_free_storage_gb=20,
    )
    snap = evaluate_disk_pressure(settings)  # type: ignore[arg-type]
    assert "used_pct" in snap
    assert "level" in snap
    assert snap["level"] in {"ok", "warning", "high", "critical"}
    assert 0 <= float(snap["used_pct"]) <= 100


def test_sellable_cloud_vps_false() -> None:
    from decimal import Decimal

    from app.services.platform.plan_matrix import sellable_on_shared_node

    vps = SimpleNamespace(
        slug="cloud-vps",
        name="Cloud VPS",
        price_monthly=Decimal("170"),
        features={"matrix_key": "cloud-vps", "kind": "vps"},
    )
    managed = SimpleNamespace(
        slug="macho-power",
        name="Macho Power",
        price_monthly=Decimal("300"),
        features=None,
    )
    assert sellable_on_shared_node(vps) is False
    assert sellable_on_shared_node(managed) is True
