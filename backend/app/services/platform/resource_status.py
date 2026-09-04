"""Phase J — truthful resource limit status (ALLOCATED / REPORTED / ENFORCED).

Customer UI must not claim enforcement until the host actually applies limits.
Bandwidth remains Monitored (reported usage, no hard cap) until provider enforcement
is verified.
"""

from __future__ import annotations

from typing import Any, Literal

from app.core.config import Settings
from app.models.platform import CustomerEnvironment, HostingPlan

ResourceStatusLevel = Literal["allocated", "reported", "enforced", "monitored"]

# Customer-facing label map
STATUS_LABELS: dict[ResourceStatusLevel, str] = {
    "allocated": "Allocated",
    "reported": "Reported",
    "enforced": "Enforced",
    "monitored": "Monitored",
}


def _dim(
    *,
    allocated: bool,
    reported: bool,
    enforced: bool,
    limit: Any = None,
    unit: str | None = None,
    detail: str | None = None,
    monitored: bool = False,
) -> dict[str, Any]:
    if monitored:
        level: ResourceStatusLevel = "monitored"
    elif enforced:
        level = "enforced"
    elif reported:
        level = "reported"
    elif allocated:
        level = "allocated"
    else:
        level = "allocated"
    out: dict[str, Any] = {
        "status": level,
        "label": STATUS_LABELS[level],
        "allocated": allocated,
        "reported": reported,
        "enforced": enforced,
    }
    if limit is not None:
        out["limit"] = limit
    if unit:
        out["unit"] = unit
    if detail:
        out["detail"] = detail
    return out


def build_resource_statuses(
    *,
    env: CustomerEnvironment,
    plan: HostingPlan | None,
    settings: Settings,
    disk: dict[str, Any] | None = None,
    os_quota: dict[str, Any] | None = None,
    live: dict[str, Any] | None = None,
    slice_applied: dict[str, Any] | None = None,
    prlimit_available: bool | None = None,
) -> dict[str, Any]:
    """Derive per-dimension status from runtime probes (no decorative claims)."""
    import shutil

    disk = disk or {}
    os_quota = os_quota or {}
    live = live or {}
    slice_applied = slice_applied or {}

    provider = str(getattr(env, "provider", None) or "legacy").lower()
    storage_gb = int(env.storage_limit_gb or 0)
    cpu_limit = float(env.cpu_limit or 0)
    ram_gb = float(env.ram_limit_gb or 0)
    bw_tb = float(getattr(plan, "bandwidth_tb", None) or 0) if plan else 0.0

    # --- Disk ---
    os_hard = bool(os_quota.get("hard_enforced"))
    panel_blocks = storage_gb > 0  # API/file manager blocks at 100% via usage.py
    ispconfig_disk = provider == "ispconfig" and bool(
        (getattr(env, "provider_meta", None) or {}).get("quota_enforced")
    )
    disk_enforced = storage_gb > 0 or os_hard or ispconfig_disk
    disk_detail = str(os_quota.get("message") or "")
    if os_hard:
        disk_detail = "OS user quota (setquota) on tenant Unix account"
    elif ispconfig_disk:
        disk_detail = "ISPConfig package disk quota"
    elif disk_enforced:
        disk_detail = "Platform storage quota and write blocking active"

    disk_status = _dim(
        allocated=storage_gb > 0,
        reported=bool(disk.get("storage_used_bytes") is not None or disk.get("storage_pct") is not None),
        enforced=disk_enforced,
        limit=storage_gb,
        unit="GB",
        detail=disk_detail or None,
    )
    disk_status["panel_write_block"] = panel_blocks and not disk_enforced

    # --- CPU / RAM / Processes (systemd slice + prlimit defense-in-depth) ---
    slice_ok = bool(slice_applied.get("applied"))
    cgroup_reported = bool(live.get("available"))
    prlimit_ok = prlimit_available if prlimit_available is not None else shutil.which("prlimit") is not None

    runtime_detail = None
    if slice_ok:
        runtime_detail = f"systemd slice {slice_applied.get('slice') or ''}".strip()
    elif slice_applied.get("skipped"):
        runtime_detail = f"Slice not applied ({slice_applied.get('skipped')})"

    cpu_status = _dim(
        allocated=cpu_limit > 0,
        reported=cgroup_reported,
        enforced=slice_ok,
        limit=cpu_limit,
        unit="vCPU",
        detail=runtime_detail,
    )

    # Prefer Phase 2C MemoryHigh (then MemoryMax) over marketing ram_limit_gb.
    ram_limit_gb = ram_gb
    high_b = live.get("memory_high_bytes") or slice_applied.get("memory_high_bytes")
    max_b = live.get("memory_max_bytes") or slice_applied.get("memory_max_bytes")
    if high_b:
        ram_limit_gb = float(high_b) / (1024 ** 3)
    elif max_b:
        ram_limit_gb = float(max_b) / (1024 ** 3)

    ram_status = _dim(
        allocated=ram_limit_gb > 0,
        reported=cgroup_reported and live.get("memory_mb") is not None,
        enforced=slice_ok,
        limit=round(ram_limit_gb * 1024, 1) if ram_limit_gb else None,
        unit="MB",
        detail=runtime_detail,
    )

    proc_limit = None
    if slice_applied.get("tasks_max") is not None:
        proc_limit = int(slice_applied["tasks_max"])
    processes_enforced = slice_ok or prlimit_ok
    proc_detail = runtime_detail
    if prlimit_ok and not slice_ok:
        proc_detail = "RLIMIT_NPROC via prlimit on supervised app commands"
        processes_enforced = True

    processes_status = _dim(
        allocated=proc_limit is not None or cpu_limit > 0,
        reported=cgroup_reported and live.get("process_count") is not None,
        enforced=processes_enforced and (slice_ok or prlimit_ok),
        limit=proc_limit,
        unit="tasks",
        detail=proc_detail,
    )

    # --- Bandwidth: SOFT_BLOCK at 100% via nginx edge (portal/mail remain up) ---
    bw_unlimited = bw_tb <= 0
    if bw_unlimited:
        bw_status = _dim(
            allocated=True,
            reported=True,
            enforced=False,
            limit=None,
            unit="TB/month",
            detail="UNLIMITED — no soft-block",
            monitored=True,
        )
    else:
        bw_status = _dim(
            allocated=True,
            reported=True,
            enforced=True,
            limit=bw_tb,
            unit="TB/month",
            detail="Persistent cycle meter; SOFT_BLOCK at 100% (hosted site only)",
        )

    any_runtime_enforced = slice_ok or os_hard or (not bw_unlimited)
    return {
        "disk": disk_status,
        "cpu": cpu_status,
        "memory": ram_status,
        "processes": processes_status,
        "bandwidth": bw_status,
        "provider": provider,
        "resources_enforced": any_runtime_enforced,
        "summary": _summary_line(disk_status, cpu_status, ram_status, processes_status, bw_status),
    }


def _summary_line(*dims: dict[str, Any]) -> str:
    enforced = [k for k, d in zip(("disk", "cpu", "memory", "processes", "bandwidth"), dims, strict=False) if d.get("enforced")]
    if enforced:
        return f"Enforced: {', '.join(enforced)}"
    reported = [k for k, d in zip(("disk", "cpu", "memory", "processes", "bandwidth"), dims, strict=False) if d.get("reported")]
    if reported:
        return f"Reported: {', '.join(reported)}; bandwidth monitored only"
    return "Plan limits allocated; host enforcement pending"
