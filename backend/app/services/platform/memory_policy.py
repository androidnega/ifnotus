"""Phase 2C — shared tenant MemoryHigh / MemoryMax enforcement.

Applies demand-driven MemoryHigh (2 or 6 GiB) and MemoryMax (12 GiB) on
environment slices, and MemoryMax=30G on the tenants parent slice.

Does NOT set MemoryMin. Does NOT activate the 9 GiB emergency governor.
Does NOT mutate customer files or legacy HostingPlan.ram_gb semantics.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any
from uuid import UUID

from app.core.logging import get_logger
from app.services.platform.resource_policy import (
    BYTES_PER_GIB,
    HostResourcePolicy,
    PlanResourceClass,
    PlanView,
    classify_plan_resource_class,
    default_host_resource_policy,
    gib_to_bytes,
    resolve_burst_memory_limit,
    resolve_normal_memory_target,
)
from app.services.platform.workload_slices import (
    TENANTS_SLICE,
    parse_legacy_slice_limits,
    read_cgroup_memory_current,
    render_env_slice_unit,
    resolve_slice_cgroup_path,
    slice_name_for,
)

logger = get_logger(__name__)

_SLICE_DIR = Path("/etc/systemd/system")
_BACKUP_ROOT = Path("/var/lib/ifnotus/memory-policy-backups")

DRIFT_POLICY_OK = "POLICY_OK"
DRIFT_LEGACY_MEMORY_MAX = "LEGACY_MEMORY_MAX"
DRIFT_WRONG_MEMORY_HIGH = "WRONG_MEMORY_HIGH"
DRIFT_WRONG_MEMORY_MAX = "WRONG_MEMORY_MAX"
DRIFT_MISSING_SLICE = "MISSING_SLICE"
DRIFT_DEDICATED_POLICY_REQUIRED = "DEDICATED_POLICY_REQUIRED"
DRIFT_PLAN_CLASSIFICATION_REVIEW = "PLAN_CLASSIFICATION_REVIEW"
DRIFT_SUSPENDED_SKIP = "SUSPENDED_SKIP"
DRIFT_FIRST_PARTY_EXCLUDED = "FIRST_PARTY_EXCLUDED"

USAGE_NORMAL = "NORMAL"
USAGE_HIGH_USAGE = "HIGH_USAGE"
USAGE_BURSTING = "BURSTING"
USAGE_NEAR_HARD_LIMIT = "NEAR_HARD_LIMIT"
USAGE_OOM = "OOM"

# Treat MemoryMax below this as "legacy hard limit" (pre-2C).
_LEGACY_MEMORY_MAX_CEILING = int(1.5 * BYTES_PER_GIB)


@dataclass(frozen=True)
class SharedMemoryTargets:
    plan_class: PlanResourceClass
    memory_high_gib: float
    memory_max_gib: float
    memory_high_bytes: int
    memory_max_bytes: int
    warnings: tuple[str, ...] = ()
    source: str = "subscription_plan"


@dataclass
class MemoryPolicyRow:
    environment_id: str
    short_id: str
    domain: str | None
    status: str
    classification: str
    old_memory_high: str | None
    old_memory_max: str | None
    new_memory_high: str | None
    new_memory_max: str | None
    tasks_max: str | None
    cpu_quota: str | None
    current_usage_bytes: int | None
    drift: str
    warnings: list[str] = field(default_factory=list)
    applied: bool = False
    skipped: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _parse_bytes(value: str | None) -> int | None:
    if value is None:
        return None
    text = str(value).strip().lower()
    if not text or text in {"infinity", "max", "-1"}:
        return None
    if text.isdigit():
        return int(text)
    m = re.fullmatch(r"(\d+(?:\.\d+)?)([kmgt]i?b?)?", text)
    if not m:
        return None
    num = float(m.group(1))
    unit = (m.group(2) or "").rstrip("b")
    mult = {
        "": 1,
        "k": 1000,
        "ki": 1024,
        "m": 1000**2,
        "mi": 1024**2,
        "g": 1000**3,
        "gi": 1024**3,
        "t": 1000**4,
        "ti": 1024**4,
    }.get(unit, None)
    if mult is None:
        return None
    return int(num * mult)


def plan_view_from_orm(plan: Any) -> PlanView | None:
    if plan is None:
        return None
    return PlanView(
        slug=str(getattr(plan, "slug", "") or ""),
        name=str(getattr(plan, "name", "") or ""),
        price_monthly=float(getattr(plan, "price_monthly", 0) or 0),
        ram_gb=float(getattr(plan, "ram_gb", 0) or 0),
        storage_gb=float(getattr(plan, "storage_gb", 0) or 0),
        features=dict(getattr(plan, "features", None) or {}),
    )


def resolve_shared_memory_targets(
    plan: PlanView | None,
    *,
    policy: HostResourcePolicy | None = None,
    source: str = "subscription_plan",
) -> SharedMemoryTargets:
    """Resolve MemoryHigh / MemoryMax for ordinary shared hosting.

    Unknown / missing plan → conservative 2 / 12 + PLAN_CLASSIFICATION_REVIEW.
    VPS/VDS/CUSTOM → dedicated (caller must skip shared enforcement).
    """
    policy = policy or default_host_resource_policy()
    warnings: list[str] = []
    if plan is None:
        high = float(policy.tenant_low_plan_normal_gb)
        burst = float(policy.tenant_individual_burst_max_gb)
        warnings.append(DRIFT_PLAN_CLASSIFICATION_REVIEW)
        return SharedMemoryTargets(
            plan_class=PlanResourceClass.SHARED_LOW,
            memory_high_gib=high,
            memory_max_gib=burst,
            memory_high_bytes=gib_to_bytes(high),
            memory_max_bytes=gib_to_bytes(burst),
            warnings=tuple(warnings),
            source="unknown_conservative",
        )

    plan_class = classify_plan_resource_class(plan, policy=policy)
    if plan_class in {
        PlanResourceClass.VPS_STYLE,
        PlanResourceClass.VDS_STYLE,
        PlanResourceClass.CUSTOM,
    }:
        configured = float(plan.ram_gb or 0)
        return SharedMemoryTargets(
            plan_class=plan_class,
            memory_high_gib=configured,
            memory_max_gib=configured,
            memory_high_bytes=gib_to_bytes(configured) if configured else 0,
            memory_max_bytes=gib_to_bytes(configured) if configured else 0,
            warnings=(DRIFT_DEDICATED_POLICY_REQUIRED,),
            source=source,
        )

    high = float(resolve_normal_memory_target(plan, policy=policy) or policy.tenant_low_plan_normal_gb)
    burst, dedicated = resolve_burst_memory_limit(plan, policy=policy)
    if dedicated:
        warnings.append(DRIFT_DEDICATED_POLICY_REQUIRED)
    burst_f = float(burst or policy.tenant_individual_burst_max_gb)
    return SharedMemoryTargets(
        plan_class=plan_class,
        memory_high_gib=high,
        memory_max_gib=burst_f,
        memory_high_bytes=gib_to_bytes(high),
        memory_max_bytes=gib_to_bytes(burst_f),
        warnings=tuple(warnings),
        source=source,
    )


def classify_usage_band(
    *,
    current_bytes: int | None,
    memory_high_bytes: int | None,
    memory_max_bytes: int | None,
    oom: int = 0,
    oom_kill: int = 0,
) -> str:
    if oom or oom_kill:
        return USAGE_OOM
    if current_bytes is None or memory_high_bytes is None or memory_max_bytes is None:
        return USAGE_NORMAL
    if memory_max_bytes > 0 and current_bytes >= int(memory_max_bytes * 0.9):
        return USAGE_NEAR_HARD_LIMIT
    if current_bytes > memory_high_bytes:
        return USAGE_BURSTING
    if memory_high_bytes > 0 and current_bytes >= int(memory_high_bytes * 0.85):
        return USAGE_HIGH_USAGE
    return USAGE_NORMAL


def read_memory_events(cgroup: Path | None) -> dict[str, int]:
    out = {"low": 0, "high": 0, "max": 0, "oom": 0, "oom_kill": 0}
    if cgroup is None:
        return out
    path = cgroup / "memory.events"
    if not path.is_file():
        return out
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            parts = line.split()
            if len(parts) != 2:
                continue
            key, val = parts[0], parts[1]
            if key in out:
                out[key] = int(val)
    except (OSError, ValueError):
        pass
    return out


def read_live_slice_limits(slice_name: str) -> dict[str, Any]:
    """Read unit file + live systemd properties for an env slice."""
    unit_path = _SLICE_DIR / slice_name
    parsed: dict[str, str] = {}
    if unit_path.is_file():
        parsed = parse_legacy_slice_limits(unit_path.read_text(encoding="utf-8", errors="replace"))
        # Also MemoryHigh if present
        for line in unit_path.read_text(encoding="utf-8", errors="replace").splitlines():
            if line.strip().startswith("MemoryHigh="):
                parsed["MemoryHigh"] = line.split("=", 1)[1].strip()
                break

    props = _systemctl_show(slice_name, "MemoryHigh", "MemoryMax", "MemoryCurrent", "MemoryMin", "TasksMax", "CPUQuota")
    cg = resolve_slice_cgroup_path(slice_name)
    current = read_cgroup_memory_current(cg) if cg else None
    if current is None:
        current = _parse_bytes(props.get("MemoryCurrent"))
    high_live = props.get("MemoryHigh") or parsed.get("MemoryHigh")
    max_live = props.get("MemoryMax") or parsed.get("MemoryMax")
    return {
        "slice": slice_name,
        "unit_exists": unit_path.is_file(),
        "cgroup": str(cg) if cg else None,
        "MemoryHigh": high_live,
        "MemoryMax": max_live,
        "MemoryMin": props.get("MemoryMin"),
        "TasksMax": props.get("TasksMax") or parsed.get("TasksMax"),
        "CPUQuota": props.get("CPUQuota") or parsed.get("CPUQuota"),
        "memory_current_bytes": current,
        "memory_events": read_memory_events(cg),
        "memory_high_bytes": _parse_bytes(high_live),
        "memory_max_bytes": _parse_bytes(max_live),
    }


def detect_drift(
    *,
    live: dict[str, Any],
    targets: SharedMemoryTargets,
    env_status: str,
) -> str:
    if env_status == "suspended":
        return DRIFT_SUSPENDED_SKIP
    if targets.warnings and DRIFT_DEDICATED_POLICY_REQUIRED in targets.warnings:
        return DRIFT_DEDICATED_POLICY_REQUIRED
    if not live.get("unit_exists"):
        return DRIFT_MISSING_SLICE
    high = live.get("memory_high_bytes")
    mx = live.get("memory_max_bytes")
    # infinity / unset high counts as wrong for Phase 2C shared
    if high is None or abs(high - targets.memory_high_bytes) > 1024 * 1024:
        # legacy often had no MemoryHigh
        if mx is not None and mx < _LEGACY_MEMORY_MAX_CEILING:
            return DRIFT_LEGACY_MEMORY_MAX
        return DRIFT_WRONG_MEMORY_HIGH
    if mx is None or abs(mx - targets.memory_max_bytes) > 1024 * 1024:
        if mx is not None and mx < _LEGACY_MEMORY_MAX_CEILING:
            return DRIFT_LEGACY_MEMORY_MAX
        return DRIFT_WRONG_MEMORY_MAX
    if targets.source == "unknown_conservative" or DRIFT_PLAN_CLASSIFICATION_REVIEW in targets.warnings:
        return DRIFT_PLAN_CLASSIFICATION_REVIEW
    return DRIFT_POLICY_OK


def render_env_slice_unit_with_high(
    *,
    slice_name: str,
    cpu_quota: str,
    memory_high: str,
    memory_max: str,
    tasks_max: str,
) -> str:
    """Env slice unit with MemoryHigh + MemoryMax and no MemoryMin."""
    return "\n".join(
        [
            "[Unit]",
            f"Description=IFNOTUS environment resource slice ({slice_name})",
            "Before=slices.target",
            "",
            "[Slice]",
            "MemoryAccounting=yes",
            "CPUAccounting=yes",
            "TasksAccounting=yes",
            f"CPUQuota={cpu_quota}",
            f"MemoryHigh={memory_high}",
            f"MemoryMax={memory_max}",
            f"TasksMax={tasks_max}",
            "",
            "[Install]",
            "WantedBy=slices.target",
            "",
        ]
    )


class MemoryPolicyService:
    """Plan / apply Phase 2C shared memory policy."""

    def __init__(self, *, policy: HostResourcePolicy | None = None, backup_root: Path | None = None) -> None:
        self.policy = policy or default_host_resource_policy()
        self.backup_root = backup_root or _BACKUP_ROOT

    def build_row(
        self,
        *,
        env_id: UUID | str,
        domain: str | None,
        status: str,
        plan: PlanView | None,
        source: str = "subscription_plan",
        domain_count: int = 0,
    ) -> MemoryPolicyRow:
        short = str(env_id).split("-")[0]
        slice_name = slice_name_for(env_id)
        live = read_live_slice_limits(slice_name)
        targets = resolve_shared_memory_targets(plan, policy=self.policy, source=source)
        # Domain count must not alter targets (assert via note only).
        warnings = list(targets.warnings)
        if domain_count > 1:
            warnings.append("domain_count_ignored_for_memory")

        classification = targets.plan_class.value
        if targets.source == "unknown_conservative":
            classification = "SHARED_UNKNOWN"

        drift = detect_drift(live=live, targets=targets, env_status=status)
        skip = drift in {
            DRIFT_SUSPENDED_SKIP,
            DRIFT_DEDICATED_POLICY_REQUIRED,
            DRIFT_FIRST_PARTY_EXCLUDED,
        }

        cpu = live.get("CPUQuota") or "25%"
        tasks = live.get("TasksMax") or "40"
        return MemoryPolicyRow(
            environment_id=str(env_id),
            short_id=short,
            domain=domain,
            status=status,
            classification=classification,
            old_memory_high=live.get("MemoryHigh"),
            old_memory_max=live.get("MemoryMax"),
            new_memory_high=str(targets.memory_high_bytes) if not skip else None,
            new_memory_max=str(targets.memory_max_bytes) if not skip else None,
            tasks_max=str(tasks),
            cpu_quota=str(cpu),
            current_usage_bytes=live.get("memory_current_bytes"),
            drift=drift,
            warnings=warnings,
            skipped=skip,
        )

    def apply_row(self, row: MemoryPolicyRow, *, dry_run: bool = True) -> MemoryPolicyRow:
        if row.skipped or row.new_memory_high is None or row.new_memory_max is None:
            return row
        slice_name = slice_name_for(row.environment_id)
        unit_path = _SLICE_DIR / slice_name
        cpu = row.cpu_quota or "25%"
        tasks = row.tasks_max or "40"
        body = render_env_slice_unit_with_high(
            slice_name=slice_name,
            cpu_quota=cpu if cpu.endswith("%") else f"{cpu}%",
            memory_high=row.new_memory_high,
            memory_max=row.new_memory_max,
            tasks_max=tasks,
        )
        if dry_run:
            row.applied = False
            return row

        self.backup_root.mkdir(parents=True, exist_ok=True)
        if unit_path.exists():
            (self.backup_root / f"{slice_name}.bak").write_bytes(unit_path.read_bytes())
        unit_path.write_text(body, encoding="utf-8")
        _systemctl("daemon-reload")
        _systemctl("start", slice_name)
        # Preserve CPUQuota + TasksMax; set High/Max. Never set MemoryMin.
        _systemctl(
            "set-property",
            slice_name,
            f"CPUQuota={cpu if str(cpu).endswith('%') else str(cpu) + '%'}",
            f"MemoryHigh={row.new_memory_high}",
            f"MemoryMax={row.new_memory_max}",
            f"TasksMax={tasks}",
        )
        # Explicitly clear MemoryMin if somehow set
        _systemctl("set-property", slice_name, "MemoryMin=")
        row.applied = True
        return row

    def read_parent_tenants(self) -> dict[str, Any]:
        live = _systemctl_show(TENANTS_SLICE, "MemoryMax", "MemoryHigh", "MemoryCurrent", "MemoryMin")
        cg = resolve_slice_cgroup_path(TENANTS_SLICE)
        current = read_cgroup_memory_current(cg) if cg else _parse_bytes(live.get("MemoryCurrent"))
        return {
            "slice": TENANTS_SLICE,
            "MemoryMax": live.get("MemoryMax"),
            "MemoryHigh": live.get("MemoryHigh"),
            "MemoryMin": live.get("MemoryMin"),
            "memory_current_bytes": current,
            "memory_max_bytes": _parse_bytes(live.get("MemoryMax")),
            "cgroup": str(cg) if cg else None,
            "cgroup_memory_max": (cg / "memory.max").read_text().strip() if cg and (cg / "memory.max").is_file() else None,
        }

    def apply_parent_tenants_memory_max(self, *, dry_run: bool = True) -> dict[str, Any]:
        """Set tenants parent MemoryMax=30G. Never MemoryMin. Never 39G."""
        target = gib_to_bytes(self.policy.tenant_normal_pool_gb)
        before = self.read_parent_tenants()
        report: dict[str, Any] = {
            "dry_run": dry_run,
            "slice": TENANTS_SLICE,
            "before": before,
            "target_memory_max_bytes": target,
            "target_memory_max_gib": self.policy.tenant_normal_pool_gb,
            "applied": False,
            "ok": False,
            "errors": [],
        }
        current = before.get("memory_current_bytes") or 0
        if current >= target:
            report["errors"].append(
                f"tenant parent memory.current ({current}) >= target MemoryMax ({target}); refuse apply"
            )
            return report
        if dry_run:
            report["ok"] = True
            return report

        unit_path = _SLICE_DIR / TENANTS_SLICE
        self.backup_root.mkdir(parents=True, exist_ok=True)
        if unit_path.exists():
            (self.backup_root / f"{TENANTS_SLICE}.bak").write_bytes(unit_path.read_bytes())
            text = unit_path.read_text(encoding="utf-8")
            if "MemoryMax=" in text:
                text = re.sub(r"^MemoryMax=.*$", f"MemoryMax={target}", text, flags=re.M)
            else:
                text = text.replace("[Slice]\n", f"[Slice]\nMemoryMax={target}\n", 1)
            # Ensure no MemoryMin
            text = "\n".join(ln for ln in text.splitlines() if not ln.strip().startswith("MemoryMin="))
            if not text.endswith("\n"):
                text += "\n"
            unit_path.write_text(text, encoding="utf-8")
        else:
            unit_path.write_text(
                "\n".join(
                    [
                        "[Unit]",
                        f"Description=IFNOTUS SHARED_TENANT parent — {self.policy.tenant_normal_pool_gb:g} GiB pool",
                        "Before=slices.target",
                        "",
                        "[Slice]",
                        "MemoryAccounting=yes",
                        "CPUAccounting=yes",
                        "TasksAccounting=yes",
                        f"MemoryMax={target}",
                        "",
                        "[Install]",
                        "WantedBy=slices.target",
                        "",
                    ]
                ),
                encoding="utf-8",
            )
        _systemctl("daemon-reload")
        _systemctl("start", TENANTS_SLICE)
        _systemctl("set-property", TENANTS_SLICE, f"MemoryMax={target}", "MemoryMin=")
        after = self.read_parent_tenants()
        report["after"] = after
        live_max = after.get("cgroup_memory_max") or after.get("MemoryMax")
        report["applied"] = True
        report["ok"] = str(live_max) in {str(target), f"{target}"}
        if not report["ok"]:
            # systemd may show infinity until property sticks — check bytes parse
            parsed = _parse_bytes(str(live_max)) if live_max not in {None, "max", "infinity"} else None
            report["ok"] = parsed == target
        return report

    def rollback_row(self, row: MemoryPolicyRow) -> dict[str, Any]:
        slice_name = slice_name_for(row.environment_id)
        bak = self.backup_root / f"{slice_name}.bak"
        out: dict[str, Any] = {"slice": slice_name, "ok": False}
        if not bak.is_file():
            out["error"] = "no_backup"
            return out
        unit_path = _SLICE_DIR / slice_name
        unit_path.write_bytes(bak.read_bytes())
        _systemctl("daemon-reload")
        _systemctl("start", slice_name)
        parsed = parse_legacy_slice_limits(bak.read_text(encoding="utf-8", errors="replace"))
        args = ["set-property", slice_name]
        if parsed.get("CPUQuota"):
            args.append(f"CPUQuota={parsed['CPUQuota']}")
        if parsed.get("MemoryMax"):
            args.append(f"MemoryMax={parsed['MemoryMax']}")
        if parsed.get("TasksMax"):
            args.append(f"TasksMax={parsed['TasksMax']}")
        # Clear MemoryHigh if restoring legacy without it
        high = None
        for line in bak.read_text(encoding="utf-8", errors="replace").splitlines():
            if line.strip().startswith("MemoryHigh="):
                high = line.split("=", 1)[1].strip()
        if high:
            args.append(f"MemoryHigh={high}")
        else:
            args.append("MemoryHigh=infinity")
        _systemctl(*args)
        out["ok"] = True
        return out


def tasksmax_warning(*, tasks_current: int | None, tasks_max: int | None, pm_max_children: int | None = None) -> str | None:
    if tasks_max is None or tasks_max <= 0:
        return None
    current = int(tasks_current or 0)
    remaining = tasks_max - current
    headroom = remaining / tasks_max
    if remaining < 4 or headroom < 0.25:
        return (
            f"TASKSMAX_WARNING current={current} max={tasks_max} remaining={remaining} "
            f"pm.max_children={pm_max_children}"
        )
    return None


def _systemctl(*args: str) -> subprocess.CompletedProcess[str]:
    systemctl = shutil.which("systemctl") or "systemctl"
    return subprocess.run(
        [systemctl, *args],
        check=False,
        capture_output=True,
        text=True,
        timeout=60,
    )


def _systemctl_show(unit: str, *props: str) -> dict[str, str]:
    args = ["show", unit, "--no-pager"]
    for p in props:
        args.append(f"-p{p}")
    proc = _systemctl(*args)
    out: dict[str, str] = {}
    for line in (proc.stdout or "").splitlines():
        if "=" in line:
            k, v = line.split("=", 1)
            out[k] = v
    return out


def format_reconcile_report(rows: list[MemoryPolicyRow], *, parent: dict[str, Any] | None = None) -> str:
    lines = ["environment classification old_high old_max new_high new_max tasks usage drift warnings"]
    for r in rows:
        lines.append(
            f"{r.short_id} {r.classification} {r.old_memory_high} {r.old_memory_max} "
            f"{r.new_memory_high} {r.new_memory_max} {r.tasks_max} {r.current_usage_bytes} "
            f"{r.drift} {','.join(r.warnings) or '-'}"
        )
    if parent:
        lines.append("")
        lines.append(
            f"parent {parent.get('slice')} current={parent.get('memory_current_bytes')} "
            f"max={parent.get('MemoryMax')}"
        )
    return "\n".join(lines)
