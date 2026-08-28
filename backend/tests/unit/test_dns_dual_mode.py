"""DNS dual-mode: nameserver delegation or registrar A records."""

from __future__ import annotations

from unittest.mock import MagicMock

from app.services.platform.dns import EnvironmentDnsService


def _svc(ip: str = "80.241.223.82") -> EnvironmentDnsService:
    settings = MagicMock()
    settings.server_public_ip = ip
    settings.dns_ns1 = "ns1.ifnotus.space"
    settings.dns_ns2 = "ns2.ifnotus.space"
    return EnvironmentDnsService(settings, MagicMock())


def test_dns_live_via_nameservers(monkeypatch) -> None:
    svc = _svc()

    def fake_dig(qname: str, qtype: str) -> list[str]:
        if qtype.upper() == "NS" and qname == "studio.online":
            return ["ns1.ifnotus.space", "ns2.ifnotus.space"]
        return []

    monkeypatch.setattr(svc, "_dig", fake_dig)
    live = svc._lookup_dns_live("studio.online", svc.nameservers())
    assert live["ns_live"] is True
    assert live["dns_live"] is True
    assert live["dns_mode"] == "nameserver"


def test_dns_live_via_a_records(monkeypatch) -> None:
    svc = _svc()

    def fake_dig(qname: str, qtype: str) -> list[str]:
        if qtype.upper() == "NS":
            return ["lunar.dns-parking.com"]
        if qtype.upper() == "A":
            if qname in {"studio.online", "www.studio.online"}:
                return ["80.241.223.82"]
        return []

    monkeypatch.setattr(svc, "_dig", fake_dig)
    live = svc._lookup_dns_live("studio.online", svc.nameservers())
    assert live["ns_live"] is False
    assert live["apex_points_here"] is True
    assert live["www_points_here"] is True
    assert live["cpanel_points_here"] is True
    assert live["dns_live"] is True
    assert live["dns_mode"] == "a_record"


def test_dns_not_live_when_www_missing(monkeypatch) -> None:
    svc = _svc()

    def fake_dig(qname: str, qtype: str) -> list[str]:
        if qtype.upper() == "A" and qname == "studio.online":
            return ["80.241.223.82"]
        return []

    monkeypatch.setattr(svc, "_dig", fake_dig)
    live = svc._lookup_dns_live("studio.online", svc.nameservers())
    assert live["dns_live"] is False
    assert live["dns_mode"] is None
    assert live["cpanel_points_here"] is True  # path-based /cpanel on apex
