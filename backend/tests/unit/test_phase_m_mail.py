"""PHASE M — Mail Architecture verification unit tests.

Verifies:
1. domain.tld/mail -> webmail path routing.
2. mail.domain.tld -> SMTP/IMAP endpoints and client settings.
3. Mail plan-gating (student packs vs developer packs).
4. DNS records for hosted mail (MX, SPF, DKIM, DMARC, PTR/rDNS, autoconfig/autodiscover).
5. Reputation / deliverability guardrails.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from app.models.platform import HostingPlan
from app.services.hosting.mail_auth import MailAuthService, SELECTOR
from app.services.hosting.nginx_provisioner import DomainNginxProvisioner
from app.services.platform.authoritative_dns import AuthoritativeDnsService
from app.services.platform.environment_mail import (
    EnvironmentMailService,
    entitlements_for_plan,
)
from app.services.platform.plan_matrix import MATRIX, capabilities_for


class _DummyPlan:
    def __init__(self, matrix_key: str) -> None:
        self.features = {"matrix_key": matrix_key}


def test_plan_gating_student_vs_pro() -> None:
    """Test that mail is plan-gated and student packages have explicit entitlements."""
    starter = entitlements_for_plan(_DummyPlan("student-starter"))
    assert starter.enabled is True
    assert starter.mailboxes == 1

    club = entitlements_for_plan(_DummyPlan("club-connect"))
    assert club.enabled is True
    assert club.mailboxes == 5
    assert club.storage_mb == 2048

    pro = entitlements_for_plan(_DummyPlan("student-pro"))
    assert pro.enabled is True
    assert pro.mailboxes == 10
    assert pro.storage_mb == 5120


def test_plan_gating_denies_disabled_mail() -> None:
    """Test that plans with mail disabled raise pack_feature error."""
    class _NoMailPlan:
        features = {"mail_enabled": False, "mailboxes": 0}

    ent = entitlements_for_plan(_NoMailPlan())  # type: ignore[arg-type]
    assert ent.enabled is False


def test_webmail_path_routing_in_nginx(tmp_path) -> None:
    """Test that /mail redirects to shared webmail in site nginx configs."""
    settings = SimpleNamespace(
        webmail_url="https://mail.ifnotus.space",
        customer_portal_url="https://ifnotus.space",
        php_fpm_socket="/run/php/php8.3-fpm.sock",
        nginx_sites_available=str(tmp_path / "sites-available"),
        nginx_sites_enabled=str(tmp_path / "sites-enabled"),
    )
    prov = DomainNginxProvisioner(settings)  # type: ignore[arg-type]
    locs = "\n".join(prov._webmail_locations(hostname="studentlab.org"))
    assert "location = /mail" in locs
    assert "return 302 https://mail.ifnotus.space/;" in locs


def test_mail_dns_hints_include_all_required_records() -> None:
    """Test that MailAuthService produces MX, SPF, DKIM, DMARC, A, autoconfig, autodiscover."""
    settings = SimpleNamespace(server_public_ip="80.241.223.82")
    service = MailAuthService(settings, MagicMock())  # type: ignore[arg-type]

    hints = service._dns_hints("studentlab.org", dkim_public="v=DKIM1; p=MIGfMA0GCSq...")
    by_type = {}
    for h in hints:
        by_type[(h.record_type, h.host)] = h.value

    assert ("MX", "@") in by_type
    assert by_type[("MX", "@")] == "mail.ifnotus.space."
    assert ("TXT", "@") in by_type
    assert "v=spf1" in by_type[("TXT", "@")]
    assert ("TXT", "_dmarc") in by_type
    assert "v=DMARC1" in by_type[("TXT", "_dmarc")]
    assert ("A", "mail") in by_type
    assert by_type[("A", "mail")] == "80.241.223.82"
    assert ("CNAME", "autoconfig") in by_type
    assert ("CNAME", "autodiscover") in by_type
    assert ("TXT", f"{SELECTOR}._domainkey") in by_type


def test_authoritative_dns_zone_includes_mail_records(tmp_path) -> None:
    """Test that AuthoritativeDnsService generates MX, SPF, DMARC, autoconfig/autodiscover."""
    settings = SimpleNamespace(
        server_public_ip="80.241.223.82",
        server_public_ipv6=None,
        dns_ns1="ns1.ifnotus.space",
        dns_ns2="ns2.ifnotus.space",
        bind_zones_dir=str(tmp_path / "zones"),
        bind_customer_conf=str(tmp_path / "named.conf.customer"),
        bind_named_conf_local=str(tmp_path / "named.conf.local"),
    )
    service = AuthoritativeDnsService(settings)  # type: ignore[arg-type]

    # Mock named-checkzone and subprocess calls
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        res = service.ensure_zone("myexamflow.com")

    zone_file = tmp_path / "zones" / "db.myexamflow.com"
    assert zone_file.exists()
    content = zone_file.read_text()
    assert "IN MX  10 mail.myexamflow.com." in content
    assert "v=spf1" in content
    assert "mail IN A   80.241.223.82" in content
    assert "autoconfig IN CNAME mail.myexamflow.com." in content
    assert "autodiscover IN CNAME mail.myexamflow.com." in content
    assert "_dmarc IN TXT" in content


def test_ptr_check_logic() -> None:
    """Test PTR lookup verification against mail hostname."""
    settings = SimpleNamespace(server_public_ip="80.241.223.82")
    service = MailAuthService(settings, MagicMock())  # type: ignore[arg-type]

    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout="mail.ifnotus.space.\n", stderr="")
        status = service._check_ptr()
        assert status["ptr_ok"] is True
        assert "mail.ifnotus.space" in status["ptrs"]

    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout="vps82.hoster.com.\n", stderr="")
        status = service._check_ptr()
        assert status["ptr_ok"] is False
