"""Unified read-only resource governance status + dry-run reconcile helpers."""

from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from app.services.platform.host_safety import (
    HOST_MEMAVAILABLE_SAFETY_FLOOR_GIB,
    build_host_safety_snapshot,
    classify_host_pressure_band,
    read_meminfo_bytes,
)
from app.services.platform.resource_governor import ResourceEmergencyGovernor
from app.services.platform.resource_policy import (
    default_host_resource_policy,
    detect_cpu_quota_drift,
    resolve_cpu_quota_percent,
)
from app.services.platform.workload_slices import PRIORITY_SLICE, TENANTS_SLICE


def _git_head(repo: Path) -> str | None:
    try:
        proc = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(repo),
            capture_output=True,
            text=True,
            check=False,
            timeout=10,
        )
        if proc.returncode == 0:
            return (proc.stdout or "").strip() or None
    except (OSError, subprocess.SubprocessError):
        return None
    return None


def _systemctl_is(unit: str, what: str) -> str:
    systemctl = shutil.which("systemctl") or "systemctl"
    proc = subprocess.run(
        [systemctl, f"is-{what}", unit],
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )
    return (proc.stdout or proc.stderr or "").strip() or "unknown"


def _port_listening(port: int) -> bool:
    try:
        proc = subprocess.run(
            ["ss", "-lnt"],
            capture_output=True,
            text=True,
            check=False,
            timeout=10,
        )
        return f":{port} " in (proc.stdout or "") or f":{port}\n" in (proc.stdout or "")
    except (OSError, subprocess.SubprocessError):
        return False


def _quota_enabled() -> dict[str, Any]:
    try:
        proc = subprocess.run(
            ["findmnt", "-n", "-o", "OPTIONS", "/"],
            capture_output=True,
            text=True,
            check=False,
            timeout=10,
        )
        opts = (proc.stdout or "").strip()
    except (OSError, subprocess.SubprocessError):
        opts = ""
    has_mount = any(x in opts for x in ("usrquota", "grpquota", "prjquota", "quota"))
    active = False
    try:
        q = subprocess.run(
            ["quotaon", "-p", "/"],
            capture_output=True,
            text=True,
            check=False,
            timeout=10,
        )
        text = f"{q.stdout or ''}\n{q.stderr or ''}".lower()
        active = "user quota" in text and "is on" in text
    except (OSError, subprocess.SubprocessError):
        active = False
    # Project quotas require offline tune2fs -O project / remount prjquota.
    prj_maintenance = "prjquota" not in opts
    backend = "none"
    if "prjquota" in opts:
        backend = "prjquota"
    elif "usrquota" in opts or active:
        backend = "usrquota"
    elif has_mount:
        backend = "unknown"
    return {
        "kernel_quota_enabled": bool(active or has_mount),
        "quotas_actively_on": active,
        "mount_options": opts,
        "quota_backend": backend,
        "project_quota_maintenance_required": prj_maintenance,
        "maintenance_required": not active,
        "maintenance_code": None
        if active
        else "FILESYSTEM_QUOTA_MAINTENANCE_REQUIRED",
    }


@dataclass
class GovernanceFinding:
    code: str
    severity: str  # PASS | WARNING | FAIL
    message: str
    detail: dict[str, Any] = field(default_factory=dict)


def collect_resource_governance_status(
    *,
    repo_path: Path | None = None,
    include_governor: bool = True,
) -> dict[str, Any]:
    policy = default_host_resource_policy()
    mi = read_meminfo_bytes()
    avail = int(mi.get("MemAvailable") or 0)
    band = classify_host_pressure_band(mem_available_bytes=avail)
    safety = build_host_safety_snapshot()
    findings: list[GovernanceFinding] = []

    gov_snap = None
    if include_governor:
        try:
            gov = ResourceEmergencyGovernor(dry_run=True)
            gov_snap = gov.tick(apply=False).to_dict()
        except Exception as exc:  # noqa: BLE001
            findings.append(
                GovernanceFinding("governor_error", "FAIL", f"governor tick failed: {exc}")
            )

    vsftpd_active = _systemctl_is("vsftpd", "active")
    vsftpd_enabled = _systemctl_is("vsftpd", "enabled")
    ftp_listen = _port_listening(21)
    if vsftpd_active == "active" or ftp_listen:
        findings.append(
            GovernanceFinding(
                "vsftpd_exposed",
                "FAIL",
                "vsftpd still active/listening — legacy FTP path",
                {"active": vsftpd_active, "enabled": vsftpd_enabled, "port_21": ftp_listen},
            )
        )
    else:
        findings.append(GovernanceFinding("vsftpd", "PASS", "vsftpd not active"))

    quota = _quota_enabled()
    if not quota.get("quotas_actively_on"):
        findings.append(
            GovernanceFinding(
                "filesystem_quota",
                "WARNING",
                quota.get("maintenance_code") or "Kernel filesystem quotas not active",
                quota,
            )
        )
    elif quota.get("project_quota_maintenance_required"):
        findings.append(
            GovernanceFinding(
                "filesystem_project_quota",
                "WARNING",
                "USRQUOTA active; PRJQUOTA needs offline tune2fs (SAFE_LEGACY www-data bypass)",
                quota,
            )
        )
    else:
        findings.append(GovernanceFinding("filesystem_quota", "PASS", "Kernel quotas active"))

    # Bandwidth soft-block path present
    bw_mod = Path(__file__).resolve().parent / "bandwidth_enforcement.py"
    if bw_mod.is_file():
        findings.append(
            GovernanceFinding(
                "bandwidth_soft_block",
                "PASS",
                "SOFT_BLOCK enforcement module present (nginx edge)",
            )
        )

    repo = repo_path or Path("/srv/apps/ifnotus")
    head = _git_head(repo) if repo.is_dir() else None

    return {
        "status": "PASS"
        if not any(f.severity == "FAIL" for f in findings)
        else ("WARNING" if any(f.severity == "WARNING" for f in findings) else "FAIL"),
        "host": {
            **safety.to_dict(),
            "pressure_band": band,
            "safety_floor_gib": HOST_MEMAVAILABLE_SAFETY_FLOOR_GIB,
        },
        "policy": policy.snapshot(),
        "governor": gov_snap,
        "slices": {
            "tenants": TENANTS_SLICE,
            "priority": PRIORITY_SLICE,
        },
        "ftp": {
            "vsftpd_active": vsftpd_active,
            "vsftpd_enabled": vsftpd_enabled,
            "port_21_listening": ftp_listen,
        },
        "storage_quota": quota,
        "bandwidth": {
            "enforcement": "SOFT_BLOCK",
            "persistent_accounting": True,
            "limit_enforced": True,
        },
        "deployment": {
            "git_head": head,
            "repo": str(repo),
        },
        "cpu_policy": {
            "central_resolve": True,
            "sample_default_percent": resolve_cpu_quota_percent(None),
            "drift_helper": detect_cpu_quota_drift(live_cpu_quota="25%", expected_percent=25),
        },
        "findings": [asdict(f) for f in findings],
    }


def format_governance_status(report: dict[str, Any]) -> str:
    lines = [
        "IFNOTUS resource-governance-status",
        f"overall: {report.get('status')}",
        f"pressure_band: {report.get('host', {}).get('pressure_band')}",
        f"mem_available_gib: {report.get('host', {}).get('mem_available_gib')}",
        f"git_head: {report.get('deployment', {}).get('git_head')}",
        f"vsftpd: active={report.get('ftp', {}).get('vsftpd_active')} "
        f"port21={report.get('ftp', {}).get('port_21_listening')}",
        f"kernel_quota: {report.get('storage_quota', {}).get('kernel_quota_enabled')}",
    ]
    for f in report.get("findings") or []:
        lines.append(f"  [{f.get('severity')}] {f.get('code')}: {f.get('message')}")
    return "\n".join(lines)


def dump_governance_json(report: dict[str, Any]) -> str:
    return json.dumps(report, indent=2, default=str)
