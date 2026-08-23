"""PHASE 38O — public catalog promises match production reality."""

from __future__ import annotations

from types import SimpleNamespace

from app.services.platform.plan_matrix import (
    PUBLIC_CATALOG_KEYS,
    SFTP_LIVE_VERIFIED,
    catalog_card_for,
    capabilities_for,
    features_for,
    production_truth_for,
)


def _plan(slug: str, **extra):
    storage = extra.pop("storage_gb", 10)
    return SimpleNamespace(
        slug=slug,
        name=slug,
        price_monthly=50,
        product_kind="managed_student",
        features=extra.get("features"),
        cpu_cores=1,
        ram_gb=1,
        storage_gb=storage,
        **{k: v for k, v in extra.items() if k != "features"},
    )


def test_public_packs_marked_beta_with_honest_transfer() -> None:
    for slug in PUBLIC_CATALOG_KEYS:
        plan = _plan(slug)
        card = catalog_card_for(plan)
        truth = production_truth_for(plan)
        assert card["product_status"] == "beta"
        assert truth["transfer"]["ftp"] == "included"
        assert truth["transfer"]["sftp"] == ("included" if SFTP_LIVE_VERIFIED else "beta")
        transfer = next(h for h in card["highlights"] if h["id"] == "transfer")
        if SFTP_LIVE_VERIFIED:
            assert "SFTP" in transfer["detail"]
        else:
            assert "SFTP beta" in transfer["detail"]


def test_backups_do_not_promise_offsite_dr() -> None:
    plan = _plan("student-pro")
    card = catalog_card_for(plan)
    backups = next(h for h in card["highlights"] if h["id"] == "backups")
    assert "same-VPS" in backups["detail"] or "not included" in backups["detail"].lower()
    truth = production_truth_for(plan)
    assert truth["offsite_dr_verified"] is False


def test_storage_highlights_include_quota_beta() -> None:
    plan = _plan("student-starter", storage_gb=2)
    card = catalog_card_for(plan)
    storage = next(h for h in card["highlights"] if h["id"] == "storage")
    assert "quota" in storage["detail"].lower()


def test_capabilities_include_production_overlay() -> None:
    plan = _plan("student-starter")
    caps = capabilities_for(plan)
    assert caps["production"]["product_status"] == "beta"
    assert caps["sftp"]["live_verified"] is SFTP_LIVE_VERIFIED


def test_student_starter_sftp_is_limited_not_full_yes() -> None:
    feats = features_for(_plan("student-starter"))
    assert feats["sftp"] == "limited"
