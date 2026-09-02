"""Phase 3B-1 host safety floor + emergency capacity calculator (no grants).

Uses live MemAvailable / MemTotal — never marketed 48 GiB for safety decisions.
Does not set MemoryMin or mutate cgroups.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from app.services.platform.resource_policy import BYTES_PER_GIB, gib_to_bytes

# Logical emergency budget (Phase 3) — not granted in 3B-1.
EMERGENCY_BUDGET_MAX_GIB = 9.0
# Operational MemAvailable floor — NOT MemoryMin.
HOST_MEMAVAILABLE_SAFETY_FLOOR_GIB = 6.0

STATUS_SAFE = "SAFE"
STATUS_REDUCED_HEADROOM = "REDUCED_HEADROOM"
STATUS_DENY_BURST = "DENY_BURST"
STATUS_CRITICAL_PRESSURE = "CRITICAL_PRESSURE"


def read_meminfo_bytes() -> dict[str, int]:
    out: dict[str, int] = {}
    path = Path("/proc/meminfo")
    if not path.is_file():
        return out
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if ":" not in line:
            continue
        key, rest = line.split(":", 1)
        parts = rest.strip().split()
        if not parts:
            continue
        try:
            # values are kB
            out[key] = int(parts[0]) * 1024
        except ValueError:
            continue
    return out


def read_memory_psi() -> dict[str, str]:
    path = Path("/proc/pressure/memory")
    if not path.is_file():
        return {"some": "", "full": "", "available": False}
    some = full = ""
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if line.startswith("some"):
            some = line
        elif line.startswith("full"):
            full = line
    return {"some": some, "full": full, "available": True}


def _psi_avg10(line: str) -> float | None:
    # some avg10=0.00 avg60=...
    try:
        for part in line.split():
            if part.startswith("avg10="):
                return float(part.split("=", 1)[1])
    except (TypeError, ValueError, IndexError):
        return None
    return None


@dataclass(frozen=True)
class HostSafetySnapshot:
    mem_total_bytes: int
    mem_available_bytes: int
    swap_total_bytes: int
    swap_free_bytes: int
    safety_floor_gib: float
    emergency_budget_max_gib: float
    emergency_allocated_gib: float
    tenant_memory_current_bytes: int | None
    priority_memory_current_bytes: int | None
    infrastructure_estimate_bytes: int | None
    psi_some: str
    psi_full: str
    status: str
    safe_emergency_capacity_gib: float
    notes: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["mem_total_gib"] = round(self.mem_total_bytes / BYTES_PER_GIB, 3)
        d["mem_available_gib"] = round(self.mem_available_bytes / BYTES_PER_GIB, 3)
        d["swap_used_mib"] = round(
            (self.swap_total_bytes - self.swap_free_bytes) / (1024 * 1024), 2
        )
        return d


def safe_emergency_capacity_gib(
    *,
    mem_available_bytes: int,
    safety_floor_gib: float = HOST_MEMAVAILABLE_SAFETY_FLOOR_GIB,
    emergency_allocated_gib: float = 0.0,
    emergency_budget_max_gib: float = EMERGENCY_BUDGET_MAX_GIB,
) -> float:
    """Maximum emergency grant that would still leave MemAvailable >= safety floor.

    Pure function — does not grant. Uses live MemAvailable, never marketed 48 GiB.
    """
    floor = gib_to_bytes(safety_floor_gib)
    host_spare = max(0, int(mem_available_bytes) - floor)
    budget_spare = max(0.0, float(emergency_budget_max_gib) - float(emergency_allocated_gib))
    budget_spare_bytes = gib_to_bytes(budget_spare)
    grantable = min(host_spare, budget_spare_bytes)
    return round(grantable / BYTES_PER_GIB, 4)


def classify_host_safety_status(
    *,
    mem_available_bytes: int,
    safety_floor_gib: float = HOST_MEMAVAILABLE_SAFETY_FLOOR_GIB,
    psi_some_avg10: float | None = None,
) -> str:
    avail_gib = mem_available_bytes / BYTES_PER_GIB
    floor = float(safety_floor_gib)
    if avail_gib < floor * 0.5 or (psi_some_avg10 is not None and psi_some_avg10 >= 20.0):
        return STATUS_CRITICAL_PRESSURE
    if avail_gib < floor:
        return STATUS_DENY_BURST
    if avail_gib < floor + 4.0:
        return STATUS_REDUCED_HEADROOM
    return STATUS_SAFE


def build_host_safety_snapshot(
    *,
    tenant_memory_current_bytes: int | None = None,
    priority_memory_current_bytes: int | None = None,
    infrastructure_estimate_bytes: int | None = None,
    emergency_allocated_gib: float = 0.0,
    safety_floor_gib: float = HOST_MEMAVAILABLE_SAFETY_FLOOR_GIB,
    emergency_budget_max_gib: float = EMERGENCY_BUDGET_MAX_GIB,
    meminfo: dict[str, int] | None = None,
) -> HostSafetySnapshot:
    mi = meminfo if meminfo is not None else read_meminfo_bytes()
    psi = read_memory_psi()
    total = int(mi.get("MemTotal") or 0)
    avail = int(mi.get("MemAvailable") or 0)
    swap_t = int(mi.get("SwapTotal") or 0)
    swap_f = int(mi.get("SwapFree") or 0)
    avg10 = _psi_avg10(psi.get("some") or "")
    status = classify_host_safety_status(
        mem_available_bytes=avail,
        safety_floor_gib=safety_floor_gib,
        psi_some_avg10=avg10,
    )
    capacity = safe_emergency_capacity_gib(
        mem_available_bytes=avail,
        safety_floor_gib=safety_floor_gib,
        emergency_allocated_gib=emergency_allocated_gib,
        emergency_budget_max_gib=emergency_budget_max_gib,
    )
    notes = (
        "Safety floor is a MemAvailable threshold, not MemoryMin.",
        "Emergency capacity is computed only — Phase 3B-1 does not grant.",
        "Live MemTotal/MemAvailable used; marketed 48 GiB is not an input.",
    )
    return HostSafetySnapshot(
        mem_total_bytes=total,
        mem_available_bytes=avail,
        swap_total_bytes=swap_t,
        swap_free_bytes=swap_f,
        safety_floor_gib=float(safety_floor_gib),
        emergency_budget_max_gib=float(emergency_budget_max_gib),
        emergency_allocated_gib=float(emergency_allocated_gib),
        tenant_memory_current_bytes=tenant_memory_current_bytes,
        priority_memory_current_bytes=priority_memory_current_bytes,
        infrastructure_estimate_bytes=infrastructure_estimate_bytes,
        psi_some=psi.get("some") or "",
        psi_full=psi.get("full") or "",
        status=status,
        safe_emergency_capacity_gib=capacity,
        notes=notes,
    )
