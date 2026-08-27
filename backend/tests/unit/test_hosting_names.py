"""Hosting name generation — fully automatic, no customer collision UX."""

from __future__ import annotations

from types import SimpleNamespace

from app.services.platform.hosting_names import (
    MAX_HOSTING_NAME_LEN,
    HostingNameService,
    candidate_bases,
    domain_label,
    is_hosting_name_reserved,
    with_suffix,
)


def test_max_length_is_twelve() -> None:
    assert MAX_HOSTING_NAME_LEN == 12


def test_custom_domain_bases() -> None:
    assert domain_label("csdttu.online") == "csdttu"
    assert domain_label("votebridge.online") == "votebridge"
    assert domain_label("manuelcode.com") == "manuelcode"
    assert domain_label("www.votebridge.online") == "votebridge"
    assert candidate_bases(domain="csdttu.online")[0] == "csdttu"
    assert candidate_bases(domain="manuelcode.com")[0] == "manuelcode"


def test_student_hostname_gets_host_suffix() -> None:
    bases = candidate_bases(domain="manuel.ifnotus.space")
    assert bases[0] == "manuelhost"
    bases2 = candidate_bases(domain="kwofie.ifnotus.space", last_name="Kwofie")
    assert bases2[0].startswith("kwofie")


def test_surname_and_firstname_fallbacks() -> None:
    bases = candidate_bases(last_name="Kwofie", first_name="Manuel")
    assert bases[0] == "kwofiehost"
    assert "manuelhost" in bases


def test_collision_suffix_style() -> None:
    assert with_suffix("manuelhost", 0) == "manuelhost"
    assert with_suffix("manuelhost", 1) == "manuelh2"
    assert with_suffix("manuelhost", 2) == "manuelh3"
    assert with_suffix("csdttu", 1) == "csdttu2"
    assert len(with_suffix("manuelhost", 1)) <= MAX_HOSTING_NAME_LEN


def test_reserved_names_skipped() -> None:
    assert is_hosting_name_reserved("mail")
    assert is_hosting_name_reserved("cpanel")
    assert is_hosting_name_reserved("admin")
    assert is_hosting_name_reserved("www")
    assert not is_hosting_name_reserved("manuelhost")
    # reserved base → first yielded candidate is a safe variant
    from app.services.platform.hosting_names import iter_name_candidates

    first = next(iter_name_candidates(["admin"]))
    assert first != "admin"
    assert first.startswith("admin") or first.startswith("site")
    assert not is_hosting_name_reserved(first)


def test_spaces_symbols_unicode_long() -> None:
    bases = candidate_bases(first_name="Manuél José", last_name="Kwofie-Mensah")
    assert all(b.isalnum() for b in bases)
    assert all(b[0].isalpha() for b in bases)
    assert all(len(b) <= MAX_HOSTING_NAME_LEN for b in bases)
    long = candidate_bases(domain="superlongdomainlabel.example.com")[0]
    assert len(long) <= MAX_HOSTING_NAME_LEN
    assert candidate_bases(domain="manuel-code.com")[0] == "manuelcode"


def test_empty_source_falls_back() -> None:
    bases = candidate_bases(domain="", first_name="", last_name="")
    assert bases[0] == "sitehost"


def test_propose_sync_examples() -> None:
    svc = HostingNameService(session=None)  # type: ignore[arg-type]
    assert svc.propose_sync(domain="votebridge.online") == "votebridge"
    assert svc.propose_sync(domain="manuel.ifnotus.space") == "manuelhost"
    assert svc.propose_sync(first_name="Manuel") == "manuelhost"
    assert svc.propose_sync(domain="admin.example.com") != "admin"


def test_stability_existing_name_not_regenerated() -> None:
    """assign_if_missing must return existing hosting_name without change."""
    import asyncio
    from unittest.mock import MagicMock

    env = SimpleNamespace(
        id="00000000-0000-0000-0000-000000000001",
        customer_id="00000000-0000-0000-0000-000000000002",
        domain="manuel.ifnotus.space",
        hosting_name="manuelhost",
    )
    session = MagicMock()
    svc = HostingNameService(session)

    async def _run() -> str:
        return await svc.assign_if_missing(env)  # type: ignore[arg-type]

    assert asyncio.run(_run()) == "manuelhost"
    session.get.assert_not_called()
