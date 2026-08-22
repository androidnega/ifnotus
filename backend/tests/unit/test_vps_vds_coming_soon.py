"""PHASE 35 — Cloud VPS/VDS stay disabled on the shared node."""

from __future__ import annotations

from types import SimpleNamespace

from app.services.platform.plan_matrix import (
    COMING_SOON_KEYS,
    coming_soon_products,
    requires_external_vm,
    sellable_on_shared_node,
)


def _plan(slug: str, **feats):
    return SimpleNamespace(
        slug=slug,
        name=slug,
        price_monthly=100,
        product_kind="cloud",
        features=feats or None,
    )


def test_coming_soon_keys_are_vps_vds_only() -> None:
    assert COMING_SOON_KEYS == ("cloud-vps", "cloud-vds")


def test_coming_soon_products_are_not_sellable() -> None:
    rows = coming_soon_products()
    assert len(rows) == 2
    names = {r["name"] for r in rows}
    assert names == {"Cloud VPS", "Cloud VDS"}
    for row in rows:
        assert row["sellable"] is False
        assert row["requires_external_vm"] is True
        assert row["status"] == "coming_soon"


def test_requires_external_vm_matches_sellable_gate() -> None:
    vps = _plan("cloud-vps")
    managed = _plan("student-starter")
    assert sellable_on_shared_node(vps) is False
    assert requires_external_vm(vps) is True
    assert sellable_on_shared_node(managed) is True
    assert requires_external_vm(managed) is False
