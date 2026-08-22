"""PHASE 34 — public package catalog finalization."""

from __future__ import annotations

from types import SimpleNamespace

from app.services.platform.plan_matrix import (
    PUBLIC_CATALOG_KEYS,
    PUBLIC_DISPLAY_NAMES,
    SLUG_ALIASES,
    catalog_card_for,
    capabilities_for,
    features_for,
    listed_in_public_catalog,
    sellable_on_shared_node,
)


def _plan(slug: str, **extra):
    return SimpleNamespace(
        slug=slug,
        name=slug,
        price_monthly=50,
        product_kind="managed_student",
        features=extra.get("features"),
        cpu_cores=1,
        ram_gb=1,
        storage_gb=10,
        **{k: v for k, v in extra.items() if k != "features"},
    )


def test_storefront_aliases_resolve_to_matrix_keys() -> None:
    assert SLUG_ALIASES["student-basic"] == "student-starter"
    assert SLUG_ALIASES["student-developer"] == "club-connect"
    assert SLUG_ALIASES["student-advanced"] == "student-elite"
    assert SLUG_ALIASES["personal-hosting"] == "personal"
    assert SLUG_ALIASES["business-hosting"] == "business-pro"


def test_public_catalog_keys_are_shared_realistic_packs() -> None:
    assert PUBLIC_CATALOG_KEYS == (
        "student-starter",
        "club-connect",
        "student-pro",
        "student-elite",
        "personal",
        "business-pro",
    )
    for key in PUBLIC_CATALOG_KEYS:
        assert key in PUBLIC_DISPLAY_NAMES


def test_listed_packs_and_hidden_legacy() -> None:
    for slug in (
        "student-starter",
        "club-connect",
        "student-pro",
        "student-elite",
        "personal",
        "business-pro",
    ):
        assert listed_in_public_catalog(_plan(slug)) is True

    for slug in ("macho-power", "monster-cloud"):
        assert sellable_on_shared_node(_plan(slug)) is True
        assert listed_in_public_catalog(_plan(slug)) is False

    for slug in ("cloud-vps", "cloud-vds"):
        assert sellable_on_shared_node(_plan(slug)) is False
        assert listed_in_public_catalog(_plan(slug)) is False


def test_display_names_match_recommended_storefront() -> None:
    expected = {
        "student-starter": "Student Basic",
        "club-connect": "Student Developer",
        "student-pro": "Student Pro",
        "student-elite": "Student Advanced",
        "personal": "Personal Hosting",
        "business-pro": "Business Hosting",
    }
    for slug, name in expected.items():
        feats = features_for(_plan(slug))
        assert feats["display_name"] == name


def test_catalog_card_and_capabilities_are_backend_sourced() -> None:
    plan = _plan("student-starter")
    card = catalog_card_for(plan)
    caps = capabilities_for(plan)
    assert card["display_name"] == "Student Basic"
    assert isinstance(card["highlights"], list) and card["highlights"]
    assert caps["matrix_key"] == "student-starter"
    assert "on" in caps and "ssh_mode" in caps
    assert caps["stacks"]
