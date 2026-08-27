#!/usr/bin/env python3
"""Phase H — ISPConfig first test tenant lifecycle (server-side only).

Usage (on VPS, from backend root):
  .venv/bin/python scripts/phase_h_ispconfig_lifecycle.py
"""

from __future__ import annotations

import asyncio
import json
import os
import secrets
import subprocess
import sys
import time
from pathlib import Path

# Ensure backend package is importable when run from /srv/apps/ifnotus/backend
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.core.config import get_settings
from app.services.hosting_provider.base import CreateAccountRequest
from app.services.hosting_provider.ispconfig_provider import ISPConfigHostingProvider

DOMAIN = "isp-test.ifnotus.space"
USERNAME = "ifn_isp_test_h"
PLAN = "student-basic-test"


def _run(cmd: list[str], *, timeout: int = 30) -> tuple[int, str, str]:
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    return proc.returncode, proc.stdout.strip(), proc.stderr.strip()


def _curl(url: str, *, insecure: bool = False) -> tuple[int, str]:
    cmd = ["curl", "-sS", "-o", "/dev/stdout", "-w", "%{http_code}", "--max-time", "20"]
    if insecure:
        cmd.append("-k")
    cmd.append(url)
    code, out, err = _run(cmd)
    if code != 0:
        return 0, err or out
    if out and out[-3:].isdigit():
        return int(out[-3:]), out[:-3]
    return 0, out


async def main() -> int:
    settings = get_settings()
    provider = ISPConfigHostingProvider(settings)
    password = secrets.token_urlsafe(16)
    ftp_password = secrets.token_urlsafe(16)
    shell_password = secrets.token_urlsafe(16)
    db_password = secrets.token_urlsafe(16)

    report: dict = {
        "phase": "H",
        "domain": DOMAIN,
        "username": USERNAME,
        "steps": {},
        "provider_ids": {},
    }

    # 0. Health
    health = await provider.health()
    report["steps"]["health"] = health
    if not health.get("ok"):
        print(json.dumps(report, indent=2, default=str))
        return 1

    # 1. Create account + website
    req = CreateAccountRequest(
        username=USERNAME,
        password=password,
        email=f"{USERNAME}@ifnotus.space",
        first_name="ISP",
        last_name="Test H",
        domain=DOMAIN,
        package_id=0,
        php_version="8.2",
    )
    try:
        account = await provider.create_account(req)
        report["provider_ids"]["client_id"] = account.user_id
        report["provider_ids"]["domain_id"] = account.raw.get("domain_id")
        report["steps"]["create_account"] = {"ok": True, "raw": account.raw}
    except Exception as exc:
        report["steps"]["create_account"] = {"ok": False, "error": str(exc)}
        print(json.dumps(report, indent=2, default=str))
        return 1

    client_id = int(account.user_id or 0)
    domain_id = int(account.raw.get("domain_id") or 0)

    # Wait for ISPConfig to write nginx + docroot
    time.sleep(8)

    # Resolve document root from ISPConfig DB via mysql CLI
    _, docroot, _ = _run(
        [
            "mysql",
            "dbispconfig",
            "-Nse",
            f"SELECT document_root FROM web_domain WHERE domain_id={domain_id};",
        ]
    )
    report["provider_ids"]["document_root"] = docroot
    web_root = Path(docroot) if docroot else Path(f"/var/www/clients/client{client_id}/web{domain_id}")
    serve_dir = web_root / "web"
    serve_dir.mkdir(parents=True, exist_ok=True)
    index = serve_dir / "index.html"
    index.write_text(
        "<!DOCTYPE html><html><body><h1>IFNOTUS Phase H ISPConfig Test</h1></body></html>\n",
        encoding="utf-8",
    )
    report["steps"]["upload_index"] = {"ok": True, "path": str(index), "serve_dir": str(serve_dir)}

    # nginx reload if needed
    _run(["nginx", "-t"])
    _run(["systemctl", "reload", "nginx"])
    time.sleep(5)

    status, body = _curl(f"http://{DOMAIN}/")
    report["steps"]["serve_http"] = {
        "status": status,
        "body_snip": body[:120],
        "contains_phase_h_marker": "Phase H ISPConfig Test" in body,
    }

    # 2. SSL
    try:
        ssl_result = await provider.issue_ssl_for_domain_id(
            domain_id=domain_id, client_id=client_id, domain=DOMAIN
        )
        report["steps"]["issue_ssl"] = {"ok": True, "result": ssl_result}
    except Exception as exc:
        report["steps"]["issue_ssl"] = {"ok": False, "error": str(exc)}

    # Allow LE + ISPConfig cron to finish
    time.sleep(25)
    _run(["systemctl", "reload", "nginx"])
    status_https, body_https = _curl(f"https://{DOMAIN}/", insecure=True)
    report["steps"]["serve_https"] = {
        "status": status_https,
        "body_snip": body_https[:120],
        "contains_phase_h_marker": "Phase H ISPConfig Test" in body_https,
    }

    # 3. Database
    db_name = f"c{client_id}phh"
    db_user = f"c{client_id}u"
    try:
        db_result = await provider.create_database(
            USERNAME, db_name=db_name, db_user=db_user, db_password=db_password,
            parent_domain_id=domain_id,
        )
        report["provider_ids"]["db_id"] = db_result.get("db_id")
        report["provider_ids"]["db_user_id"] = db_result.get("db_user_id")
        report["steps"]["create_database"] = {"ok": True, "result": db_result}

        # Resolve actual MySQL names (ISPConfig prefixes)
        _, db_row, _ = _run(
            [
                "mysql",
                "dbispconfig",
                "-Nse",
                f"SELECT CONCAT(IFNULL(d.database_name_prefix,''), d.database_name), "
                f"CONCAT(IFNULL(u.database_user_prefix,''), u.database_user) "
                f"FROM web_database d "
                f"JOIN web_database_user u ON d.database_user_id=u.database_user_id "
                f"WHERE d.database_id={db_result.get('db_id')};",
            ]
        )
        report["provider_ids"]["mysql_names"] = db_row
        time.sleep(3)
        if db_row:
            parts = db_row.split("\t")
            if len(parts) >= 2:
                real_db, real_user = parts[0], parts[1]
                code, out, err = _run(
                    [
                        "mysql",
                        "-Nse",
                        f"CREATE TABLE IF NOT EXISTS phase_h_check (id INT PRIMARY KEY); "
                        f"INSERT IGNORE INTO phase_h_check VALUES (1); SELECT id FROM phase_h_check LIMIT 1;",
                        "-u",
                        real_user,
                        f"-p{db_password}",
                        real_db,
                    ]
                )
                report["steps"]["connect_database"] = {
                    "ok": code == 0 and out.strip() == "1",
                    "stdout": out,
                    "stderr": err[:200],
                    "real_db": real_db,
                    "real_user": real_user,
                }
        else:
            report["steps"]["connect_database"] = {"ok": False, "error": "could not resolve mysql names"}
    except Exception as exc:
        report["steps"]["create_database"] = {"ok": False, "error": str(exc)}

    # 4. SFTP shell user
    shell_name = f"web{domain_id}"
    shell_result: dict = {}
    try:
        shell_result = await provider.create_shell_user(
            USERNAME,
            parent_domain_id=domain_id,
            shell_username=shell_name,
            password=shell_password,
        )
        report["provider_ids"]["shell_user_id"] = shell_result.get("shell_user_id")
        report["steps"]["create_shell_user"] = {"ok": True, "result": shell_result}
    except Exception as exc:
        report["steps"]["create_shell_user"] = {"ok": False, "error": str(exc)}

    # 5. FTP user
    ftp_name = f"ftp{domain_id}h"
    try:
        ftp_result = await provider.create_ftp_user(
            USERNAME,
            parent_domain_id=domain_id,
            ftp_username=ftp_name,
            password=ftp_password,
        )
        report["provider_ids"]["ftp_user_id"] = ftp_result.get("ftp_user_id")
        report["steps"]["create_ftp_user"] = {"ok": True, "result": ftp_result}
    except Exception as exc:
        report["steps"]["create_ftp_user"] = {"ok": False, "error": str(exc)}

    # 6. Isolation — shell user must not read legacy tenant path
    legacy_paths = sorted(Path("/srv/apps/ifnotus-customers").glob("*/*/public"))
    legacy_target = str(legacy_paths[0]) if legacy_paths else ""
    iso_ok = True
    iso_detail: dict = {}
    if legacy_target and shell_result.get("shell_user_id"):
        # Resolve ISPConfig system user for the site
        _, sys_user, _ = _run(
            [
                "mysql",
                "dbispconfig",
                "-Nse",
                f"SELECT system_user FROM web_domain WHERE domain_id={domain_id};",
            ]
        )
        iso_detail["system_user"] = sys_user
        if sys_user:
            code, _, err = _run(["sudo", "-u", sys_user, "test", "-r", legacy_target])
            iso_ok = code != 0
            iso_detail.update({"legacy_path": legacy_target, "readable": code == 0, "stderr": err[:120]})
        else:
            iso_detail["skipped"] = "no system_user yet"
    elif legacy_target:
        iso_detail = {"legacy_path": legacy_target, "skipped": "shell user not created"}
    report["steps"]["verify_isolation"] = {"ok": iso_ok, **iso_detail}

    # 7. Suspend / unsuspend
    try:
        await provider.suspend_account(USERNAME)
        time.sleep(5)
        _run(["systemctl", "reload", "nginx"])
        _, active_flag, _ = _run(
            [
                "mysql",
                "dbispconfig",
                "-Nse",
                f"SELECT active FROM web_domain WHERE domain_id={domain_id};",
            ]
        )
        status_susp, body_susp = _curl(f"http://{DOMAIN}/")
        report["steps"]["suspend"] = {
            "ok": True,
            "db_active": active_flag,
            "http_status_after": status_susp,
            "body_snip": body_susp[:80],
        }
    except Exception as exc:
        report["steps"]["suspend"] = {"ok": False, "error": str(exc)}

    try:
        await provider.unsuspend_account(USERNAME)
        time.sleep(4)
        _run(["systemctl", "reload", "nginx"])
        status_uns, body_uns = _curl(f"http://{DOMAIN}/")
        report["steps"]["unsuspend"] = {
            "ok": True,
            "http_status_after": status_uns,
            "body_snip": body_uns[:80],
        }
    except Exception as exc:
        report["steps"]["unsuspend"] = {"ok": False, "error": str(exc)}

    # 8. Usage
    try:
        usage = await provider.get_usage(USERNAME)
        report["steps"]["get_usage"] = {
            "disk_used": usage.disk_used,
            "disk_limit": usage.disk_limit,
            "raw_keys": list((usage.raw or {}).keys()),
        }
    except Exception as exc:
        report["steps"]["get_usage"] = {"ok": False, "error": str(exc)}

    # 9. Cleanup — delete test environment
    try:
        deleted = await provider.delete_account(USERNAME)
        report["steps"]["delete_account"] = {"ok": True, "result": deleted}
    except Exception as exc:
        report["steps"]["delete_account"] = {"ok": False, "error": str(exc)}

    # Verify cleanup
    _, remaining, _ = _run(
        [
            "mysql",
            "dbispconfig",
            "-Nse",
            f"SELECT COUNT(*) FROM client WHERE username='{USERNAME}';",
        ]
    )
    report["steps"]["cleanup_verify"] = {"clients_remaining": remaining}

    out_path = Path("/tmp/phase_h_ispconfig_report.json")
    out_path.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    print(json.dumps(report, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
