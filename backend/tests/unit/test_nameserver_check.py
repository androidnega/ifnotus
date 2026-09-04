"""Live nameserver delegation messages for walk-in domains."""

from __future__ import annotations

from app.core.config import Environment, Settings
from app.services.platform.dns import EnvironmentDnsService


def _settings() -> Settings:
    return Settings(
        secret_key="test-secret-key-at-least-32-characters-long",
        database_url="postgresql+asyncpg://ifnotus:ifnotus@localhost:5432/ifnotus_test",
        redis_url="redis://localhost:6379/1",
        environment=Environment.TESTING,
        debug=True,
        dns_ns1="ns1.ifnotus.space",
        dns_ns2="ns2.ifnotus.space",
    )


def test_included_hostname_is_already_on_ifnotus() -> None:
    svc = EnvironmentDnsService(_settings(), session=None)  # type: ignore[arg-type]
    out = svc.check_public_delegation("mensah.ifnotus.space")
    assert out["included_hostname"] is True
    assert out["ns_live"] is True
    assert "ifnotus.space" in out["message"]


def test_foreign_ns_reports_not_delegated(monkeypatch) -> None:
    svc = EnvironmentDnsService(_settings(), session=None)  # type: ignore[arg-type]

    def fake_live(domain: str, expected: list[str]) -> dict:
        return {
            "ns_live": False,
            "dns_live": False,
            "dns_mode": None,
            "ns_found": ["ns1.example-registrar.com", "ns2.example-registrar.com"],
        }

    monkeypatch.setattr(svc, "_lookup_dns_live", fake_live)
    out = svc.check_public_delegation("shop.example.com")
    assert out["included_hostname"] is False
    assert out["ns_live"] is False
    assert "ns1.ifnotus.space" in out["message"]
    assert "example-registrar.com" in out["message"]


def test_matching_ns_is_live(monkeypatch) -> None:
    svc = EnvironmentDnsService(_settings(), session=None)  # type: ignore[arg-type]

    def fake_live(domain: str, expected: list[str]) -> dict:
        return {
            "ns_live": True,
            "dns_live": True,
            "dns_mode": "nameserver",
            "ns_found": ["ns1.ifnotus.space", "ns2.ifnotus.space"],
        }

    monkeypatch.setattr(svc, "_lookup_dns_live", fake_live)
    out = svc.check_public_delegation("shop.example.com")
    assert out["ns_live"] is True
    assert "pointing at IFNOTUS" in out["message"]


def test_parent_referral_counts_when_recursive_empty(monkeypatch) -> None:
    """Registrar NS can be live before BIND has a zone (recursive dig SERVFAIL)."""
    svc = EnvironmentDnsService(_settings(), session=None)  # type: ignore[arg-type]

    def fake_dig(qname: str, qtype: str) -> list[str]:
        if qtype.upper() == "NS" and qname == "ibuk.online":
            return []
        if qtype.upper() == "NS" and qname == "online":
            return ["ns10.trs-dns.org"]
        if qtype.upper() == "A":
            return []
        return []

    monkeypatch.setattr(svc, "_dig", fake_dig)
    monkeypatch.setattr(
        svc,
        "_dig_ns_via_parent",
        lambda name: ["ns1.ifnotus.space", "ns2.ifnotus.space"] if name == "ibuk.online" else [],
    )
    monkeypatch.setattr(svc, "_server_ips", lambda: {"80.241.223.82"})
    live = svc._lookup_dns_live("ibuk.online", ["ns1.ifnotus.space", "ns2.ifnotus.space"])
    assert live["ns_live"] is True
    assert live["dns_mode"] == "nameserver"
    assert "ns1.ifnotus.space" in live["ns_found"]


def test_parse_dig_ns_authority_lines() -> None:
    svc = EnvironmentDnsService(_settings(), session=None)  # type: ignore[arg-type]
    stdout = (
        "ibuk.online.\t900\tIN\tNS\tns1.ifnotus.space.\n"
        "ibuk.online.\t900\tIN\tNS\tns2.ifnotus.space.\n"
    )
    assert svc._parse_dig_ns_lines(stdout) == ["ns1.ifnotus.space", "ns2.ifnotus.space"]
