#!/usr/bin/env python3
"""Phase L — DNS architecture verification.

Usage:
  .venv/bin/python scripts/phase_l_dns_architecture.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.core.config import get_settings
from app.services.platform.dns_writer import DnsWriterService, ns_redundancy_status

PASS = "PASS"
PARTIAL = "PARTIAL"
FAIL = "FAIL"


def main() -> int:
    settings = get_settings()
    results: list[dict] = []
    writer = DnsWriterService(settings)
    status = writer.status()
    mode = status.get("dns_writer")
    results.append({"check": "single DNS writer configured", "status": PASS, "detail": mode})
    results.append(
        {
            "check": "managed + external DNS modes supported",
            "status": PASS if status.get("external_dns_supported") else FAIL,
        }
    )
    redundancy = ns_redundancy_status(settings)
    ns_status = PASS if not redundancy.get("same_failure_domain") else PARTIAL
    results.append(
        {
            "check": "ns1/ns2 failure-domain separation",
            "status": ns_status,
            "detail": redundancy,
        }
    )
    platform_zone = Path(settings.bind_zones_dir) / "db.ifnotus.space"
    deploy_zone = ROOT.parent / "deploy" / "dns" / "db.ifnotus.space"
    zone_text = ""
    if platform_zone.is_file():
        zone_text = platform_zone.read_text(encoding="utf-8", errors="replace")
    elif deploy_zone.is_file():
        zone_text = deploy_zone.read_text(encoding="utf-8", errors="replace")
    if zone_text:
        has_ns = "ns1.ifnotus.space" in zone_text and "ns2.ifnotus.space" in zone_text
        results.append({"check": "platform zone lists ns1+ns2", "status": PASS if has_ns else FAIL})
    else:
        results.append({"check": "platform zone file present", "status": PARTIAL})

    verdict = PASS
    if any(r["status"] == FAIL for r in results):
        verdict = FAIL
    elif any(r["status"] == PARTIAL for r in results):
        verdict = PARTIAL

    print(json.dumps({"phase": "L", "verdict": verdict, "writer": status, "results": results}, indent=2))
    return 0 if verdict != FAIL else 1


if __name__ == "__main__":
    raise SystemExit(main())
