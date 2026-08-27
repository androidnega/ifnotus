#!/usr/bin/env python3
"""Scan / prepare legacy sites (csdttu.online, votebridge.online, …) for tenant import.

This is a controlled discovery tool. It does NOT move traffic or rewrite live configs
unless --execute is passed (execute still requires explicit --domain).

Usage:
  python scripts/import-existing-site.py --scan
  python scripts/import-existing-site.py --dry-run --domain csdttu.online
  python scripts/import-existing-site.py --dry-run --domain votebridge.online
"""

from __future__ import annotations

import argparse
import json
import socket
from pathlib import Path

KNOWN = ("csdttu.online", "votebridge.online", "documento.csdttu.online", "neckpressing.online")
NGINX_ENABLED = Path("/etc/nginx/sites-enabled")
WWW = Path("/var/www")
SRV = Path("/srv/apps")


def resolve_ip(host: str) -> list[str]:
    try:
        infos = socket.getaddrinfo(host, 80, type=socket.SOCK_STREAM)
        return sorted({i[4][0] for i in infos})
    except OSError as exc:
        return [f"error:{exc}"]


def find_docroots(domain: str) -> list[str]:
    hits: list[str] = []
    for base in (WWW, SRV):
        if not base.exists():
            continue
        for path in base.rglob("*"):
            if path.name in {domain, domain.replace(".", "-")} and path.is_dir():
                hits.append(str(path))
            if path.is_file() and path.name in {"index.php", "index.html", "manage.py", "package.json"}:
                # cheap: parent name matches domain fragment
                if domain.split(".")[0] in str(path.parent).lower():
                    hits.append(str(path.parent))
    # unique preserve order
    seen: set[str] = set()
    out: list[str] = []
    for h in hits:
        if h not in seen:
            seen.add(h)
            out.append(h)
    return out[:20]


def nginx_mentions(domain: str) -> list[str]:
    if not NGINX_ENABLED.exists():
        return []
    files = []
    for conf in NGINX_ENABLED.iterdir():
        try:
            text = conf.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if domain in text:
            files.append(str(conf))
    return files


def audit_domain(domain: str) -> dict:
    label = domain.split(".")[0]
    return {
        "domain": domain,
        "proposed_hosting_name": label[:12],
        "dns_a": resolve_ip(domain),
        "nginx_files": nginx_mentions(domain),
        "candidate_paths": find_docroots(domain),
        "notes": [
            "Assign hosting_name via scripts/assign-hosting-names.py (DB identity only).",
            "Do NOT restructure live paths automatically when hosting_name is added.",
            "Re-issue nginx via DomainNginxProvisioner after tenant import.",
            "Inspect runtime (PHP/Django/Node) before cutover — votebridge may need workers/redis.",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--scan", action="store_true")
    parser.add_argument("--dry-run", action="store_true", default=True)
    parser.add_argument("--domain", action="append", default=[])
    parser.add_argument("--execute", action="store_true", help="Reserved — not implemented yet (safety).")
    args = parser.parse_args()
    domains = args.domain or (list(KNOWN) if args.scan else [])
    if not domains:
        print("Pass --scan or --domain <name>")
        return 2
    if args.execute:
        print("EXECUTE is intentionally disabled in this scaffold. Use --dry-run audits first.")
        return 3
    report = [audit_domain(d) for d in domains]
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
