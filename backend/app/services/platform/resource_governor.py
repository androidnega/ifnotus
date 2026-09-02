"""Phase 3B-2 — Resource emergency memory governor.

Single shared 9 GiB emergency ledger for tenant parent + priority parent.
Host MemAvailable safety floor (6 GiB), PSI, swap, and OOM gates.
Kernel cgroup state is authoritative on restart.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import time
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path
from typing import Any, Callable

from app.core.logging import get_logger
from app.services.platform.host_safety import (
    EMERGENCY_BUDGET_MAX_GIB,
    HOST_MEMAVAILABLE_SAFETY_FLOOR_GIB,
    STATUS_CRITICAL_PRESSURE,
    STATUS_DENY_BURST,
    _psi_avg10,
    classify_host_safety_status,
    read_meminfo_bytes,
    read_memory_psi,
    safe_emergency_capacity_gib,
)
from app.services.platform.resource_policy import BYTES_PER_GIB, gib_to_bytes
from app.services.platform.workload_slices import (
    PRIORITY_MEMORY_HIGH,
    PRIORITY_SLICE,
    TENANTS_SLICE,
    read_cgroup_memory_current,
    resolve_slice_cgroup_path,
)

logger = get_logger(__name__)

TENANT_NORMAL_MAX_GIB = 30
PRIORITY_NORMAL_MAX_GIB = 8
PRIORITY_NORMAL_HIGH_GIB = 8
INCREMENT_GIB = 1
PRESSURE_RATIO = 0.90

SAMPLE_INTERVAL_SEC = 10
TRIGGER_SAMPLES = 3
RELEASE_COOLDOWN_SEC = 120

PSI_SOME_DENY_AVG10 = 10.0
PSI_FULL_DENY_AVG10 = 5.0
SWAP_USED_DENY_MIB = 256.0
SWAP_RISE_DENY_MIB = 64.0
SAFE_SHRINK_MARGIN_MIB = 256.0
OOM_COOLDOWN_SEC = 300

AUDIT_LOG_PATH = Path("/var/log/ifnotus/resource-governor.jsonl")
STATE_PATH = Path("/var/lib/ifnotus/resource-governor-state.json")

Borrower = str


class GovernorState(str, Enum):
    NORMAL = "NORMAL"
    PRESSURE_REQUESTED = "PRESSURE_REQUESTED"
    BURST_GRANTED = "BURST_GRANTED"
    BURST_ACTIVE = "BURST_ACTIVE"
    COOLDOWN = "COOLDOWN"
    DENIED = "DENIED"
    RECONCILING = "RECONCILING"
    ERROR = "ERROR"


class AuditAction(str, Enum):
    EMERGENCY_MEMORY_REQUESTED = "EMERGENCY_MEMORY_REQUESTED"
    EMERGENCY_MEMORY_GRANTED = "EMERGENCY_MEMORY_GRANTED"
    EMERGENCY_MEMORY_DENIED = "EMERGENCY_MEMORY_DENIED"
    EMERGENCY_MEMORY_RELEASED = "EMERGENCY_MEMORY_RELEASED"
    GOVERNOR_RECONCILED = "GOVERNOR_RECONCILED"
    GOVERNOR_ERROR = "GOVERNOR_ERROR"


@dataclass
class EmergencyLedger:
    tenant_emergency_gib: int = 0
    priority_emergency_gib: int = 0

    @property
    def total_emergency_gib(self) -> int:
        return int(self.tenant_emergency_gib) + int(self.priority_emergency_gib)

    @property
    def remaining_emergency_gib(self) -> int:
        return max(0, int(EMERGENCY_BUDGET_MAX_GIB) - self.total_emergency_gib)

    def assert_invariant(self) -> None:
        if self.tenant_emergency_gib < 0 or self.priority_emergency_gib < 0:
            raise ValueError("emergency allocation cannot be negative")
        if self.total_emergency_gib > int(EMERGENCY_BUDGET_MAX_GIB):
            raise ValueError(
                f"emergency ledger exceeds {EMERGENCY_BUDGET_MAX_GIB} GiB: "
                f"{self.total_emergency_gib}"
            )


@dataclass
class SliceLive:
    name: str
    memory_current_bytes: int
    memory_max_bytes: int | None
    memory_high_bytes: int | None
    memory_events: dict[str, int] = field(default_factory=dict)


@dataclass
class HostLive:
    mem_total_bytes: int
    mem_available_bytes: int
    swap_total_bytes: int
    swap_free_bytes: int
    psi_some: str
    psi_full: str
    safety_status: str

    @property
    def swap_used_bytes(self) -> int:
        return max(0, self.swap_total_bytes - self.swap_free_bytes)

    @property
    def psi_some_avg10(self) -> float | None:
        return _psi_avg10(self.psi_some)

    @property
    def psi_full_avg10(self) -> float | None:
        return _psi_avg10(self.psi_full)


@dataclass
class PlannedAction:
    action: str
    borrower: Borrower | None
    amount_gib: int
    old_memory_max_bytes: int | None
    new_memory_max_bytes: int | None
    reason: str
    would_mutate: bool


@dataclass
class GovernorSnapshot:
    state: GovernorState
    ledger: EmergencyLedger
    host: HostLive
    tenants: SliceLive
    priority: SliceLive
    last_action: str
    last_reason: str
    last_grant: str | None
    last_release: str | None
    priority_baseline_applied: bool
    dry_run: bool = False
    planned: PlannedAction | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "state": self.state.value,
            "dry_run": self.dry_run,
            "last_action": self.last_action,
            "last_reason": self.last_reason,
            "last_grant": self.last_grant,
            "last_release": self.last_release,
            "priority_baseline_applied": self.priority_baseline_applied,
            "host": {
                "mem_total_gib": round(self.host.mem_total_bytes / BYTES_PER_GIB, 3),
                "mem_available_gib": round(self.host.mem_available_bytes / BYTES_PER_GIB, 3),
                "safety_floor_gib": HOST_MEMAVAILABLE_SAFETY_FLOOR_GIB,
                "safety_status": self.host.safety_status,
                "swap_used_mib": round(self.host.swap_used_bytes / (1024 * 1024), 2),
                "psi_some": self.host.psi_some,
                "psi_full": self.host.psi_full,
            },
            "tenants": {
                "slice": self.tenants.name,
                "memory_current_gib": round(self.tenants.memory_current_bytes / BYTES_PER_GIB, 3),
                "normal_max_gib": TENANT_NORMAL_MAX_GIB,
                "emergency_gib": self.ledger.tenant_emergency_gib,
                "effective_max_gib": TENANT_NORMAL_MAX_GIB + self.ledger.tenant_emergency_gib,
                "memory_max_live": _fmt_bytes(self.tenants.memory_max_bytes),
            },
            "priority": {
                "slice": self.priority.name,
                "memory_current_gib": round(self.priority.memory_current_bytes / BYTES_PER_GIB, 3),
                "normal_high_gib": PRIORITY_NORMAL_HIGH_GIB,
                "normal_max_gib": PRIORITY_NORMAL_MAX_GIB,
                "emergency_gib": self.ledger.priority_emergency_gib,
                "effective_max_gib": PRIORITY_NORMAL_MAX_GIB + self.ledger.priority_emergency_gib,
                "memory_max_live": _fmt_bytes(self.priority.memory_max_bytes),
                "memory_high_live": _fmt_bytes(self.priority.memory_high_bytes),
            },
            "emergency": {
                "maximum_total_gib": int(EMERGENCY_BUDGET_MAX_GIB),
                "tenant_emergency_gib": self.ledger.tenant_emergency_gib,
                "priority_emergency_gib": self.ledger.priority_emergency_gib,
                "allocated_total_gib": self.ledger.total_emergency_gib,
                "remaining_gib": self.ledger.remaining_emergency_gib,
            },
            "planned": asdict(self.planned) if self.planned else None,
        }


def _fmt_bytes(value: int | None) -> str:
    if value is None:
        return "infinity"
    return str(value)


def parse_systemd_bytes(raw: str | None) -> int | None:
    if raw is None:
        return None
    s = str(raw).strip().lower()
    if not s or s in {"infinity", "18446744073709551615", "-1"}:
        return None
    try:
        return int(s)
    except ValueError:
        return None


def reconstruct_emergency_from_memory_max(
    *,
    memory_max_bytes: int | None,
    normal_max_gib: int,
) -> int:
    if memory_max_bytes is None:
        return 0
    normal = gib_to_bytes(normal_max_gib)
    if memory_max_bytes <= normal:
        return 0
    return max(0, int((memory_max_bytes - normal) // BYTES_PER_GIB))


def effective_memory_max_bytes(*, normal_gib: int, emergency_gib: int) -> int:
    return gib_to_bytes(normal_gib + int(emergency_gib))


def pressure_threshold_bytes(normal_gib: int) -> int:
    return int(gib_to_bytes(normal_gib) * PRESSURE_RATIO)


def round_grantable_to_increment(
    safe_grantable_gib: float, *, increment: int = INCREMENT_GIB
) -> int:
    if safe_grantable_gib < increment:
        return 0
    return int(safe_grantable_gib // increment) * increment


def can_safely_shrink(
    *,
    memory_current_bytes: int,
    proposed_max_bytes: int,
    margin_mib: float = SAFE_SHRINK_MARGIN_MIB,
) -> bool:
    margin = int(margin_mib * 1024 * 1024)
    return memory_current_bytes + margin <= proposed_max_bytes


class SystemdPropertyBackend:
    def show_properties(self, unit: str, *props: str) -> dict[str, str]:
        systemctl = shutil.which("systemctl") or "systemctl"
        proc = subprocess.run(
            [systemctl, "show", unit, *[f"-p{p}" for p in props]],
            capture_output=True,
            text=True,
            check=False,
            timeout=15,
        )
        out: dict[str, str] = {}
        for line in (proc.stdout or "").splitlines():
            if "=" in line:
                k, v = line.split("=", 1)
                out[k.strip()] = v.strip()
        return out

    def set_memory_max(self, unit: str, memory_max_bytes: int) -> None:
        systemctl = shutil.which("systemctl") or "systemctl"
        subprocess.run(
            [systemctl, "set-property", unit, f"MemoryMax={memory_max_bytes}", "MemoryMin="],
            check=False,
            capture_output=True,
            text=True,
            timeout=30,
        )

    def set_memory_high(self, unit: str, memory_high: str) -> None:
        systemctl = shutil.which("systemctl") or "systemctl"
        subprocess.run(
            [systemctl, "set-property", unit, f"MemoryHigh={memory_high}", "MemoryMin="],
            check=False,
            capture_output=True,
            text=True,
            timeout=30,
        )

    def read_memory_events(self, slice_name: str) -> dict[str, int]:
        cg = resolve_slice_cgroup_path(slice_name)
        if not cg:
            return {}
        path = cg / "memory.events"
        if not path.is_file():
            return {}
        out: dict[str, int] = {}
        try:
            for line in path.read_text(encoding="utf-8").splitlines():
                parts = line.split()
                if len(parts) >= 2:
                    out[parts[0]] = int(parts[1])
        except (OSError, ValueError):
            return {}
        return out

    def read_slice(self, slice_name: str) -> SliceLive:
        props = self.show_properties(slice_name, "MemoryMax", "MemoryHigh", "MemoryCurrent")
        cg = resolve_slice_cgroup_path(slice_name)
        current = read_cgroup_memory_current(cg) if cg else None
        if current is None:
            current = parse_systemd_bytes(props.get("MemoryCurrent")) or 0
        return SliceLive(
            name=slice_name,
            memory_current_bytes=int(current),
            memory_max_bytes=parse_systemd_bytes(props.get("MemoryMax")),
            memory_high_bytes=parse_systemd_bytes(props.get("MemoryHigh")),
            memory_events=self.read_memory_events(slice_name),
        )


class FakeBackend:
    """In-memory backend for unit/integration simulation."""

    def __init__(self) -> None:
        self.slices: dict[str, SliceLive] = {
            TENANTS_SLICE: SliceLive(
                name=TENANTS_SLICE,
                memory_current_bytes=gib_to_bytes(1),
                memory_max_bytes=gib_to_bytes(TENANT_NORMAL_MAX_GIB),
                memory_high_bytes=None,
            ),
            PRIORITY_SLICE: SliceLive(
                name=PRIORITY_SLICE,
                memory_current_bytes=gib_to_bytes(1),
                memory_max_bytes=gib_to_bytes(PRIORITY_NORMAL_MAX_GIB),
                memory_high_bytes=gib_to_bytes(PRIORITY_NORMAL_HIGH_GIB),
            ),
        }
        self.mutations: list[tuple[str, int]] = []

    def show_properties(self, unit: str, *props: str) -> dict[str, str]:
        sl = self.slices[unit]
        return {
            "MemoryMax": "infinity" if sl.memory_max_bytes is None else str(sl.memory_max_bytes),
            "MemoryHigh": "infinity" if sl.memory_high_bytes is None else str(sl.memory_high_bytes),
            "MemoryCurrent": str(sl.memory_current_bytes),
        }

    def set_memory_max(self, unit: str, memory_max_bytes: int) -> None:
        self.slices[unit].memory_max_bytes = memory_max_bytes
        self.mutations.append((unit, memory_max_bytes))

    def set_memory_high(self, unit: str, memory_high: str) -> None:
        self.slices[unit].memory_high_bytes = int(memory_high)

    def read_memory_events(self, slice_name: str) -> dict[str, int]:
        return dict(self.slices[slice_name].memory_events)

    def read_slice(self, slice_name: str) -> SliceLive:
        sl = self.slices[slice_name]
        return SliceLive(
            name=sl.name,
            memory_current_bytes=sl.memory_current_bytes,
            memory_max_bytes=sl.memory_max_bytes,
            memory_high_bytes=sl.memory_high_bytes,
            memory_events=dict(sl.memory_events),
        )


@dataclass
class ResourceEmergencyGovernor:
    backend: Any = None
    meminfo_reader: Callable[[], dict[str, int]] = field(default=read_meminfo_bytes)
    psi_reader: Callable[[], dict[str, str]] = field(default=read_memory_psi)
    now_fn: Callable[[], float] = field(default=time.time)
    audit_path: Path = AUDIT_LOG_PATH
    state_path: Path = STATE_PATH
    dry_run: bool = False

    state: GovernorState = GovernorState.NORMAL
    ledger: EmergencyLedger = field(default_factory=EmergencyLedger)
    pressure_streak: dict[str, int] = field(default_factory=lambda: {"tenants": 0, "priority": 0})
    below_normal_since: dict[str, float | None] = field(
        default_factory=lambda: {"tenants": None, "priority": None}
    )
    last_swap_used_bytes: int | None = None
    last_oom_total: dict[str, int] = field(default_factory=dict)
    last_oom_at: float | None = None
    last_action: str = "none"
    last_reason: str = ""
    last_grant: str | None = None
    last_release: str | None = None
    priority_baseline_applied: bool = False
    _bootstrapped: bool = False

    def _be(self) -> Any:
        if self.backend is None:
            self.backend = SystemdPropertyBackend()
        return self.backend

    def read_host(self) -> HostLive:
        mi = self.meminfo_reader()
        psi = self.psi_reader()
        avail = int(mi.get("MemAvailable") or 0)
        status = classify_host_safety_status(
            mem_available_bytes=avail,
            safety_floor_gib=HOST_MEMAVAILABLE_SAFETY_FLOOR_GIB,
            psi_some_avg10=_psi_avg10(psi.get("some") or ""),
        )
        return HostLive(
            mem_total_bytes=int(mi.get("MemTotal") or 0),
            mem_available_bytes=avail,
            swap_total_bytes=int(mi.get("SwapTotal") or 0),
            swap_free_bytes=int(mi.get("SwapFree") or 0),
            psi_some=psi.get("some") or "",
            psi_full=psi.get("full") or "",
            safety_status=status,
        )

    def reconcile_from_kernel(self) -> GovernorSnapshot:
        self.state = GovernorState.RECONCILING
        be = self._be()
        tenants = be.read_slice(TENANTS_SLICE)
        priority = be.read_slice(PRIORITY_SLICE)
        host = self.read_host()

        t_em = reconstruct_emergency_from_memory_max(
            memory_max_bytes=tenants.memory_max_bytes,
            normal_max_gib=TENANT_NORMAL_MAX_GIB,
        )
        if priority.memory_max_bytes is None:
            p_em = 0
            self.priority_baseline_applied = False
        else:
            p_em = reconstruct_emergency_from_memory_max(
                memory_max_bytes=priority.memory_max_bytes,
                normal_max_gib=PRIORITY_NORMAL_MAX_GIB,
            )
            self.priority_baseline_applied = True

        total = t_em + p_em
        if total > int(EMERGENCY_BUDGET_MAX_GIB):
            overflow = total - int(EMERGENCY_BUDGET_MAX_GIB)
            cut_t = min(t_em, overflow)
            t_em -= cut_t
            overflow -= cut_t
            p_em = max(0, p_em - overflow)

        self.ledger = EmergencyLedger(
            tenant_emergency_gib=t_em,
            priority_emergency_gib=p_em,
        )
        self.ledger.assert_invariant()
        self._bootstrapped = True
        self.last_action = "reconcile"
        self.last_reason = "kernel_authoritative_reconstruct"
        self._audit(
            AuditAction.GOVERNOR_RECONCILED,
            borrower=None,
            old_max=None,
            new_max=None,
            host=host,
            reason=self.last_reason,
        )
        self.state = (
            GovernorState.BURST_ACTIVE if self.ledger.total_emergency_gib > 0 else GovernorState.NORMAL
        )
        self._persist_state()
        return self.snapshot(host=host, tenants=tenants, priority=priority)

    def ensure_priority_baseline(self, *, apply: bool) -> PlannedAction:
        be = self._be()
        priority = be.read_slice(PRIORITY_SLICE)
        host = self.read_host()
        target = gib_to_bytes(PRIORITY_NORMAL_MAX_GIB)
        if (
            priority.memory_max_bytes == target
            and self.ledger.priority_emergency_gib == 0
        ):
            self.priority_baseline_applied = True
            return PlannedAction(
                action="none",
                borrower="priority",
                amount_gib=0,
                old_memory_max_bytes=priority.memory_max_bytes,
                new_memory_max_bytes=target,
                reason="priority_baseline_already_8g",
                would_mutate=False,
            )
        if not can_safely_shrink(
            memory_current_bytes=priority.memory_current_bytes,
            proposed_max_bytes=target,
        ):
            return PlannedAction(
                action="deny",
                borrower="priority",
                amount_gib=0,
                old_memory_max_bytes=priority.memory_max_bytes,
                new_memory_max_bytes=target,
                reason="priority_usage_too_close_to_8g_for_baseline",
                would_mutate=False,
            )
        planned = PlannedAction(
            action="set_baseline",
            borrower="priority",
            amount_gib=0,
            old_memory_max_bytes=priority.memory_max_bytes,
            new_memory_max_bytes=target,
            reason="apply_priority_normal_memorymax_8g",
            would_mutate=True,
        )
        if apply and not self.dry_run:
            be.set_memory_high(PRIORITY_SLICE, PRIORITY_MEMORY_HIGH)
            be.set_memory_max(PRIORITY_SLICE, target)
            self.priority_baseline_applied = True
            self.last_action = "set_baseline"
            self.last_reason = planned.reason
            self._audit(
                AuditAction.GOVERNOR_RECONCILED,
                borrower="priority",
                old_max=priority.memory_max_bytes,
                new_max=target,
                host=host,
                reason=planned.reason,
            )
            self._persist_state()
        return planned

    def deny_reasons(self, host: HostLive, tenants: SliceLive, priority: SliceLive) -> list[str]:
        reasons: list[str] = []
        if host.safety_status in {STATUS_DENY_BURST, STATUS_CRITICAL_PRESSURE}:
            reasons.append(f"host_safety_{host.safety_status.lower()}")
        some = host.psi_some_avg10
        full = host.psi_full_avg10
        if some is not None and some >= PSI_SOME_DENY_AVG10:
            reasons.append(f"psi_some_avg10={some}")
        if full is not None and full >= PSI_FULL_DENY_AVG10:
            reasons.append(f"psi_full_avg10={full}")
        swap_mib = host.swap_used_bytes / (1024 * 1024)
        if swap_mib >= SWAP_USED_DENY_MIB:
            reasons.append(f"swap_used_mib={swap_mib:.1f}")
        if self.last_swap_used_bytes is not None:
            rise = (host.swap_used_bytes - self.last_swap_used_bytes) / (1024 * 1024)
            if rise >= SWAP_RISE_DENY_MIB:
                reasons.append(f"swap_rising_mib={rise:.1f}")
        now = self.now_fn()
        for sl in (tenants, priority):
            oom = int(sl.memory_events.get("oom", 0)) + int(sl.memory_events.get("oom_kill", 0))
            prev = self.last_oom_total.get(sl.name, oom)
            if oom > prev:
                self.last_oom_at = now
                reasons.append(f"oom_event_{sl.name}")
            self.last_oom_total[sl.name] = oom
        if self.last_oom_at is not None and (now - self.last_oom_at) < OOM_COOLDOWN_SEC:
            reasons.append("oom_cooldown")
        return reasons

    def tick(self, *, apply: bool = False) -> GovernorSnapshot:
        if not self._bootstrapped:
            self.reconcile_from_kernel()
        be = self._be()
        host = self.read_host()
        tenants = be.read_slice(TENANTS_SLICE)
        priority = be.read_slice(PRIORITY_SLICE)
        self._sync_ledger_from_slices(tenants, priority)
        denies = self.deny_reasons(host, tenants, priority)
        planned = self._decide(host, tenants, priority, denies)
        snap = self.snapshot(host=host, tenants=tenants, priority=priority, planned=planned)

        if planned.action in {"grant", "release"} and planned.would_mutate:
            if apply and not self.dry_run:
                self._apply_planned(planned, host)
                tenants = be.read_slice(TENANTS_SLICE)
                priority = be.read_slice(PRIORITY_SLICE)
                snap = self.snapshot(host=host, tenants=tenants, priority=priority, planned=planned)
            else:
                self.last_action = f"dry_run_{planned.action}"
                self.last_reason = planned.reason

        self.last_swap_used_bytes = host.swap_used_bytes
        self._persist_state()
        return snap

    def force_grant(self, borrower: Borrower, *, apply: bool) -> GovernorSnapshot:
        be = self._be()
        host = self.read_host()
        tenants = be.read_slice(TENANTS_SLICE)
        priority = be.read_slice(PRIORITY_SLICE)
        self._sync_ledger_from_slices(tenants, priority)
        denies = self.deny_reasons(host, tenants, priority)
        if denies:
            planned = PlannedAction(
                action="deny",
                borrower=borrower,
                amount_gib=0,
                old_memory_max_bytes=None,
                new_memory_max_bytes=None,
                reason=";".join(denies),
                would_mutate=False,
            )
            self.state = GovernorState.DENIED
            self._audit(
                AuditAction.EMERGENCY_MEMORY_DENIED,
                borrower=borrower,
                old_max=None,
                new_max=None,
                host=host,
                reason=planned.reason,
            )
            return self.snapshot(host=host, tenants=tenants, priority=priority, planned=planned)

        capacity = round_grantable_to_increment(
            safe_emergency_capacity_gib(
                mem_available_bytes=host.mem_available_bytes,
                emergency_allocated_gib=float(self.ledger.total_emergency_gib),
            )
        )
        if capacity < INCREMENT_GIB or self.ledger.remaining_emergency_gib < INCREMENT_GIB:
            planned = PlannedAction(
                action="deny",
                borrower=borrower,
                amount_gib=0,
                old_memory_max_bytes=None,
                new_memory_max_bytes=None,
                reason="insufficient_safe_or_budget_capacity",
                would_mutate=False,
            )
            self.state = GovernorState.DENIED
            return self.snapshot(host=host, tenants=tenants, priority=priority, planned=planned)

        planned = self._plan_grant(
            borrower, tenants, priority, host, reason="controlled_live_grant_test"
        )
        if apply and not self.dry_run and planned.action == "grant":
            self._apply_planned(planned, host)
            tenants = be.read_slice(TENANTS_SLICE)
            priority = be.read_slice(PRIORITY_SLICE)
        return self.snapshot(host=host, tenants=tenants, priority=priority, planned=planned)

    def force_release(self, borrower: Borrower, *, apply: bool) -> GovernorSnapshot:
        be = self._be()
        host = self.read_host()
        tenants = be.read_slice(TENANTS_SLICE)
        priority = be.read_slice(PRIORITY_SLICE)
        self._sync_ledger_from_slices(tenants, priority)
        planned = self._plan_release(
            borrower, tenants, priority, reason="controlled_live_release_test"
        )
        if apply and not self.dry_run and planned.action == "release":
            self._apply_planned(planned, host)
            tenants = be.read_slice(TENANTS_SLICE)
            priority = be.read_slice(PRIORITY_SLICE)
        return self.snapshot(host=host, tenants=tenants, priority=priority, planned=planned)

    def _sync_ledger_from_slices(self, tenants: SliceLive, priority: SliceLive) -> None:
        t = reconstruct_emergency_from_memory_max(
            memory_max_bytes=tenants.memory_max_bytes,
            normal_max_gib=TENANT_NORMAL_MAX_GIB,
        )
        if priority.memory_max_bytes is None:
            p = 0
        else:
            p = reconstruct_emergency_from_memory_max(
                memory_max_bytes=priority.memory_max_bytes,
                normal_max_gib=PRIORITY_NORMAL_MAX_GIB,
            )
            self.priority_baseline_applied = True
        self.ledger = EmergencyLedger(tenant_emergency_gib=t, priority_emergency_gib=p)
        try:
            self.ledger.assert_invariant()
        except ValueError:
            overflow = self.ledger.total_emergency_gib - int(EMERGENCY_BUDGET_MAX_GIB)
            cut = min(self.ledger.tenant_emergency_gib, overflow)
            self.ledger.tenant_emergency_gib -= cut
            overflow -= cut
            self.ledger.priority_emergency_gib = max(
                0, self.ledger.priority_emergency_gib - overflow
            )

    def _decide(
        self,
        host: HostLive,
        tenants: SliceLive,
        priority: SliceLive,
        denies: list[str],
    ) -> PlannedAction:
        now = self.now_fn()
        t_press = tenants.memory_current_bytes >= pressure_threshold_bytes(TENANT_NORMAL_MAX_GIB)
        p_press = priority.memory_current_bytes >= pressure_threshold_bytes(PRIORITY_NORMAL_MAX_GIB)
        self.pressure_streak["tenants"] = self.pressure_streak["tenants"] + 1 if t_press else 0
        self.pressure_streak["priority"] = self.pressure_streak["priority"] + 1 if p_press else 0

        for key, sl, normal in (
            ("tenants", tenants, TENANT_NORMAL_MAX_GIB),
            ("priority", priority, PRIORITY_NORMAL_MAX_GIB),
        ):
            if sl.memory_current_bytes < gib_to_bytes(normal):
                if self.below_normal_since[key] is None:
                    self.below_normal_since[key] = now
            else:
                self.below_normal_since[key] = None

        for borrower, em_attr in (
            ("priority", "priority_emergency_gib"),
            ("tenants", "tenant_emergency_gib"),
        ):
            em = getattr(self.ledger, em_attr)
            since = self.below_normal_since[borrower]
            if em > 0 and since is not None and (now - since) >= RELEASE_COOLDOWN_SEC:
                return self._plan_release(borrower, tenants, priority, reason="below_normal_120s")

        if denies:
            self.state = GovernorState.DENIED
            return PlannedAction(
                action="deny",
                borrower=None,
                amount_gib=0,
                old_memory_max_bytes=None,
                new_memory_max_bytes=None,
                reason=";".join(denies),
                would_mutate=False,
            )

        order: list[Borrower] = []
        if self.pressure_streak["priority"] >= TRIGGER_SAMPLES:
            order.append("priority")
        if self.pressure_streak["tenants"] >= TRIGGER_SAMPLES:
            order.append("tenants")

        if order:
            self.state = GovernorState.PRESSURE_REQUESTED
            self._audit(
                AuditAction.EMERGENCY_MEMORY_REQUESTED,
                borrower=order[0],
                old_max=None,
                new_max=None,
                host=host,
                reason=f"sustained_pressure:{order}",
            )

        capacity = round_grantable_to_increment(
            safe_emergency_capacity_gib(
                mem_available_bytes=host.mem_available_bytes,
                emergency_allocated_gib=float(self.ledger.total_emergency_gib),
            )
        )
        for borrower in order:
            if capacity < INCREMENT_GIB or self.ledger.remaining_emergency_gib < INCREMENT_GIB:
                self.state = GovernorState.DENIED
                reason = "emergency_budget_or_host_spare_exhausted"
                self._audit(
                    AuditAction.EMERGENCY_MEMORY_DENIED,
                    borrower=borrower,
                    old_max=None,
                    new_max=None,
                    host=host,
                    reason=reason,
                )
                return PlannedAction(
                    action="deny",
                    borrower=borrower,
                    amount_gib=0,
                    old_memory_max_bytes=None,
                    new_memory_max_bytes=None,
                    reason=reason,
                    would_mutate=False,
                )
            projected = host.mem_available_bytes - gib_to_bytes(INCREMENT_GIB)
            if projected < gib_to_bytes(HOST_MEMAVAILABLE_SAFETY_FLOOR_GIB):
                self.state = GovernorState.DENIED
                reason = "projected_memavailable_below_floor"
                self._audit(
                    AuditAction.EMERGENCY_MEMORY_DENIED,
                    borrower=borrower,
                    old_max=None,
                    new_max=None,
                    host=host,
                    reason=reason,
                )
                return PlannedAction(
                    action="deny",
                    borrower=borrower,
                    amount_gib=0,
                    old_memory_max_bytes=None,
                    new_memory_max_bytes=None,
                    reason=reason,
                    would_mutate=False,
                )
            return self._plan_grant(
                borrower,
                tenants,
                priority,
                host,
                reason=f"sustained_{TRIGGER_SAMPLES}_samples",
            )

        if self.ledger.total_emergency_gib > 0:
            self.state = GovernorState.BURST_ACTIVE
        elif self.state not in {GovernorState.COOLDOWN}:
            self.state = GovernorState.NORMAL
        return PlannedAction(
            action="none",
            borrower=None,
            amount_gib=0,
            old_memory_max_bytes=None,
            new_memory_max_bytes=None,
            reason="no_action",
            would_mutate=False,
        )

    def _plan_grant(
        self,
        borrower: Borrower,
        tenants: SliceLive,
        priority: SliceLive,
        host: HostLive,
        *,
        reason: str,
    ) -> PlannedAction:
        if borrower == "tenants":
            old = effective_memory_max_bytes(
                normal_gib=TENANT_NORMAL_MAX_GIB,
                emergency_gib=self.ledger.tenant_emergency_gib,
            )
            new_em = self.ledger.tenant_emergency_gib + INCREMENT_GIB
            new = effective_memory_max_bytes(
                normal_gib=TENANT_NORMAL_MAX_GIB, emergency_gib=new_em
            )
        else:
            old = effective_memory_max_bytes(
                normal_gib=PRIORITY_NORMAL_MAX_GIB,
                emergency_gib=self.ledger.priority_emergency_gib,
            )
            new_em = self.ledger.priority_emergency_gib + INCREMENT_GIB
            new = effective_memory_max_bytes(
                normal_gib=PRIORITY_NORMAL_MAX_GIB, emergency_gib=new_em
            )
        return PlannedAction(
            action="grant",
            borrower=borrower,
            amount_gib=INCREMENT_GIB,
            old_memory_max_bytes=old,
            new_memory_max_bytes=new,
            reason=reason,
            would_mutate=True,
        )

    def _plan_release(
        self,
        borrower: Borrower,
        tenants: SliceLive,
        priority: SliceLive,
        *,
        reason: str,
    ) -> PlannedAction:
        if borrower == "tenants":
            if self.ledger.tenant_emergency_gib <= 0:
                return PlannedAction(
                    action="none",
                    borrower=borrower,
                    amount_gib=0,
                    old_memory_max_bytes=tenants.memory_max_bytes,
                    new_memory_max_bytes=tenants.memory_max_bytes,
                    reason="no_tenant_emergency",
                    would_mutate=False,
                )
            old = effective_memory_max_bytes(
                normal_gib=TENANT_NORMAL_MAX_GIB,
                emergency_gib=self.ledger.tenant_emergency_gib,
            )
            new_em = self.ledger.tenant_emergency_gib - INCREMENT_GIB
            new = effective_memory_max_bytes(
                normal_gib=TENANT_NORMAL_MAX_GIB, emergency_gib=new_em
            )
            current = tenants.memory_current_bytes
        else:
            if self.ledger.priority_emergency_gib <= 0:
                return PlannedAction(
                    action="none",
                    borrower=borrower,
                    amount_gib=0,
                    old_memory_max_bytes=priority.memory_max_bytes,
                    new_memory_max_bytes=priority.memory_max_bytes,
                    reason="no_priority_emergency",
                    would_mutate=False,
                )
            old = effective_memory_max_bytes(
                normal_gib=PRIORITY_NORMAL_MAX_GIB,
                emergency_gib=self.ledger.priority_emergency_gib,
            )
            new_em = self.ledger.priority_emergency_gib - INCREMENT_GIB
            new = effective_memory_max_bytes(
                normal_gib=PRIORITY_NORMAL_MAX_GIB, emergency_gib=new_em
            )
            current = priority.memory_current_bytes

        if not can_safely_shrink(memory_current_bytes=current, proposed_max_bytes=new):
            self.state = GovernorState.COOLDOWN
            return PlannedAction(
                action="deny",
                borrower=borrower,
                amount_gib=0,
                old_memory_max_bytes=old,
                new_memory_max_bytes=new,
                reason="safe_shrink_blocked_usage_near_new_max",
                would_mutate=False,
            )
        return PlannedAction(
            action="release",
            borrower=borrower,
            amount_gib=INCREMENT_GIB,
            old_memory_max_bytes=old,
            new_memory_max_bytes=new,
            reason=reason,
            would_mutate=True,
        )

    def _apply_planned(self, planned: PlannedAction, host: HostLive) -> None:
        assert planned.borrower is not None
        assert planned.new_memory_max_bytes is not None
        unit = TENANTS_SLICE if planned.borrower == "tenants" else PRIORITY_SLICE
        be = self._be()
        be.set_memory_max(unit, planned.new_memory_max_bytes)
        if planned.borrower == "priority":
            be.set_memory_high(PRIORITY_SLICE, PRIORITY_MEMORY_HIGH)
            self.priority_baseline_applied = True

        if planned.action == "grant":
            self.state = GovernorState.BURST_GRANTED
            self.last_grant = datetime.now(UTC).isoformat()
            self.last_action = "grant"
            self.last_reason = planned.reason
            self.pressure_streak[planned.borrower] = 0
            # Re-read kernel/fake state — never double-count ledger vs MemoryMax
            tenants = be.read_slice(TENANTS_SLICE)
            priority = be.read_slice(PRIORITY_SLICE)
            self._sync_ledger_from_slices(tenants, priority)
            self.ledger.assert_invariant()
            self._audit(
                AuditAction.EMERGENCY_MEMORY_GRANTED,
                borrower=planned.borrower,
                old_max=planned.old_memory_max_bytes,
                new_max=planned.new_memory_max_bytes,
                host=host,
                reason=planned.reason,
            )
            self.state = GovernorState.BURST_ACTIVE
        elif planned.action == "release":
            self.state = GovernorState.COOLDOWN
            self.last_release = datetime.now(UTC).isoformat()
            self.last_action = "release"
            self.last_reason = planned.reason
            self.below_normal_since[planned.borrower] = self.now_fn()
            tenants = be.read_slice(TENANTS_SLICE)
            priority = be.read_slice(PRIORITY_SLICE)
            self._sync_ledger_from_slices(tenants, priority)
            self.ledger.assert_invariant()
            self._audit(
                AuditAction.EMERGENCY_MEMORY_RELEASED,
                borrower=planned.borrower,
                old_max=planned.old_memory_max_bytes,
                new_max=planned.new_memory_max_bytes,
                host=host,
                reason=planned.reason,
            )

    def snapshot(
        self,
        *,
        host: HostLive | None = None,
        tenants: SliceLive | None = None,
        priority: SliceLive | None = None,
        planned: PlannedAction | None = None,
    ) -> GovernorSnapshot:
        be = self._be()
        host = host or self.read_host()
        tenants = tenants or be.read_slice(TENANTS_SLICE)
        priority = priority or be.read_slice(PRIORITY_SLICE)
        return GovernorSnapshot(
            state=self.state,
            ledger=EmergencyLedger(
                tenant_emergency_gib=self.ledger.tenant_emergency_gib,
                priority_emergency_gib=self.ledger.priority_emergency_gib,
            ),
            host=host,
            tenants=tenants,
            priority=priority,
            last_action=self.last_action,
            last_reason=self.last_reason,
            last_grant=self.last_grant,
            last_release=self.last_release,
            priority_baseline_applied=self.priority_baseline_applied,
            dry_run=self.dry_run,
            planned=planned,
        )

    def format_status(self, snap: GovernorSnapshot | None = None) -> str:
        s = snap or self.snapshot()
        d = s.to_dict()
        lines = [
            "## Host",
            f"MemTotal: {d['host']['mem_total_gib']} GiB",
            f"MemAvailable: {d['host']['mem_available_gib']} GiB",
            f"Safety Floor: {d['host']['safety_floor_gib']} GiB",
            f"Safety Status: {d['host']['safety_status']}",
            f"PSI some: {d['host']['psi_some']}",
            f"PSI full: {d['host']['psi_full']}",
            f"Swap used: {d['host']['swap_used_mib']} MiB",
            "",
            "## Tenants",
            f"memory.current: {d['tenants']['memory_current_gib']} GiB",
            f"normal max: {d['tenants']['normal_max_gib']} GiB",
            f"emergency allocation: {d['tenants']['emergency_gib']} GiB",
            f"effective max: {d['tenants']['effective_max_gib']} GiB",
            f"live MemoryMax: {d['tenants']['memory_max_live']}",
            "",
            "## Priority",
            f"memory.current: {d['priority']['memory_current_gib']} GiB",
            f"normal high/max: {d['priority']['normal_high_gib']} / {d['priority']['normal_max_gib']} GiB",
            f"emergency allocation: {d['priority']['emergency_gib']} GiB",
            f"effective max: {d['priority']['effective_max_gib']} GiB",
            f"live MemoryMax: {d['priority']['memory_max_live']}",
            f"baseline applied: {d['priority_baseline_applied']}",
            "",
            "## Emergency",
            f"allocated: {d['emergency']['allocated_total_gib']} GiB",
            f"remaining: {d['emergency']['remaining_gib']} GiB",
            f"maximum: {d['emergency']['maximum_total_gib']} GiB",
            "",
            "## Governor",
            f"state: {d['state']}",
            f"last action: {d['last_action']}",
            f"last reason: {d['last_reason']}",
            f"last grant: {d['last_grant']}",
            f"last release: {d['last_release']}",
        ]
        if d.get("planned"):
            lines += ["", "## Planned", json.dumps(d["planned"], indent=2)]
        return "\n".join(lines)

    def _audit(
        self,
        action: AuditAction,
        *,
        borrower: Borrower | None,
        old_max: int | None,
        new_max: int | None,
        host: HostLive,
        reason: str,
    ) -> None:
        event = {
            "timestamp": datetime.now(UTC).isoformat(),
            "action": action.value,
            "borrower": borrower,
            "old_memory_max": old_max,
            "new_memory_max": new_max,
            "host_mem_available_bytes": host.mem_available_bytes,
            "psi_some": host.psi_some,
            "psi_full": host.psi_full,
            "swap_used_bytes": host.swap_used_bytes,
            "emergency_allocated_gib": self.ledger.total_emergency_gib,
            "tenant_emergency_gib": self.ledger.tenant_emergency_gib,
            "priority_emergency_gib": self.ledger.priority_emergency_gib,
            "reason": reason,
            "state": self.state.value,
        }
        try:
            self.audit_path.parent.mkdir(parents=True, exist_ok=True)
            with self.audit_path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(event, separators=(",", ":")) + "\n")
        except OSError as exc:
            logger.warning("governor_audit_write_failed", error=str(exc))
        logger.info("resource_governor_event", action=action.value, reason=reason, borrower=borrower)

    def _persist_state(self) -> None:
        payload = {
            "ledger": asdict(self.ledger),
            "state": self.state.value,
            "priority_baseline_applied": self.priority_baseline_applied,
            "last_action": self.last_action,
            "last_reason": self.last_reason,
            "last_grant": self.last_grant,
            "last_release": self.last_release,
            "updated_at": datetime.now(UTC).isoformat(),
        }
        try:
            self.state_path.parent.mkdir(parents=True, exist_ok=True)
            self.state_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        except OSError:
            pass

    def run_loop(self, *, interval_sec: int = SAMPLE_INTERVAL_SEC, apply: bool = True) -> None:
        self.dry_run = not apply
        self.reconcile_from_kernel()
        self.ensure_priority_baseline(apply=apply)
        logger.info(
            "resource_governor_started",
            interval_sec=interval_sec,
            apply=apply,
        )
        while True:
            try:
                self.tick(apply=apply)
            except Exception as exc:  # noqa: BLE001
                self.state = GovernorState.ERROR
                logger.exception("resource_governor_tick_error", error=str(exc))
                try:
                    host = self.read_host()
                    self._audit(
                        AuditAction.GOVERNOR_ERROR,
                        borrower=None,
                        old_max=None,
                        new_max=None,
                        host=host,
                        reason=str(exc)[:500],
                    )
                except Exception:  # noqa: BLE001
                    pass
            time.sleep(interval_sec)
