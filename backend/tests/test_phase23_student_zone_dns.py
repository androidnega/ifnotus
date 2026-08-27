"""PHASE 23 — student zone is platform-owned, not a customer BIND zone."""

from pathlib import Path

from app.services.platform.authoritative_dns import AuthoritativeDnsService
from app.services.platform.student_hostname import RESERVED_LABELS, STUDENT_ZONE


def test_zone_template_lists_reserved_and_wildcard() -> None:
    root = Path(__file__).resolve().parents[2]
    zone = (root / "deploy" / "dns" / "db.ifnotus.space").read_text(encoding="utf-8")
    assert any(line.strip().startswith("*") and "IN A" in line for line in zone.splitlines())
    for label in ("www", "mail", "cpanel", "ns1", "ns2"):
        assert label in RESERVED_LABELS
        assert label in zone


def test_legacy_named_conf_still_declares_serverlabsttu() -> None:
    root = Path(__file__).resolve().parents[2]
    conf = (root / "deploy" / "dns" / "named.conf.serverlabsttu.space").read_text(encoding="utf-8")
    assert 'zone "serverlabsttu.space"' in conf
    assert "db.serverlabsttu.space" in conf


def test_existing_customer_zones_excludes_student_apex(tmp_path, test_settings) -> None:
    zones = tmp_path / "zones"
    zones.mkdir()
    (zones / "db.ifnotus.space").write_text("x", encoding="utf-8")
    (zones / f"db.{STUDENT_ZONE}").write_text("x", encoding="utf-8")
    (zones / "db.customer.example").write_text("x", encoding="utf-8")

    svc = AuthoritativeDnsService(test_settings)
    svc._zones_dir = zones  # type: ignore[attr-defined]
    found = svc._existing_customer_zones()
    assert "customer.example" in found
    assert "ifnotus.space" not in found
    assert STUDENT_ZONE not in found
