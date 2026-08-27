"""Tests for customer storage slug generation."""

from app.services.platform.customer_storage import (
    MAX_STORAGE_SLUG_LEN,
    MIN_STORAGE_SLUG_LEN,
    email_local_part,
    fit_slug_length,
    is_storage_slug_reserved,
    slug_candidates,
    slug_with_suffix,
)


def test_email_local_strips_random_suffix() -> None:
    assert email_local_part("bettyacheampong38_a1b2c3") == "bettyacheampong38"
    assert email_local_part("kwameblaytheophilus@gmail.com") == "kwameblaytheophilus"


def test_slug_length_bounds() -> None:
    slug = fit_slug_length("kwameblaytheophilus")
    assert MIN_STORAGE_SLUG_LEN <= len(slug) <= MAX_STORAGE_SLUG_LEN
    assert slug == "kwameblaytheoph"


def test_short_name_pads_to_minimum() -> None:
    slug = fit_slug_length("betty")
    assert len(slug) >= MIN_STORAGE_SLUG_LEN


def test_collision_suffix() -> None:
    first = slug_with_suffix("manuelhosting", 1)
    second = slug_with_suffix("manuelhosting", 2)
    assert first != second
    assert len(second) <= MAX_STORAGE_SLUG_LEN


def test_candidates_priority() -> None:
    cands = slug_candidates(
        email="bettyacheampong38@gmail.com",
        first_name="Betty",
        last_name="Enkson",
        hosting_names=["enksonhost"],
    )
    assert cands[0].startswith("betty")


def test_reserved_labels() -> None:
    assert is_storage_slug_reserved("admin")
    assert is_storage_slug_reserved("ab")
    assert not is_storage_slug_reserved("bettyenkson")
