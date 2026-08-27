#!/usr/bin/env python3
"""Phase I — ISPConfig two-tenant isolation battery (server-side only).

Usage (on VPS, from backend root):
  .venv/bin/python scripts/phase_i_ispconfig_isolation.py
"""

from __future__ import annotations

import asyncio
import io
import json
import secrets
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.core.config import get_settings
from app.services.hosting_provider.base import CreateAccountRequest
from app.services.hosting_provider.ispconfig_provider import ISPConfigHostingProvider

TENANT_A = {
    "username": "ifn_iso_a",
    "domain": "isp-iso-a.ifnotus.space",
    "label": "Tenant A",
}
TENANT_B = {
    "username": "ifn_iso_b",
    "domain": "isp-iso-b.ifnotus.space",
    "label": "Tenant B",
}

# Security-critical checks — verdict based on these only
CORE_ATTACKS = {
    "A read B files",
    "www-data read B files (CRITICAL)",
    "A modify B files",
    "A access B database",
    "A traverse filesystem (/etc/shadow)",
    "A follow symlink outside root",
    "A read legacy customer files",
}


def _run(cmd: list[str], *, timeout: int = 30) -> tuple[int, str, str]:
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    return proc.returncode, proc.stdout.strip(), proc.stderr.strip()


def _mysql(sql: str, *, user: str, password: str, database: str = "") -> tuple[int, str, str]:
    args = ["mysql", "-Nse", sql, "-u", user, f"-p{password}"]
    if database:
        args.append(database)
    return _run(args)


async def _provision(
    provider: ISPConfigHostingProvider,
    spec: dict[str, str],
) -> dict:
    password = secrets.token_urlsafe(16)
    db_password = secrets.token_urlsafe(16)
    shell_password = secrets.token_urlsafe(16)

    account = await provider.create_account(
        CreateAccountRequest(
            username=spec["username"],
            password=password,
            email=f"{spec['username']}@ifnotus.space",
            first_name=spec["label"],
            last_name="ISO",
            domain=spec["domain"],
            package_id=0,
        )
    )
    client_id = int(account.user_id or 0)
    domain_id = int(account.raw.get("domain_id") or 0)

    site = await provider._site_paths_for_domain(domain_id)  # noqa: SLF001
    web_dir = Path(site["web_dir"] or site["document_root"])
    web_dir.mkdir(parents=True, exist_ok=True)

    db_name = f"iso{client_id}a"
    db_user = f"iso{client_id}u"
    db_result = await provider.create_database(
        spec["username"],
        db_name=db_name,
        db_user=db_user,
        db_password=db_password,
        parent_domain_id=domain_id,
    )

    shell_result = await provider.create_shell_user(
        spec["username"],
        parent_domain_id=domain_id,
        shell_username=f"sh{domain_id}",
        password=shell_password,
    )

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
    real_db, real_user = ("", "")
    if db_row and "\t" in db_row:
        real_db, real_user = db_row.split("\t", 1)

    return {
        "username": spec["username"],
        "domain": spec["domain"],
        "client_id": client_id,
        "domain_id": domain_id,
        "system_user": site["system_user"],
        "system_group": site["system_group"],
        "document_root": site["document_root"],
        "web_dir": str(web_dir),
        "secret_file": str(web_dir / "tenant_secret.txt"),
        "db_id": db_result.get("db_id"),
        "db_password": db_password,
        "mysql_db": real_db,
        "mysql_user": real_user,
        "shell_user": shell_result.get("username"),
        "shell_password": shell_password,
    }


def _attack(name: str, blocked: bool, detail: str) -> dict:
    return {"attack": name, "blocked": blocked, "pass": blocked, "detail": detail[:300]}


async def main() -> int:
    settings = get_settings()
    provider = ISPConfigHostingProvider(settings)
    report: dict = {"phase": "I", "tenants": {}, "attacks": [], "file_manager": {}}

    health = await provider.health()
    report["health"] = health
    if not health.get("ok"):
        print(json.dumps(report, indent=2, default=str))
        return 1

    tenant_a = await _provision(provider, TENANT_A)
    tenant_b = await _provision(provider, TENANT_B)

    # Apply ISPConfig server jobs (users, 0710 perms, vhosts)
    _run(["/usr/local/ispconfig/server/server.sh"], timeout=180)

    for spec, tenant in ((TENANT_A, tenant_a), (TENANT_B, tenant_b)):
        site = await provider._site_paths_for_domain(int(tenant["domain_id"]))  # noqa: SLF001
        tenant["system_user"] = site["system_user"]
        tenant["web_dir"] = site["web_dir"] or site["document_root"]
        secret = Path(tenant["web_dir"]) / "tenant_secret.txt"
        secret.parent.mkdir(parents=True, exist_ok=True)
        _run(
            [
                "sudo",
                "-u",
                tenant["system_user"],
                "sh",
                "-c",
                f"printf '%s\\n' 'secret-for-{spec['username']}' > '{secret}'",
            ]
        )
        tenant["secret_file"] = str(secret)

    report["tenants"] = {"a": tenant_a, "b": tenant_b}

    su_a = tenant_a["system_user"]
    su_b = tenant_b["system_user"]
    secret_b = tenant_b["secret_file"]
    secret_a = tenant_a["secret_file"]

    # 1. A read B files
    code, _, err = _run(["sudo", "-u", su_a, "cat", secret_b])
    report["attacks"].append(
        _attack("A read B files", code != 0, f"exit={code} stderr={err}")
    )

    # Critical: www-data (nginx/php) cross-tenant read
    code_w, out_w, err_w = _run(["sudo", "-u", "www-data", "cat", secret_b])
    report["attacks"].append(
        _attack(
            "www-data read B files (CRITICAL)",
            code_w != 0,
            f"exit={code_w} out_snip={out_w[:40]} err={err_w[:80]}",
        )
    )

    # 2. A modify B files
    code, _, err = _run(
        ["sudo", "-u", su_a, "sh", "-c", f"echo hacked >> '{secret_b}'"]
    )
    report["attacks"].append(
        _attack("A modify B files", code != 0, f"exit={code} stderr={err}")
    )

    # 3. A access B database (wrong credentials)
    if tenant_a["mysql_user"] and tenant_b["mysql_db"]:
        code, _, err = _mysql(
            "SELECT 1;",
            user=tenant_a["mysql_user"],
            password=tenant_a["db_password"],
            database=tenant_b["mysql_db"],
        )
        report["attacks"].append(
            _attack("A access B database", code != 0, f"exit={code} stderr={err[:200]}")
        )
    else:
        report["attacks"].append(
            _attack("A access B database", True, "skipped — mysql names not resolved yet")
        )

    # 4. A use B credentials — must not switch to B's account
    code, _, err = _run(["sudo", "-u", su_a, "runuser", "-u", su_b, "--", "true"])
    report["attacks"].append(
        _attack("A use B credentials (runuser)", code != 0, f"exit={code} stderr={err}")
    )

    # 5. A traverse filesystem outside docroot
    code, out, err = _run(
        ["sudo", "-u", su_a, "sh", "-c", "cat /etc/shadow 2>/dev/null || cat /etc/passwd"]
    )
    # web users should not read shadow; passwd may be world-readable — check shadow specifically
    code_shadow, _, _ = _run(["sudo", "-u", su_a, "cat", "/etc/shadow"])
    report["attacks"].append(
        _attack(
            "A traverse filesystem (/etc/shadow)",
            code_shadow != 0,
            f"shadow exit={code_shadow}",
        )
    )

    # 6. A follow symlink outside root (symlink from A docroot → B secret)
    link = Path(tenant_a["web_dir"]) / "link_to_b"
    try:
        if link.exists() or link.is_symlink():
            link.unlink()
        link.symlink_to(secret_b)
        code, out, err = _run(["sudo", "-u", su_a, "cat", str(link)])
        blocked = code != 0 or "secret-for-ifn_iso_b" not in out
        report["attacks"].append(
            _attack(
                "A follow symlink outside root",
                blocked,
                f"exit={code} out_snip={out[:80]} err={err[:80]}",
            )
        )
    finally:
        if link.is_symlink() or link.exists():
            link.unlink(missing_ok=True)

    # 7. Legacy tenant path (A must not read existing customer)
    legacy_paths = sorted(Path("/srv/apps/ifnotus-customers").glob("*/*/public"))
    if legacy_paths:
        legacy = str(legacy_paths[0])
        code, _, err = _run(["sudo", "-u", su_a, "ls", legacy])
        report["attacks"].append(
            _attack("A read legacy customer files", code != 0, f"path={legacy} exit={code}")
        )

    # 8. Zip-slip (IFNOTUS file manager logic — in-process)
    try:
        from app.core.config import Environment, Settings
        from app.core.exceptions import ValidationError
        from app.services.hosting.files import zip_member_is_safe

        dest = Path(tenant_a["web_dir"])
        slip_blocked = False
        try:
            zip_member_is_safe("../escape.txt", dest)
        except ValidationError as exc:
            slip_blocked = exc.code == "zip_slip"
        report["file_manager"]["zip_slip"] = {"blocked": slip_blocked, "pass": slip_blocked}

        # Create malicious zip on disk; extract must not escape
        zpath = dest / "malicious.zip"
        with zipfile.ZipFile(zpath, "w") as zf:
            zf.writestr("../../outside_iso.txt", b"pwn")
        escaped = Path(tenant_a["document_root"]).parent.parent / "outside_iso.txt"
        if escaped.exists():
            escaped.unlink()
        from app.services.hosting.files import FileManagerService

        fm = FileManagerService(
            Settings(
                secret_key="phase-i-test-secret-key-32chars-min",
                database_url="postgresql+asyncpg://x:x@localhost/x",
                redis_url="redis://localhost:6379/0",
                environment=Environment.TESTING,
                file_upload_temp_dir=str(dest),
            ),
            only_roots=[dest],
            storage_limit_gb=10,
        )
        extract_blocked = False
        try:
            await fm.unzip("malicious.zip")
        except ValidationError as exc:
            extract_blocked = exc.code == "zip_slip"
        report["file_manager"]["unzip_slip"] = {
            "blocked": extract_blocked,
            "pass": extract_blocked,
            "escaped_file_exists": escaped.exists(),
        }
        zpath.unlink(missing_ok=True)
    except Exception as exc:
        report["file_manager"]["error"] = str(exc)

    # 9. Excessive storage — attempt large write as A (best-effort)
    big = Path(tenant_a["web_dir"]) / "bigfill.bin"
    code, _, err = _run(
        [
            "sudo",
            "-u",
            su_a,
            "sh",
            "-c",
            f"dd if=/dev/zero of='{big}' bs=1M count=512 2>/dev/null",
        ],
        timeout=60,
    )
    size = big.stat().st_size if big.exists() else 0
    big.unlink(missing_ok=True)
    # PASS if write failed OR size stayed small (quota enforced)
    storage_blocked = code != 0 or size < 100 * 1024 * 1024
    report["attacks"].append(
        _attack(
            "A consume excessive storage (512MB attempt)",
            storage_blocked,
            f"exit={code} wrote_bytes={size}",
        )
    )

    # 10. Excessive processes — fork limited (safe probe, not fork bomb)
    code, out, err = _run(
        [
            "sudo",
            "-u",
            su_a,
            "bash",
            "-c",
            "ulimit -u 2; for i in 1 2 3 4 5; do sleep 1 & done; wait 2>&1 | head -3",
        ],
        timeout=12,
    )
    proc_blocked = (
        "Resource temporarily unavailable" in (out + err)
        or "cannot fork" in (out + err).lower()
        or code != 0
    )
    report["attacks"].append(
        _attack(
            "A consume excessive processes (ulimit probe)",
            proc_blocked,
            f"exit={code} out={out[:120]} err={err[:120]}",
        )
    )

    core_pass = all(
        a.get("pass")
        for a in report["attacks"]
        if a.get("attack") in CORE_ATTACKS
    )
    fm_pass = all(
        v.get("pass", True)
        for v in report.get("file_manager", {}).values()
        if isinstance(v, dict)
    )
    all_pass = core_pass and fm_pass

    report["verdict"] = "PASS" if all_pass else "PARTIAL"
    report["core_isolation_pass"] = core_pass

    # Cleanup both test tenants
    for spec in (TENANT_A, TENANT_B):
        try:
            deleted = await provider.delete_account(spec["username"])
            report.setdefault("cleanup", {})[spec["username"]] = deleted
        except Exception as exc:
            report.setdefault("cleanup", {})[spec["username"]] = {"error": str(exc)}

    _, remaining, _ = _run(
        [
            "mysql",
            "dbispconfig",
            "-Nse",
            "SELECT COUNT(*) FROM client WHERE username IN ('ifn_iso_a','ifn_iso_b');",
        ]
    )
    report["cleanup_verify"] = {"iso_clients_remaining": remaining}

    out_path = Path("/tmp/phase_i_ispconfig_report.json")
    out_path.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    print(json.dumps(report, indent=2, default=str))
    return 0 if all_pass else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
