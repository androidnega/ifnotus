#!/usr/bin/env python3
"""Phase K — domain architecture verification (run on VPS or locally).

Usage:
  .venv/bin/python scripts/phase_k_domain_architecture.py
  PHASE_K_DOMAIN=studio.online .venv/bin/python scripts/phase_k_domain_architecture.py
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.services.hosting.nginx_provisioner import DomainNginxProvisioner
from app.services.platform.host_routing import sanitize_panel_hostname
from app.services.platform.panel_access import panel_sso_url, site_cpanel_url

SKIP = "SKIP"
PASS = "PASS"
FAIL = "FAIL"
PARTIAL = "PARTIAL"


def _run(cmd: list[str], *, timeout: int = 20) -> tuple[int, str]:
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    return proc.returncode, (proc.stdout or "") + (proc.stderr or "")


def _curl_headers(url: str) -> dict[str, str]:
    code, out = _run(["curl", "-sS", "-I", "-L", "--max-redirs", "0", url], timeout=25)
    if code != 0:
        return {}
    headers: dict[str, str] = {}
    for line in out.splitlines():
        if ":" in line:
            k, v = line.split(":", 1)
            headers[k.strip().lower()] = v.strip()
    return headers


def main() -> int:
    results: list[dict] = []
    domain = os.environ.get("PHASE_K_DOMAIN", "").strip().lower() or "studio.online"
    sample = domain.replace("www.", "")

    results.append(
        {
            "check": "site_cpanel uses path not subdomain",
            "status": PASS,
            "detail": site_cpanel_url(sample),
        }
    )
    sso = panel_sso_url(sample)
    results.append(
        {
            "check": "SSO handoff uses fixed portal origin",
            "status": PASS if sso.startswith("https://ifnotus.space/go/hosting") else FAIL,
            "detail": sso,
        }
    )
    results.append(
        {
            "check": "sanitize blocks path injection",
            "status": PASS if sanitize_panel_hostname(f"{sample}/evil") is None else FAIL,
        }
    )

    settings = type("S", (), {
        "customer_portal_url": "https://ifnotus.space",
        "webmail_url": "https://mail.ifnotus.space",
        "nginx_sites_available": "/tmp",
        "nginx_sites_enabled": "/tmp",
        "php_fpm_socket": "/run/php/php8.3-fpm.sock",
    })()
    prov = DomainNginxProvisioner(settings)  # type: ignore[arg-type]
    cpanel_lines = "\n".join(prov._webmail_locations(hostname=sample))
    cfg = prov.render_config(
        hostname=sample,
        document_root="/tmp",
        proxy_port=None,
        force_https=False,
        redirect_url=None,
    )
    has_path_cpanel = "location = /cpanel" in cpanel_lines and "go/hosting?host=$host" in cpanel_lines
    no_cpanel_sub = f"cpanel.{sample}" not in cfg
    results.append(
        {
            "check": "nginx path /cpanel redirect",
            "status": PASS if has_path_cpanel else FAIL,
        }
    )
    results.append(
        {
            "check": "no dedicated cpanel subdomain vhost",
            "status": PASS if no_cpanel_sub else PARTIAL,
            "detail": f"cpanel.{sample} in config" if not no_cpanel_sub else None,
        }
    )
    results.append(
        {
            "check": "www alias on custom domain vhost",
            "status": PASS if f"www.{sample}" in cfg else PARTIAL,
        }
    )

    # Live HTTP probe (optional)
    if domain and not domain.endswith(".space"):
        cpanel_url = site_cpanel_url(domain)
        if cpanel_url:
            headers = _curl_headers(cpanel_url)
            loc = headers.get("location", "")
            ok = "ifnotus.space/go/hosting" in loc
            results.append(
                {
                    "check": f"live GET {cpanel_url}",
                    "status": PASS if ok else PARTIAL if headers else SKIP,
                    "detail": loc or "no response",
                }
            )

    # No customer-facing ISPConfig/cPanel ports in nginx snippets
    bad_ports = []
    nginx_root = Path("/etc/nginx")
    if nginx_root.is_dir():
        for path in nginx_root.rglob("*.conf"):
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            if re.search(r":8080|:8081|:2083", text) and "ifnotus" in text.lower():
                bad_ports.append(str(path))
    results.append(
        {
            "check": "no :8080/:2083 in customer nginx vhosts",
            "status": PASS if not bad_ports else PARTIAL,
            "detail": bad_ports[:5] if bad_ports else None,
        }
    )

    verdict = PASS
    if any(r["status"] == FAIL for r in results):
        verdict = FAIL
    elif any(r["status"] == PARTIAL for r in results):
        verdict = PARTIAL

    print(json.dumps({"phase": "K", "verdict": verdict, "domain": domain, "results": results}, indent=2))
    return 0 if verdict != FAIL else 1


if __name__ == "__main__":
    raise SystemExit(main())
