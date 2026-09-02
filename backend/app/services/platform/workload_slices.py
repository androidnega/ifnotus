"""IFNOTUS systemd/cgroup v2 workload hierarchy (Phase 2A → 3B-1).

Valid systemd slice naming encodes parentage with dashes:

  ifnotus-workloads.slice
  ├── ifnotus-workloads-priority.slice          (MemoryHigh=8 GiB normal)
  │   ├── ifnotus-workloads-priority-core.slice
  │   └── ifnotus-workloads-priority-products.slice
  └── ifnotus-workloads-tenants.slice           (MemoryMax=30 GiB)
      └── ifnotus-workloads-tenants-env-<shortid>.slice

Phase 3B-1: priority MemoryHigh=8G, MemoryMax unlimited; no MemoryMin; no emergency grants.
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
from app.services.platform.resource_policy import gib_to_bytes

logger = get_logger(__name__)

# Phase 2C tenant parent — preserved unchanged in 3B-1.
TENANTS_MEMORY_MAX_BYTES = gib_to_bytes(30)
TENANTS_MEMORY_MAX = str(TENANTS_MEMORY_MAX_BYTES)

_SLICE_DIR = Path("/etc/systemd/system")
_CGROUP_ROOT = Path("/sys/fs/cgroup")
_BACKUP_DIR = Path("/var/backups/ifnotus/systemd-phase2a")

WORKLOADS_ROOT = "ifnotus-workloads.slice"
PRIORITY_SLICE = "ifnotus-workloads-priority.slice"
PRIORITY_CORE_SLICE = "ifnotus-workloads-priority-core.slice"
PRIORITY_PRODUCTS_SLICE = "ifnotus-workloads-priority-products.slice"
TENANTS_SLICE = "ifnotus-workloads-tenants.slice"

# Back-compat aliases (pre-3B-1 names → priority children)
CORE_SLICE = PRIORITY_CORE_SLICE
PRODUCTS_SLICE = PRIORITY_PRODUCTS_SLICE
LEGACY_CORE_SLICE = "ifnotus-workloads-core.slice"
LEGACY_PRODUCTS_SLICE = "ifnotus-workloads-products.slice"

PRIORITY_MEMORY_HIGH_BYTES = gib_to_bytes(8)
PRIORITY_MEMORY_HIGH = str(PRIORITY_MEMORY_HIGH_BYTES)

# Legacy env slice prefix (pre-Phase 2A). Still recognized for migration/read_usage.
LEGACY_ENV_SLICE_PREFIX = "ifnotus-env-"
ENV_SLICE_PREFIX = "ifnotus-workloads-tenants-env-"

PLATFORM_CORE_UNITS: tuple[str, ...] = (
    "ifnotus-api.service",
    "ifnotus-worker.service",
)

FIRST_PARTY_UNITS: tuple[str, ...] = (
    "votebridge.service",
    "votebridge-celery.service",
    "votebridge-daphne.service",
    "quizsnap.service",
    "quizsnap-reverb.service",
)

# Confirmed IFNOTUS-owned apps under /srv/apps/csdttu (no CustomerEnvironment).
ADDITIONAL_FIRST_PARTY_UNITS: tuple[str, ...] = (
    "documento.service",
    "cliq_tech_hangout.service",
    "gunicorn-ceeu.service",
)

# Legacy Quiz app still scheduled from root crontab (/srv/apps/quiz).
QUIZ_LEGACY_SCHEDULE_UNITS: tuple[str, ...] = (
    "quiz-schedule.service",
    "quiz-schedule.timer",
)

SHARED_INFRASTRUCTURE_UNITS: tuple[str, ...] = (
    "nginx.service",
    "postgresql.service",
    "postgresql@16-main.service",
    "redis-server.service",
    "php8.3-fpm.service",
    "mysql.service",
    "named.service",
)

# Phase 2B — PHP worker isolation options (design only; not deployed in 2A).
PHASE_2B_PHP_FPM_RECOMMENDATION: dict[str, Any] = {
    "current": {
        "master": "php8.3-fpm.service",
        "pools": "~171 ifnotus-*.conf under /etc/php/8.3/fpm/pool.d",
        "worker_isolation": "Unix UID per pool; workers remain in php8.3-fpm.service cgroup",
    },
    "options_evaluated": [
        {
            "id": "A",
            "name": "per-environment PHP-FPM systemd service",
            "pros": ["true cgroup MemoryMax per tenant", "restart isolation"],
            "cons": ["~N daemons RAM overhead", "socket/nginx rewrite", "complex deploy"],
        },
        {
            "id": "B",
            "name": "grouped FPM instances (shared among small cohorts)",
            "pros": ["fewer masters than A", "partial isolation"],
            "cons": ["noisy-neighbor within group", "still complex"],
        },
        {
            "id": "C",
            "name": "systemd-managed pool wrappers / Delegate=",
            "pros": ["keeps one master pattern"],
            "cons": ["FPM does not natively move workers to foreign cgroups safely"],
        },
        {
            "id": "D",
            "name": "cgroup migration hooks (unsupported)",
            "pros": ["appears simple"],
            "cons": ["racy", "breaks on worker recycle", "unsafe for production"],
        },
    ],
    "recommendation": "A-env",
    "recommendation_detail": (
        "Phase 2B: one php-fpm master per CustomerEnvironment (not per hostname), "
        "loading all hostname pools for that env, Slice=ifnotus-workloads-tenants-env-*.slice. "
        "Preserve per-hostname sockets for Nginx. Canary one low-risk shared PHP tenant first. "
        "See app.services.platform.php_fpm_env_design. Do not change MemoryMax in 2B."
    ),
    "production_php_architecture_changed": True,
}

SFTP_ACCOUNTING_STATUS = {
    "accounting_supported": "PHASE_2B4_PAM_ATTACH",
    "detail": (
        "OpenSSH internal-sftp remains chrooted. Session PIDs are attached to "
        "a leaf cgroup under ifnotus-workloads-tenants-env-*.slice (sftp-sessions) via pam_exec "
        "/usr/local/sbin/ifnotus-sftp-cgroup-attach using authenticated Unix username → slice map."
    ),
    "changed": True,
}


@dataclass(frozen=True)
class SliceSpec:
    name: str
    description: str
    memory_accounting: bool = True
    cpu_accounting: bool = True
    tasks_accounting: bool = True
    io_accounting: bool = True
    memory_max: str | None = None
    memory_high: str | None = None
    extra_slice_lines: tuple[str, ...] = ()


@dataclass
class ReconcileAction:
    action: str
    path: str
    detail: str = ""
    content: str | None = None


@dataclass
class ReconcileReport:
    dry_run: bool
    actions: list[ReconcileAction] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    env_reparented: int = 0
    legacy_limits_preserved: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "dry_run": self.dry_run,
            "actions": [asdict(a) for a in self.actions],
            "errors": list(self.errors),
            "warnings": list(self.warnings),
            "env_reparented": self.env_reparented,
            "legacy_limits_preserved": self.legacy_limits_preserved,
        }


def env_short_id(environment_id: UUID | str) -> str:
    short = str(environment_id).split("-")[0].lower()
    return re.sub(r"[^a-z0-9]", "", short)[:12] or "env"


def slice_name_for(environment_id: UUID | str) -> str:
    """Canonical Phase 2A tenant environment slice (under tenants parent)."""
    return f"{ENV_SLICE_PREFIX}{env_short_id(environment_id)}.slice"


def legacy_slice_name_for(environment_id: UUID | str) -> str:
    return f"{LEGACY_ENV_SLICE_PREFIX}{env_short_id(environment_id)}.slice"


def hierarchy_slice_specs() -> tuple[SliceSpec, ...]:
    """Phase 3B-1 hierarchy: priority (MemoryHigh=8G) + tenants (MemoryMax may be set live)."""
    return (
        SliceSpec(
            name=WORKLOADS_ROOT,
            description="IFNOTUS managed workloads root",
        ),
        SliceSpec(
            name=PRIORITY_SLICE,
            description="IFNOTUS priority normal pool (core + first-party) — MemoryHigh 8 GiB",
            memory_high=PRIORITY_MEMORY_HIGH,
        ),
        SliceSpec(
            name=PRIORITY_CORE_SLICE,
            description="IFNOTUS PLATFORM_CORE under priority pool (API + worker)",
        ),
        SliceSpec(
            name=PRIORITY_PRODUCTS_SLICE,
            description="IFNOTUS FIRST_PARTY_PRODUCT under priority pool",
        ),
        SliceSpec(
            name=TENANTS_SLICE,
            description="IFNOTUS SHARED_TENANT parent — MemoryMax 30 GiB (Phase 2C)",
            memory_max=TENANTS_MEMORY_MAX,
        ),
    )


def render_hierarchy_slice_unit(spec: SliceSpec) -> str:
    lines = [
        "[Unit]",
        f"Description={spec.description}",
        "Before=slices.target",
        "",
        "[Slice]",
    ]
    if spec.memory_accounting:
        lines.append("MemoryAccounting=yes")
    if spec.cpu_accounting:
        lines.append("CPUAccounting=yes")
    if spec.tasks_accounting:
        lines.append("TasksAccounting=yes")
    if spec.io_accounting:
        lines.append("IOAccounting=yes")
    if spec.memory_high:
        lines.append(f"MemoryHigh={spec.memory_high}")
    if spec.memory_max:
        lines.append(f"MemoryMax={spec.memory_max}")
    # Never emit MemoryMin in hierarchy units.
    lines.extend(spec.extra_slice_lines)
    lines += ["", "[Install]", "WantedBy=slices.target", ""]
    return "\n".join(lines)


def render_service_slice_dropin(slice_name: str, *, comment: str) -> str:
    return "\n".join(
        [
            "[Service]",
            f"# {comment}",
            f"Slice={slice_name}",
            "MemoryAccounting=yes",
            "CPUAccounting=yes",
            "TasksAccounting=yes",
            "",
        ]
    )


def parse_legacy_slice_limits(unit_text: str) -> dict[str, str]:
    """Extract CPUQuota / MemoryMax / TasksMax from an existing slice unit body."""
    out: dict[str, str] = {}
    for line in unit_text.splitlines():
        stripped = line.strip()
        if stripped.startswith("CPUQuota="):
            out["CPUQuota"] = stripped.split("=", 1)[1].strip()
        elif stripped.startswith("MemoryMax="):
            out["MemoryMax"] = stripped.split("=", 1)[1].strip()
        elif stripped.startswith("TasksMax="):
            out["TasksMax"] = stripped.split("=", 1)[1].strip()
    return out


def render_env_slice_unit(
    *,
    slice_name: str,
    cpu_quota: str,
    memory_max: str,
    tasks_max: str,
) -> str:
    """Preserve legacy limit values exactly while nesting under tenants parent."""
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
            f"MemoryMax={memory_max}",
            f"TasksMax={tasks_max}",
            "",
            "[Install]",
            "WantedBy=slices.target",
            "",
        ]
    )


def validate_child_limits_vs_parent(
    *,
    child_memory_max_bytes: int | None,
    parent_memory_max_bytes: int | None,
) -> list[str]:
    """Return validation errors if child MemoryMax exceeds an enforced parent max."""
    errors: list[str] = []
    if parent_memory_max_bytes is None or child_memory_max_bytes is None:
        return errors
    if child_memory_max_bytes > parent_memory_max_bytes:
        errors.append(
            f"child MemoryMax ({child_memory_max_bytes}) exceeds parent "
            f"MemoryMax ({parent_memory_max_bytes})"
        )
    return errors


def slice_cgroup_candidates(slice_name: str) -> list[Path]:
    """Possible cgroup v2 paths for a slice (nested hierarchy encoded in name)."""
    # ifnotus-workloads-tenants-env-abc.slice → ifnotus-workloads.slice/ifnotus-workloads-tenants.slice/...
    parts = slice_name.removesuffix(".slice").split("-")
    paths: list[Path] = []
    # Full unit directory under cgroup root (systemd often flattens with .slice suffix dirs)
    paths.append(_CGROUP_ROOT / slice_name)
    # Nested path building
    nested = _CGROUP_ROOT
    built: list[str] = []
    for part in parts:
        built.append(part)
        nested = nested / f"{'-'.join(built)}.slice"
        paths.append(nested)
    paths.append(_CGROUP_ROOT / "system.slice" / slice_name)
    # Deduplicate preserving order
    seen: set[str] = set()
    out: list[Path] = []
    for p in paths:
        key = str(p)
        if key not in seen:
            seen.add(key)
            out.append(p)
    return out


def resolve_slice_cgroup_path(slice_name: str) -> Path | None:
    """Resolve the cgroup directory for a slice unit.

    Prefer the leaf path whose basename equals ``slice_name``. Intermediate
    parents (e.g. ``ifnotus.slice`` for ``ifnotus-workloads-….slice``) must not
    win — that would attribute host-wide usage to one environment.

    Also consult ``systemctl show -p ControlGroup`` when available so nested
    paths under ``ifnotus.slice/…`` are found reliably.
    """
    # Fast path: ask systemd for the live ControlGroup.
    try:
        proc = subprocess.run(
            ["systemctl", "show", slice_name, "-p", "ControlGroup", "--value"],
            capture_output=True,
            text=True,
            check=False,
            timeout=5,
        )
        cg = (proc.stdout or "").strip()
        if cg and cg != "/":
            # ControlGroup is like /ifnotus.slice/ifnotus-workloads.slice/...
            candidate = _CGROUP_ROOT / cg.lstrip("/")
            if candidate.is_dir() and candidate.name == slice_name:
                return candidate
    except (OSError, subprocess.TimeoutExpired):
        pass

    candidates = slice_cgroup_candidates(slice_name)
    for path in candidates:
        if path.is_dir() and path.name == slice_name:
            return path
    return None


def read_cgroup_memory_current(cgroup_path: Path) -> int | None:
    """Kernel cgroup-charged memory (source of truth for MemoryMax enforcement)."""
    try:
        return int((cgroup_path / "memory.current").read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return None


MEMORY_ACCOUNTING_NOTE = (
    "memory.current is cgroup-charged memory (enforcement source of truth). "
    "Summed process RSS is typically higher because shared library/file pages "
    "are counted once in the cgroup but appear in each process RSS."
)


def examflow_health_classification(*, user: str | None, slice_path: str | None) -> dict[str, Any]:
    """ExamFlow cannot be classified healthy while running as root."""
    u = (user or "").strip().lower()
    root = u in {"", "root"}
    in_tenant = bool(slice_path and "tenants-env-" in slice_path)
    healthy = (not root) and in_tenant
    return {
        "healthy": healthy,
        "root_execution": root,
        "in_tenant_slice": in_tenant,
        "code": None if healthy else "RESOURCE_ISOLATION_VIOLATION",
    }


def classify_process_hierarchy(*, cgroup_path: str | None, expected: str) -> dict[str, Any]:
    """Detect whether a process cgroup sits under the expected workload hierarchy.

    ``expected`` is one of: core | products | priority | tenants | infrastructure | unknown
    """
    path = (cgroup_path or "").strip()
    under_workloads = WORKLOADS_ROOT.removesuffix(".slice") in path or "/ifnotus-workloads.slice/" in path
    under_priority = "workloads-priority" in path
    under_core = "workloads-priority-core" in path or (
        "workloads-core" in path and "priority" not in path
    )
    under_products = "workloads-priority-products" in path or (
        "workloads-products" in path and "priority" not in path
    )
    under_tenants = "workloads-tenants" in path
    under_system = "/system.slice/" in path or path.endswith("system.slice")

    ok = False
    if expected == "core":
        ok = under_core and under_priority
    elif expected == "products":
        ok = under_products and under_priority
    elif expected == "priority":
        ok = under_priority
    elif expected == "tenants":
        ok = under_tenants
    elif expected == "infrastructure":
        ok = under_system or (not under_tenants and not under_priority)
    else:
        ok = False

    escaped = False
    if expected in {"core", "products", "priority", "tenants"} and under_system and not under_workloads:
        escaped = True

    return {
        "expected": expected,
        "ok": ok,
        "escaped_workload_hierarchy": escaped,
        "under_workloads": under_workloads,
        "under_priority": under_priority,
        "under_core": under_core,
        "under_products": under_products,
        "under_tenants": under_tenants,
        "code": None if ok and not escaped else "WORKLOAD_OUTSIDE_EXPECTED_HIERARCHY",
    }


class WorkloadSliceReconciler:
    """Generate / apply Phase 2A hierarchy, drop-ins, and env re-parenting."""

    def __init__(self, *, slice_dir: Path | None = None, backup_dir: Path | None = None):
        self.slice_dir = slice_dir or _SLICE_DIR
        self.backup_dir = backup_dir or _BACKUP_DIR

    def plan_hierarchy(self) -> list[ReconcileAction]:
        actions: list[ReconcileAction] = []
        for spec in hierarchy_slice_specs():
            path = self.slice_dir / spec.name
            content = render_hierarchy_slice_unit(spec)
            actions.append(
                ReconcileAction(
                    action="write_slice",
                    path=str(path),
                    detail=spec.description,
                    content=content,
                )
            )
        return actions

    def plan_service_dropins(self) -> list[ReconcileAction]:
        actions: list[ReconcileAction] = []
        for unit in PLATFORM_CORE_UNITS:
            drop = self.slice_dir / f"{unit}.d" / "10-ifnotus-workload-slice.conf"
            actions.append(
                ReconcileAction(
                    action="write_dropin",
                    path=str(drop),
                    detail=f"Place {unit} under {PRIORITY_CORE_SLICE}",
                    content=render_service_slice_dropin(
                        PRIORITY_CORE_SLICE,
                        comment="Phase 3B-1 PLATFORM_CORE under priority-core slice",
                    ),
                )
            )
        for unit in (*FIRST_PARTY_UNITS, *ADDITIONAL_FIRST_PARTY_UNITS):
            drop = self.slice_dir / f"{unit}.d" / "10-ifnotus-workload-slice.conf"
            actions.append(
                ReconcileAction(
                    action="write_dropin",
                    path=str(drop),
                    detail=f"Place {unit} under {PRIORITY_PRODUCTS_SLICE}",
                    content=render_service_slice_dropin(
                        PRIORITY_PRODUCTS_SLICE,
                        comment="Phase 3B-1 FIRST_PARTY_PRODUCT under priority-products slice",
                    ),
                )
            )
        return actions

    def plan_retire_legacy_core_product_slices(self) -> list[ReconcileAction]:
        """Stop/remove pre-3B-1 ifnotus-workloads-core/products.slice unit files after reparent."""
        actions: list[ReconcileAction] = []
        for name in (LEGACY_CORE_SLICE, LEGACY_PRODUCTS_SLICE):
            path = self.slice_dir / name
            if path.is_file():
                actions.append(
                    ReconcileAction(
                        action="remove_legacy_slice",
                        path=str(path),
                        detail=f"Retire {name} after priority-* children are active",
                    )
                )
        return actions

    def plan_env_reparent(
        self,
        *,
        environment_id: UUID | str,
        cpu_quota: str | None = None,
        memory_max: str | None = None,
        tasks_max: str | None = None,
        fallback_cpu_quota: str | None = None,
        fallback_memory_max: str | None = None,
        fallback_tasks_max: str | None = None,
    ) -> list[ReconcileAction]:
        """Re-parent one env: new nested name, preserve limits from legacy unit when present.

        Precedence: explicit overrides > existing unit file (legacy or new) >
        fallback_* (typically from env DB fields) > conservative defaults.
        """
        actions: list[ReconcileAction] = []
        new_name = slice_name_for(environment_id)
        legacy_name = legacy_slice_name_for(environment_id)
        legacy_path = self.slice_dir / legacy_name
        new_path = self.slice_dir / new_name

        limits = {
            "CPUQuota": fallback_cpu_quota or "25%",
            "MemoryMax": fallback_memory_max or "268435456",
            "TasksMax": fallback_tasks_max or "40",
        }
        if legacy_path.is_file():
            parsed = parse_legacy_slice_limits(legacy_path.read_text(encoding="utf-8", errors="replace"))
            limits.update({k: v for k, v in parsed.items() if v})
        elif new_path.is_file():
            parsed = parse_legacy_slice_limits(new_path.read_text(encoding="utf-8", errors="replace"))
            limits.update({k: v for k, v in parsed.items() if v})

        if cpu_quota:
            limits["CPUQuota"] = cpu_quota
        if memory_max:
            limits["MemoryMax"] = memory_max
        if tasks_max:
            limits["TasksMax"] = tasks_max

        body = render_env_slice_unit(
            slice_name=new_name,
            cpu_quota=limits["CPUQuota"],
            memory_max=limits["MemoryMax"],
            tasks_max=limits["TasksMax"],
        )
        actions.append(
            ReconcileAction(
                action="write_slice",
                path=str(new_path),
                detail=f"Reparent {legacy_name} → {new_name} preserving limits {limits}",
                content=body,
            )
        )
        if legacy_path.is_file():
            actions.append(
                ReconcileAction(
                    action="remove_legacy_slice",
                    path=str(legacy_path),
                    detail=f"Remove legacy slice after {new_name} is active",
                )
            )
        return actions

    def plan_quizsnap_schedule_units(self) -> list[ReconcileAction]:
        """Replace root crontab quizsnap schedule with systemd timer in products slice."""
        service = self.slice_dir / "quizsnap-schedule.service"
        timer = self.slice_dir / "quizsnap-schedule.timer"
        svc_body = "\n".join(
            [
                "[Unit]",
                "Description=QuizSnap artisan schedule:run (IFNOTUS products slice)",
                "After=network.target",
                "",
                "[Service]",
                "Type=oneshot",
                f"Slice={PRIORITY_PRODUCTS_SLICE}",
                "User=www-data",
                "Group=www-data",
                "WorkingDirectory=/srv/apps/quizsnap",
                "ExecStart=/usr/bin/php artisan schedule:run",
                "Nice=5",
                "",
            ]
        )
        timer_body = "\n".join(
            [
                "[Unit]",
                "Description=Run QuizSnap scheduler every minute",
                "",
                "[Timer]",
                "OnCalendar=*:*:00",
                "AccuracySec=1s",
                "Persistent=true",
                "",
                "[Install]",
                "WantedBy=timers.target",
                "",
            ]
        )
        return [
            ReconcileAction(
                action="write_unit",
                path=str(service),
                detail="QuizSnap schedule oneshot in priority-products slice",
                content=svc_body,
            ),
            ReconcileAction(
                action="write_unit",
                path=str(timer),
                detail="QuizSnap schedule timer",
                content=timer_body,
            ),
        ]

    def plan_quiz_legacy_schedule_units(self) -> list[ReconcileAction]:
        """Contain root-crontab /srv/apps/quiz artisan schedule under priority-products."""
        service = self.slice_dir / "quiz-schedule.service"
        timer = self.slice_dir / "quiz-schedule.timer"
        svc_body = "\n".join(
            [
                "[Unit]",
                "Description=Legacy Quiz artisan schedule:run (priority-products slice)",
                "After=network.target",
                "",
                "[Service]",
                "Type=oneshot",
                f"Slice={PRIORITY_PRODUCTS_SLICE}",
                "User=www-data",
                "Group=www-data",
                "WorkingDirectory=/srv/apps/quiz",
                "ExecStart=/usr/bin/php artisan schedule:run",
                "Nice=5",
                "",
            ]
        )
        timer_body = "\n".join(
            [
                "[Unit]",
                "Description=Run legacy Quiz scheduler every minute",
                "",
                "[Timer]",
                "OnCalendar=*:*:00",
                "AccuracySec=1s",
                "Persistent=true",
                "",
                "[Install]",
                "WantedBy=timers.target",
                "",
            ]
        )
        return [
            ReconcileAction(
                action="write_unit",
                path=str(service),
                detail="Legacy Quiz schedule oneshot in priority-products",
                content=svc_body,
            ),
            ReconcileAction(
                action="write_unit",
                path=str(timer),
                detail="Legacy Quiz schedule timer",
                content=timer_body,
            ),
        ]

    def apply_actions(self, actions: list[ReconcileAction], *, dry_run: bool) -> ReconcileReport:
        report = ReconcileReport(dry_run=dry_run)
        report.actions = list(actions)
        if dry_run:
            report.warnings.append("dry-run only — no files written, no daemon-reload")
            return report

        self.backup_dir.mkdir(parents=True, exist_ok=True)
        for act in actions:
            path = Path(act.path)
            try:
                if act.action in {"write_slice", "write_dropin", "write_unit"}:
                    if path.exists():
                        bak = self.backup_dir / f"{path.name}.bak"
                        if path.is_file():
                            bak.write_bytes(path.read_bytes())
                    path.parent.mkdir(parents=True, exist_ok=True)
                    assert act.content is not None
                    path.write_text(act.content, encoding="utf-8")
                elif act.action == "remove_legacy_slice":
                    if path.exists():
                        bak = self.backup_dir / f"{path.name}.bak"
                        bak.write_bytes(path.read_bytes())
                        # stop best-effort
                        self._systemctl("stop", path.name)
                        path.unlink()
                if "tenants-env-" in path.name and act.action == "write_slice":
                    report.env_reparented += 1
            except OSError as exc:
                report.errors.append(f"{act.action} {path}: {exc}")
                report.legacy_limits_preserved = False
        return report

    @staticmethod
    def _systemctl(*args: str) -> subprocess.CompletedProcess[str]:
        systemctl = shutil.which("systemctl") or "systemctl"
        return subprocess.run(
            [systemctl, *args],
            check=False,
            capture_output=True,
            text=True,
            timeout=60,
        )


def systemd_analyze_verify(unit_paths: list[str]) -> tuple[bool, str]:
    binary = shutil.which("systemd-analyze")
    if not binary:
        return True, "systemd-analyze missing — skipped"
    proc = subprocess.run(
        [binary, "verify", *unit_paths],
        check=False,
        capture_output=True,
        text=True,
        timeout=60,
    )
    # verify writes warnings to stderr even on success
    ok = proc.returncode == 0
    return ok, (proc.stdout or "") + (proc.stderr or "")
