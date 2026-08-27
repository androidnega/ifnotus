"""PHASE 38A — public student DNS zone + verification tooling."""

from __future__ import annotations

import re
from pathlib import Path

from app.services.platform.student_hostname import STUDENT_ZONE, student_hostname

ROOT = Path(__file__).resolve().parents[3]
ZONE_FILE = ROOT / "deploy" / "dns" / "db.ifnotus.space"
VERIFY_SCRIPT = ROOT / "scripts" / "verify-ifnotus-platform-dns.sh"


def test_zone_declares_ifnotus_authoritative_ns() -> None:
    zone = ZONE_FILE.read_text(encoding="utf-8")
    assert STUDENT_ZONE == "ifnotus.space"
    assert re.search(r"(?m)^\s*IN\s+NS\s+ns1\.ifnotus\.space\.", zone)
    assert re.search(r"(?m)^\s*IN\s+NS\s+ns2\.ifnotus\.space\.", zone)
    assert "dns1.registrar-servers.com" not in zone
    assert "dns2.registrar-servers.com" not in zone


def test_zone_has_wildcard_and_hosting_ip() -> None:
    zone = ZONE_FILE.read_text(encoding="utf-8")
    assert any(line.strip().startswith("*") and "IN A" in line and "80.241.223.82" in line for line in zone.splitlines())
    assert "80.241.223.82" in zone
    assert "cpanel IN A" in zone or re.search(r"(?m)^cpanel\s+IN\s+A", zone)


def test_new_student_hostnames_never_use_legacy_zone() -> None:
    host = student_hostname("auditphase38a", 0)
    assert host.endswith(".ifnotus.space")
    assert not host.endswith(".serverlabsttu.space")
    assert host == "auditphase38a.ifnotus.space"


def test_verify_script_exists_and_is_safe() -> None:
    text = VERIFY_SCRIPT.read_text(encoding="utf-8")
    assert VERIFY_SCRIPT.exists()
    assert "dig" in text
    assert "1.1.1.1" in text
    assert "ns1.ifnotus.space" in text
    assert "ns2.ifnotus.space" in text
    # Non-destructive: no registrar API / nsupdate / zone overwrite
    assert "nsupdate" not in text
    assert "namecheap" not in text.lower()
    assert "install -o" not in text
    assert text.startswith("#!/usr/bin/env bash")
    assert "audittest" in text  # random wildcard probe label


def test_install_ifnotus_zone_script_exists() -> None:
    script = ROOT / "deploy" / "dns" / "install-ifnotus-zone.sh"
    frag = ROOT / "deploy" / "dns" / "named.conf.ifnotus.space"
    assert script.is_file()
    body = script.read_text(encoding="utf-8")
    assert "db.ifnotus.space" in body
    assert "named-checkzone ifnotus.space" in body
    assert frag.is_file()
    assert 'zone "ifnotus.space"' in frag.read_text(encoding="utf-8")
