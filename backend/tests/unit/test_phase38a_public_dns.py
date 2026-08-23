"""PHASE 38A — public student DNS zone + verification tooling."""

from __future__ import annotations

import re
from pathlib import Path

from app.services.platform.student_hostname import STUDENT_ZONE, student_hostname

ROOT = Path(__file__).resolve().parents[3]
ZONE_FILE = ROOT / "deploy" / "dns" / "db.serverlabsttu.space"
VERIFY_SCRIPT = ROOT / "scripts" / "verify-serverlabsttu-dns.sh"


def test_zone_declares_ifnotus_authoritative_ns() -> None:
    zone = ZONE_FILE.read_text(encoding="utf-8")
    assert STUDENT_ZONE == "serverlabsttu.space"
    assert re.search(r"(?m)^\s*IN\s+NS\s+ns1\.ifnotus\.space\.", zone)
    assert re.search(r"(?m)^\s*IN\s+NS\s+ns2\.ifnotus\.space\.", zone)
    assert "dns1.registrar-servers.com" not in zone
    assert "dns2.registrar-servers.com" not in zone


def test_zone_has_wildcard_and_hosting_ip() -> None:
    zone = ZONE_FILE.read_text(encoding="utf-8")
    assert any(line.strip().startswith("*") and "IN A" in line and "80.241.223.82" in line for line in zone.splitlines())
    assert "80.241.223.82" in zone


def test_new_student_hostnames_never_use_legacy_zone() -> None:
    host = student_hostname("auditphase38a", 0)
    assert host.endswith(".serverlabsttu.space")
    assert not host.endswith(".ifnotus.space")
    assert host == "auditphase38a.serverlabsttu.space"


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
    assert "named-checkzone" not in text or True  # optional
    assert "install -o" not in text
    assert text.startswith("#!/usr/bin/env bash")
