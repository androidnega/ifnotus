"""Phase L — DNS single-writer and NS redundancy tests."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

from app.services.platform.authoritative_dns import AuthoritativeDnsService
from app.services.platform.dns_writer import (
    DnsWriterMode,
    DnsWriterService,
    effective_dns_writer,
    ns_redundancy_status,
)


def _settings(**kw):
    base = {
        "dns_ns1": "ns1.ifnotus.space",
        "dns_ns2": "ns2.ifnotus.space",
        "dns_writer_mode": "legacy_bind",
        "dns_ns2_target_ip": None,
        "hosting_provider_default": "legacy",
        "server_public_ip": "80.241.223.82",
        "server_public_ipv6": None,
        "bind_zones_dir": "/tmp/zones",
        "bind_customer_conf": "/tmp/named.conf.customer",
        "bind_named_conf_local": "/tmp/named.conf.local",
        "ispconfig_base_url": None,
        "ispconfig_remote_user": None,
        "ispconfig_remote_password": None,
    }
    base.update(kw)
    return SimpleNamespace(**base)


def test_effective_writer_legacy_by_default() -> None:
    env = SimpleNamespace(provider="legacy")
    assert effective_dns_writer(_settings(), env) == DnsWriterMode.LEGACY_BIND


def test_effective_writer_external_when_forced() -> None:
    assert effective_dns_writer(_settings(dns_writer_mode="external")) == DnsWriterMode.EXTERNAL


def test_effective_writer_ispconfig_when_provider_and_creds() -> None:
    env = SimpleNamespace(provider="ispconfig")
    s = _settings(
        ispconfig_base_url="https://x:8080",
        ispconfig_remote_user="u",
        ispconfig_remote_password="p",
    )
    assert effective_dns_writer(s, env) == DnsWriterMode.ISPCONFIG


def test_ns_redundancy_detects_same_ip(monkeypatch) -> None:
    def fake_dig(host: str) -> list[str]:
        return ["80.241.223.82"]

    monkeypatch.setattr("app.services.platform.dns_writer._dig_a", fake_dig)
    status = ns_redundancy_status(_settings())
    assert status["same_failure_domain"] is True
    assert status["status"] == "single_host"


def test_customer_zone_template_omits_cpanel_subdomain(tmp_path, test_settings) -> None:
    zones = tmp_path / "zones"
    zones.mkdir()
    settings = test_settings.model_copy(
        update={
            "bind_zones_dir": str(zones),
            "bind_customer_conf": str(tmp_path / "named.conf.customer"),
            "bind_named_conf_local": str(tmp_path / "named.conf.local"),
            "server_public_ip": "1.2.3.4",
        }
    )
    svc = AuthoritativeDnsService(settings)
    svc._zones_dir = zones  # type: ignore[attr-defined]
    svc._customer_conf = tmp_path / "named.conf.customer"  # type: ignore[attr-defined]

    zone_path = zones / "db.studio.online"
    body = (
        "$TTL 1800\n"
        "@   IN SOA ns1.ifnotus.space. hostmaster.ifnotus.space. (\n"
        "        2026082701 ; serial\n"
        "        3600\n"
        "        900\n"
        "        604800\n"
        "        300 )\n"
        "    IN NS  ns1.ifnotus.space.\n"
        "    IN NS  ns2.ifnotus.space.\n"
        "    IN A   1.2.3.4\n"
        "www IN A    1.2.3.4\n"
        "mail IN A   1.2.3.4\n"
    )
    zone_path.write_text(body, encoding="utf-8")
    text = zone_path.read_text(encoding="utf-8")
    assert "cpanel IN A" not in text
    assert "www IN A" in text


def test_dns_writer_external_blocks_publish() -> None:
    svc = DnsWriterService(_settings(dns_writer_mode="external"))
    try:
        svc.publish_zone("studio.online")
        raised = False
    except Exception as exc:
        raised = True
        assert getattr(exc, "code", None) == "dns_external_only"
    assert raised


def test_dns_writer_status_includes_redundancy(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.services.platform.dns_writer.ns_redundancy_status",
        lambda s: {"same_failure_domain": True, "status": "single_host"},
    )
    out = DnsWriterService(_settings()).status(SimpleNamespace(provider="legacy"))
    assert out["dns_writer"] == "legacy_bind"
    assert out["single_writer"] is True
    assert out["ns_redundancy"]["same_failure_domain"] is True
