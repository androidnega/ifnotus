"""Central IFNOTUS resource governance policy (Phase 1).

Authoritative capacity / classification / target resolution for later enforcement.
This module MUST NOT write cgroups, systemd units, quotas, or mutate plan/env RAM
in the database. Phase 1 is policy foundation only.

Logical host capacity class (default):

  OS safety 1 + Core 8 + Tenant pool 30 + Emergency 9 = 48 GB

Memory targets for shared hosting are demand-driven policy — NOT MemoryMin
hard reservations. Do not sum (N tenants × normal target) as physical RAM.

Resources belong to CustomerEnvironment / hosting account — never to domain count.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, replace
from decimal import Decimal
from enum import StrEnum
from typing import Any, Mapping, Protocol

# ---------------------------------------------------------------------------
# Units — prefer binary GiB for Linux memory limits
# ---------------------------------------------------------------------------

BYTES_PER_GIB = 1024**3
BYTES_PER_GB = 1000**3  # decimal GB when explicitly required


def gib_to_bytes(gib: float | int | Decimal) -> int:
    return int(Decimal(str(gib)) * BYTES_PER_GIB)


def bytes_to_gib(num_bytes: int | float) -> float:
    return float(num_bytes) / float(BYTES_PER_GIB)


def gb_to_bytes(gb: float | int | Decimal) -> int:
    """Decimal GB → bytes (storage marketing units). Prefer explicit call sites."""
    return int(Decimal(str(gb)) * BYTES_PER_GB)


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class WorkloadClass(StrEnum):
    PLATFORM_CORE = "PLATFORM_CORE"
    FIRST_PARTY_PRODUCT = "FIRST_PARTY_PRODUCT"
    SHARED_TENANT = "SHARED_TENANT"
    VPS_STYLE_TENANT = "VPS_STYLE_TENANT"
    SYSTEM_INFRASTRUCTURE = "SYSTEM_INFRASTRUCTURE"
    UNCLASSIFIED = "UNCLASSIFIED"


class PlanResourceClass(StrEnum):
    SHARED_LOW = "SHARED_LOW"
    SHARED_STANDARD = "SHARED_STANDARD"
    VPS_STYLE = "VPS_STYLE"
    VDS_STYLE = "VDS_STYLE"
    CUSTOM = "CUSTOM"


class PlanCompatibility(StrEnum):
    COMPATIBLE_SHARED = "COMPATIBLE_SHARED"
    DEDICATED_POLICY_REQUIRED = "DEDICATED_POLICY_REQUIRED"
    INVALID_RESOURCE_CONFIGURATION = "INVALID_RESOURCE_CONFIGURATION"


class IsolationSeverity(StrEnum):
    BLOCKER = "BLOCKER"
    WARNING = "WARNING"
    INFO = "INFO"


class StoragePoolSupport(StrEnum):
    YES = "YES"
    REQUIRES_DEDICATED_POLICY = "REQUIRES_DEDICATED_POLICY"
    NO = "NO"


# ---------------------------------------------------------------------------
# Protocols / lightweight plan views (avoid DB coupling in pure functions)
# ---------------------------------------------------------------------------


class PlanLike(Protocol):
    slug: str
    name: str
    price_monthly: Decimal | float | int
    ram_gb: Decimal | float | int
    storage_gb: int | float | Decimal
    features: Mapping[str, Any] | None


@dataclass(frozen=True)
class PlanView:
    """In-memory plan shape for tests and CLI without ORM mutation."""

    slug: str
    name: str
    price_monthly: float
    ram_gb: float
    storage_gb: float
    features: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class HostResourcePolicy:
    """Configured host capacity class (not live MemAvailable)."""

    physical_ram_gb: float = 48.0
    os_safety_reserve_gb: float = 1.0
    core_normal_gb: float = 8.0
    tenant_normal_pool_gb: float = 30.0
    emergency_pool_gb: float = 9.0

    tenant_low_plan_normal_gb: float = 2.0
    tenant_standard_plan_normal_gb: float = 6.0
    tenant_individual_burst_max_gb: float = 12.0

    core_storage_reserve_gb: float = 40.0
    tenant_storage_pool_gb: float = 140.0

    shared_price_threshold_ghs: float = 100.0

    def total_allocated_ram_gb(self) -> float:
        return (
            self.os_safety_reserve_gb
            + self.core_normal_gb
            + self.tenant_normal_pool_gb
            + self.emergency_pool_gb
        )

    def snapshot(self) -> dict[str, float]:
        return {
            "host_ram_gb": self.physical_ram_gb,
            "os_reserve_gb": self.os_safety_reserve_gb,
            "core_normal_gb": self.core_normal_gb,
            "tenant_normal_pool_gb": self.tenant_normal_pool_gb,
            "emergency_pool_gb": self.emergency_pool_gb,
            "shared_low_normal_gb": self.tenant_low_plan_normal_gb,
            "shared_standard_normal_gb": self.tenant_standard_plan_normal_gb,
            "shared_burst_max_gb": self.tenant_individual_burst_max_gb,
            "core_storage_reserve_gb": self.core_storage_reserve_gb,
            "tenant_storage_pool_gb": self.tenant_storage_pool_gb,
        }


@dataclass(frozen=True)
class PolicyValidationIssue:
    code: str
    message: str
    severity: str = "error"  # error | warning


@dataclass(frozen=True)
class PolicyValidationResult:
    ok: bool
    errors: tuple[PolicyValidationIssue, ...] = ()
    warnings: tuple[PolicyValidationIssue, ...] = ()


@dataclass(frozen=True)
class MemoryEntitlement:
    """Distinguish plan metadata from future targets — do not collapse into one field."""

    configured_plan_ram_gb: float
    normal_target_ram_gb: float | None
    burst_ceiling_ram_gb: float | None
    actual_current_ram_usage_gb: float | None = None
    plan_class: PlanResourceClass = PlanResourceClass.SHARED_LOW
    dedicated_policy_required: bool = False
    notes: tuple[str, ...] = ()


@dataclass(frozen=True)
class StorageEntitlement:
    plan_storage_quota_gb: float
    aggregate_pool_allocation_gb: float | None
    actual_disk_usage_gb: float | None = None
    pool_support: StoragePoolSupport = StoragePoolSupport.YES
    dedicated_policy_required: bool = False
    notes: tuple[str, ...] = ()


@dataclass(frozen=True)
class EnvironmentResourcePolicy:
    """Resource policy for one hosting account — independent of domain count."""

    environment_id: str | None
    plan_slug: str | None
    plan_class: PlanResourceClass
    compatibility: PlanCompatibility
    memory: MemoryEntitlement
    storage: StorageEntitlement
    domain_count: int = 0
    notes: tuple[str, ...] = ()


@dataclass(frozen=True)
class WorkloadUnit:
    key: str
    display_name: str
    workload_class: WorkloadClass
    systemd_units: tuple[str, ...] = ()
    notes: str = ""
    requires_tenant_worker_assignment: bool = False
    isolation_violation: bool = False


@dataclass(frozen=True)
class IsolationBlocker:
    code: str
    title: str
    severity: IsolationSeverity
    detail: str
    phase_required: str = "2"


# Known first-party / platform / infra keys (classification only — no moves).
_PLATFORM_CORE_UNITS: tuple[WorkloadUnit, ...] = (
    WorkloadUnit(
        key="ifnotus-api",
        display_name="IFNOTUS API",
        workload_class=WorkloadClass.PLATFORM_CORE,
        systemd_units=("ifnotus-api.service",),
        notes="Future core_normal_gb budget (8 GiB group), not enforced in Phase 1.",
    ),
    WorkloadUnit(
        key="ifnotus-worker",
        display_name="IFNOTUS Worker",
        workload_class=WorkloadClass.PLATFORM_CORE,
        systemd_units=("ifnotus-worker.service",),
        notes="Same PLATFORM_CORE budget as API.",
    ),
)

_FIRST_PARTY_UNITS: tuple[WorkloadUnit, ...] = (
    WorkloadUnit(
        key="votebridge",
        display_name="VoteBridge",
        workload_class=WorkloadClass.FIRST_PARTY_PRODUCT,
        systemd_units=(
            "votebridge.service",
            "votebridge-celery.service",
            "votebridge-daphne.service",
        ),
        notes="Not in tenant 30 GiB pool; may later borrow from shared emergency reserve.",
    ),
    WorkloadUnit(
        key="quizsnap",
        display_name="QuizSnap",
        workload_class=WorkloadClass.FIRST_PARTY_PRODUCT,
        systemd_units=("quizsnap.service", "quizsnap-reverb.service"),
        notes="Not in tenant 30 GiB pool; cron currently under cron.service.",
    ),
)

_SYSTEM_INFRA_UNITS: tuple[WorkloadUnit, ...] = (
    WorkloadUnit(
        key="nginx",
        display_name="Nginx",
        workload_class=WorkloadClass.SYSTEM_INFRASTRUCTURE,
        systemd_units=("nginx.service",),
        notes="Shared front door — not PLATFORM_CORE application budget.",
    ),
    WorkloadUnit(
        key="postgresql",
        display_name="PostgreSQL",
        workload_class=WorkloadClass.SYSTEM_INFRASTRUCTURE,
        systemd_units=("postgresql.service", "postgresql@16-main.service"),
    ),
    WorkloadUnit(
        key="redis",
        display_name="Redis",
        workload_class=WorkloadClass.SYSTEM_INFRASTRUCTURE,
        systemd_units=("redis-server.service",),
    ),
    WorkloadUnit(
        key="php-fpm-master",
        display_name="PHP-FPM master / shared service",
        workload_class=WorkloadClass.SYSTEM_INFRASTRUCTURE,
        systemd_units=("php8.3-fpm.service",),
        requires_tenant_worker_assignment=True,
        notes=(
            "Master process is infrastructure. Tenant PHP workers must eventually be "
            "attributed to SHARED_TENANT env boundaries (requires_tenant_worker_assignment)."
        ),
    ),
)

_ISOLATION_VIOLATION_UNITS: tuple[WorkloadUnit, ...] = (
    WorkloadUnit(
        key="examflow-ifnotus",
        display_name="ExamFlow (ifnotus-managed unit)",
        workload_class=WorkloadClass.UNCLASSIFIED,
        systemd_units=("examflow-ifnotus.service",),
        isolation_violation=True,
        notes=(
            "RESOURCE_ISOLATION_VIOLATION: runs as root from a tenant public_html tree "
            "outside tenant slices. Tenant isolation is incomplete until fixed."
        ),
    ),
)

VPS_STYLE_SLUGS = frozenset({"cloud-vps", "vps", "cloud_vps"})
VDS_STYLE_SLUGS = frozenset({"cloud-vds", "vds", "cloud_vds"})


def default_host_resource_policy() -> HostResourcePolicy:
    return HostResourcePolicy()


def host_resource_policy_from_settings(settings: Any | None = None) -> HostResourcePolicy:
    """Build policy from Settings overrides when present; else defaults."""
    base = default_host_resource_policy()
    if settings is None:
        return base

    def _g(name: str, current: float) -> float:
        val = getattr(settings, name, None)
        if val is None:
            return current
        try:
            return float(val)
        except (TypeError, ValueError):
            return current

    return HostResourcePolicy(
        physical_ram_gb=_g("ifnotus_host_ram_gb", base.physical_ram_gb),
        os_safety_reserve_gb=_g("ifnotus_os_reserve_gb", base.os_safety_reserve_gb),
        core_normal_gb=_g("ifnotus_core_normal_gb", base.core_normal_gb),
        tenant_normal_pool_gb=_g("ifnotus_tenant_pool_gb", base.tenant_normal_pool_gb),
        emergency_pool_gb=_g("ifnotus_emergency_pool_gb", base.emergency_pool_gb),
        tenant_low_plan_normal_gb=_g("ifnotus_shared_low_normal_gb", base.tenant_low_plan_normal_gb),
        tenant_standard_plan_normal_gb=_g(
            "ifnotus_shared_standard_normal_gb", base.tenant_standard_plan_normal_gb
        ),
        tenant_individual_burst_max_gb=_g(
            "ifnotus_shared_burst_max_gb", base.tenant_individual_burst_max_gb
        ),
        core_storage_reserve_gb=_g(
            "ifnotus_core_storage_reserve_gb", base.core_storage_reserve_gb
        ),
        tenant_storage_pool_gb=_g(
            "ifnotus_tenant_storage_pool_gb", base.tenant_storage_pool_gb
        ),
        shared_price_threshold_ghs=_g(
            "ifnotus_shared_price_threshold_ghs", base.shared_price_threshold_ghs
        ),
    )


def validate_resource_policy(policy: HostResourcePolicy) -> PolicyValidationResult:
    errors: list[PolicyValidationIssue] = []
    warnings: list[PolicyValidationIssue] = []

    if policy.physical_ram_gb <= 0:
        errors.append(PolicyValidationIssue("host_ram_invalid", "physical_ram_gb must be > 0"))
    if policy.os_safety_reserve_gb <= 0:
        errors.append(PolicyValidationIssue("os_reserve_invalid", "os_safety_reserve_gb must be > 0"))
    if policy.core_normal_gb <= 0:
        errors.append(PolicyValidationIssue("core_reserve_invalid", "core_normal_gb must be > 0"))
    if policy.tenant_normal_pool_gb <= 0:
        errors.append(PolicyValidationIssue("tenant_pool_invalid", "tenant_normal_pool_gb must be > 0"))
    if policy.emergency_pool_gb < 0:
        errors.append(PolicyValidationIssue("emergency_negative", "emergency_pool_gb must be >= 0"))
    if policy.core_storage_reserve_gb <= 0:
        errors.append(
            PolicyValidationIssue("core_storage_invalid", "core_storage_reserve_gb must be > 0")
        )
    if policy.tenant_storage_pool_gb <= 0:
        errors.append(
            PolicyValidationIssue("tenant_storage_invalid", "tenant_storage_pool_gb must be > 0")
        )

    total = policy.total_allocated_ram_gb()
    # Allow tiny float noise.
    if total - policy.physical_ram_gb > 1e-9:
        errors.append(
            PolicyValidationIssue(
                "ram_over_capacity",
                f"os+core+tenant+emergency ({total} GB) exceeds physical_ram_gb ({policy.physical_ram_gb} GB)",
            )
        )
    elif abs(total - policy.physical_ram_gb) > 1e-6:
        warnings.append(
            PolicyValidationIssue(
                "ram_under_capacity",
                f"os+core+tenant+emergency ({total} GB) != physical_ram_gb ({policy.physical_ram_gb} GB)",
                severity="warning",
            )
        )

    if policy.tenant_individual_burst_max_gb < policy.tenant_standard_plan_normal_gb:
        errors.append(
            PolicyValidationIssue(
                "burst_below_standard",
                "shared burst max must be >= shared standard normal target",
            )
        )
    if policy.tenant_individual_burst_max_gb < policy.tenant_low_plan_normal_gb:
        errors.append(
            PolicyValidationIssue(
                "burst_below_low",
                "shared burst max must be >= shared low normal target",
            )
        )

    if policy.tenant_individual_burst_max_gb > policy.tenant_normal_pool_gb:
        warnings.append(
            PolicyValidationIssue(
                "burst_exceeds_tenant_pool",
                "shared burst max exceeds tenant normal pool — emergency borrowing required later",
                severity="warning",
            )
        )

    return PolicyValidationResult(
        ok=not errors,
        errors=tuple(errors),
        warnings=tuple(warnings),
    )


def _slug(plan: PlanLike | PlanView) -> str:
    return (getattr(plan, "slug", "") or "").strip().lower()


def _features(plan: PlanLike | PlanView) -> dict[str, Any]:
    raw = getattr(plan, "features", None) or {}
    return dict(raw) if isinstance(raw, Mapping) else {}


def _price_ghs(plan: PlanLike | PlanView) -> float:
    try:
        return float(getattr(plan, "price_monthly", 0) or 0)
    except (TypeError, ValueError):
        return 0.0


def _plan_ram_gb(plan: PlanLike | PlanView) -> float:
    try:
        return float(getattr(plan, "ram_gb", 0) or 0)
    except (TypeError, ValueError):
        return 0.0


def _plan_storage_gb(plan: PlanLike | PlanView) -> float:
    try:
        return float(getattr(plan, "storage_gb", 0) or 0)
    except (TypeError, ValueError):
        return 0.0


def classify_plan_resource_class(
    plan: PlanLike | PlanView,
    *,
    policy: HostResourcePolicy | None = None,
) -> PlanResourceClass:
    """Classify a hosting plan without mutating DB values.

    Order: explicit feature override → slug semantics → price threshold.
    """
    policy = policy or default_host_resource_policy()
    feats = _features(plan)
    override = str(feats.get("resource_class") or feats.get("plan_resource_class") or "").upper()
    if override in {c.value for c in PlanResourceClass}:
        return PlanResourceClass(override)

    category = str(feats.get("category") or feats.get("plan_category") or "").lower()
    slug = _slug(plan)

    if slug in VDS_STYLE_SLUGS or "vds" in slug or category in {"vds", "cloud-vds"}:
        return PlanResourceClass.VDS_STYLE
    if slug in VPS_STYLE_SLUGS or "vps" in slug or category in {"vps", "cloud-vps"}:
        return PlanResourceClass.VPS_STYLE
    if feats.get("dedicated_policy") or feats.get("custom_resource_policy"):
        return PlanResourceClass.CUSTOM

    if _price_ghs(plan) >= policy.shared_price_threshold_ghs:
        return PlanResourceClass.SHARED_STANDARD
    return PlanResourceClass.SHARED_LOW


def resolve_normal_memory_target(
    plan: PlanLike | PlanView,
    *,
    policy: HostResourcePolicy | None = None,
) -> float | None:
    """Future normal memory target (GiB). Does NOT write to the database.

    Shared low → 2 GiB; shared standard → 6 GiB.
    VPS/VDS/CUSTOM → preserve explicit plan RAM (dedicated path) as None signal via
    returning configured plan RAM while marking dedicated elsewhere — here we return
    the plan's configured RAM for dedicated classes so callers do not invent 6 GiB.
    """
    policy = policy or default_host_resource_policy()
    plan_class = classify_plan_resource_class(plan, policy=policy)
    if plan_class == PlanResourceClass.SHARED_LOW:
        return float(policy.tenant_low_plan_normal_gb)
    if plan_class == PlanResourceClass.SHARED_STANDARD:
        return float(policy.tenant_standard_plan_normal_gb)
    # VPS / VDS / CUSTOM: do not flatten to shared targets.
    return _plan_ram_gb(plan)


def resolve_burst_memory_limit(
    plan: PlanLike | PlanView,
    *,
    policy: HostResourcePolicy | None = None,
) -> tuple[float | None, bool]:
    """Return (burst_ceiling_gib, dedicated_policy_required).

    Shared hosting burst max is 12 GiB (not guaranteed / not reserved).
    VPS/VDS must not be silently capped to 12 GiB.
    """
    policy = policy or default_host_resource_policy()
    plan_class = classify_plan_resource_class(plan, policy=policy)
    if plan_class in {
        PlanResourceClass.VPS_STYLE,
        PlanResourceClass.VDS_STYLE,
        PlanResourceClass.CUSTOM,
    }:
        return _plan_ram_gb(plan) or None, True
    return float(policy.tenant_individual_burst_max_gb), False


def supports_shared_storage_pool(
    plan: PlanLike | PlanView,
    *,
    policy: HostResourcePolicy | None = None,
) -> StoragePoolSupport:
    policy = policy or default_host_resource_policy()
    plan_class = classify_plan_resource_class(plan, policy=policy)
    if plan_class in {
        PlanResourceClass.VPS_STYLE,
        PlanResourceClass.VDS_STYLE,
        PlanResourceClass.CUSTOM,
    }:
        return StoragePoolSupport.REQUIRES_DEDICATED_POLICY
    storage = _plan_storage_gb(plan)
    if storage > policy.tenant_storage_pool_gb:
        return StoragePoolSupport.REQUIRES_DEDICATED_POLICY
    return StoragePoolSupport.YES


def evaluate_plan_compatibility(
    plan: PlanLike | PlanView,
    *,
    policy: HostResourcePolicy | None = None,
) -> PlanCompatibility:
    policy = policy or default_host_resource_policy()
    plan_class = classify_plan_resource_class(plan, policy=policy)
    storage = _plan_storage_gb(plan)
    ram = _plan_ram_gb(plan)

    if storage < 0 or ram < 0:
        return PlanCompatibility.INVALID_RESOURCE_CONFIGURATION

    if plan_class in {
        PlanResourceClass.VPS_STYLE,
        PlanResourceClass.VDS_STYLE,
        PlanResourceClass.CUSTOM,
    }:
        return PlanCompatibility.DEDICATED_POLICY_REQUIRED

    if storage > policy.tenant_storage_pool_gb:
        return PlanCompatibility.DEDICATED_POLICY_REQUIRED

    return PlanCompatibility.COMPATIBLE_SHARED


def resolve_memory_entitlement(
    plan: PlanLike | PlanView,
    *,
    policy: HostResourcePolicy | None = None,
    actual_current_ram_usage_gb: float | None = None,
) -> MemoryEntitlement:
    policy = policy or default_host_resource_policy()
    plan_class = classify_plan_resource_class(plan, policy=policy)
    configured = _plan_ram_gb(plan)
    normal = resolve_normal_memory_target(plan, policy=policy)
    burst, dedicated = resolve_burst_memory_limit(plan, policy=policy)
    notes: list[str] = []
    if dedicated:
        notes.append("Dedicated/VPS-style memory policy required — not shared 2/6/12 targets.")
    else:
        notes.append(
            "configured_plan_ram is live DB metadata; normal_target/burst are Phase-1 policy only "
            "and must not be written to CustomerEnvironment yet."
        )
    return MemoryEntitlement(
        configured_plan_ram_gb=configured,
        normal_target_ram_gb=normal,
        burst_ceiling_ram_gb=burst,
        actual_current_ram_usage_gb=actual_current_ram_usage_gb,
        plan_class=plan_class,
        dedicated_policy_required=dedicated,
        notes=tuple(notes),
    )


def resolve_storage_entitlement(
    plan: PlanLike | PlanView,
    *,
    policy: HostResourcePolicy | None = None,
    actual_disk_usage_gb: float | None = None,
) -> StorageEntitlement:
    policy = policy or default_host_resource_policy()
    pool = supports_shared_storage_pool(plan, policy=policy)
    quota = _plan_storage_gb(plan)
    dedicated = pool != StoragePoolSupport.YES
    notes: list[str] = []
    if dedicated:
        notes.append(
            f"Plan storage_gb={quota} requires dedicated policy vs shared pool "
            f"{policy.tenant_storage_pool_gb} GB."
        )
    return StorageEntitlement(
        plan_storage_quota_gb=quota,
        aggregate_pool_allocation_gb=None if dedicated else quota,
        actual_disk_usage_gb=actual_disk_usage_gb,
        pool_support=pool,
        dedicated_policy_required=dedicated,
        notes=tuple(notes),
    )


def resolve_cpu_quota_percent(
    plan: PlanLike | PlanView | None,
    *,
    env_cpu_limit: float | None = None,
    default_percent: int = 25,
) -> int:
    """Central CPUQuota percent from plan/env — preserves existing entitlements.

    cpu_limit of 0.25 → 25%. Never invents new business entitlements.
    """
    if env_cpu_limit is not None and float(env_cpu_limit) > 0:
        return max(1, min(100, int(round(float(env_cpu_limit) * 100))))
    if plan is None:
        return int(default_percent)
    cores = getattr(plan, "cpu_cores", None)
    if cores is not None and float(cores) > 0:
        return max(1, min(100, int(round(float(cores) * 100))))
    return int(default_percent)


CPU_DRIFT_OK = "POLICY_OK"
CPU_DRIFT_MISSING = "MISSING_CPU_QUOTA"
CPU_DRIFT_LEGACY = "LEGACY_CPU_POLICY"
CPU_DRIFT_MISMATCH = "CPU_QUOTA_MISMATCH"


def detect_cpu_quota_drift(
    *,
    live_cpu_quota: str | None,
    expected_percent: int,
) -> str:
    raw = (live_cpu_quota or "").strip()
    if not raw or raw.lower() in {"infinity", ""}:
        return CPU_DRIFT_MISSING
    try:
        live = int(raw.rstrip("%").strip())
    except ValueError:
        return CPU_DRIFT_LEGACY
    if live != int(expected_percent):
        # Preserve legacy distinct values as LEGACY rather than auto-rewrite.
        if live in {20, 25, 40, 100}:
            return CPU_DRIFT_LEGACY
        return CPU_DRIFT_MISMATCH
    return CPU_DRIFT_OK


def resolve_environment_resource_policy(
    *,
    plan: PlanLike | PlanView,
    environment_id: str | None = None,
    domain_names: list[str] | tuple[str, ...] | None = None,
    policy: HostResourcePolicy | None = None,
    actual_current_ram_usage_gb: float | None = None,
    actual_disk_usage_gb: float | None = None,
) -> EnvironmentResourcePolicy:
    """Environment-scoped policy. Domain count never multiplies entitlements."""
    policy = policy or default_host_resource_policy()
    domains = list(domain_names or [])
    memory = resolve_memory_entitlement(
        plan, policy=policy, actual_current_ram_usage_gb=actual_current_ram_usage_gb
    )
    storage = resolve_storage_entitlement(
        plan, policy=policy, actual_disk_usage_gb=actual_disk_usage_gb
    )
    notes = (
        "Resources belong to CustomerEnvironment / hosting account, not domain names.",
        f"domain_count={len(domains)} does not multiply RAM or storage entitlements.",
    )
    return EnvironmentResourcePolicy(
        environment_id=environment_id,
        plan_slug=_slug(plan),
        plan_class=memory.plan_class,
        compatibility=evaluate_plan_compatibility(plan, policy=policy),
        memory=memory,
        storage=storage,
        domain_count=len(domains),
        notes=notes,
    )


def known_workload_units() -> tuple[WorkloadUnit, ...]:
    return _PLATFORM_CORE_UNITS + _FIRST_PARTY_UNITS + _SYSTEM_INFRA_UNITS + _ISOLATION_VIOLATION_UNITS


def classify_workload_unit(key_or_unit: str) -> WorkloadUnit | None:
    needle = (key_or_unit or "").strip().lower()
    for unit in known_workload_units():
        if unit.key == needle or needle in {u.lower() for u in unit.systemd_units}:
            return unit
        if needle in unit.display_name.lower().replace(" ", ""):
            return unit
    return None


def isolation_blockers() -> tuple[IsolationBlocker, ...]:
    """Phase 2 prerequisites — documented, not repaired in Phase 1."""
    return (
        IsolationBlocker(
            code="RESOURCE_ISOLATION_VIOLATION",
            title="examflow-ifnotus.service",
            severity=IsolationSeverity.BLOCKER,
            detail=(
                "Runs as root from a tenant public_html tree outside tenant resource accounting. "
                "Tenant isolation cannot be considered complete until this is fixed."
            ),
            phase_required="2",
        ),
        IsolationBlocker(
            code="PHP_WORKER_ATTRIBUTION",
            title="Tenant PHP worker attribution",
            severity=IsolationSeverity.BLOCKER,
            detail=(
                "PHP-FPM master is SYSTEM_INFRASTRUCTURE; tenant workers are not yet inside "
                "per-environment slices (requires_tenant_worker_assignment)."
            ),
            phase_required="2",
        ),
        IsolationBlocker(
            code="NODE_WORKER_ATTRIBUTION",
            title="Tenant Node / long-running process attribution",
            severity=IsolationSeverity.BLOCKER,
            detail="Supervisor/long-lived tenant processes are not reliably inside env slices.",
            phase_required="2",
        ),
        IsolationBlocker(
            code="SLICE_HIERARCHY",
            title="Missing ifnotus-core / ifnotus-tenants parent slices",
            severity=IsolationSeverity.BLOCKER,
            detail=(
                "ifnotus.slice exists but is mostly empty; no 30 GiB tenant parent pool or "
                "coordinated 9 GiB emergency governor."
            ),
            phase_required="2",
        ),
        IsolationBlocker(
            code="CRON_ACCOUNTING",
            title="Cron resource accounting",
            severity=IsolationSeverity.WARNING,
            detail="Verify env cron joins tenant slices; product crons must not pollute tenant pool.",
            phase_required="2",
        ),
        IsolationBlocker(
            code="SHARED_INFRA_SPLIT",
            title="Shared infrastructure accounting",
            severity=IsolationSeverity.WARNING,
            detail="Nginx/Redis/PostgreSQL must not be billed as PLATFORM_CORE application RAM.",
            phase_required="2",
        ),
    )


def resource_policy_status_report(
    *,
    policy: HostResourcePolicy | None = None,
    plans: list[PlanLike | PlanView] | None = None,
) -> dict[str, Any]:
    """Internal snapshot for CLI / staff tooling — not a customer API."""
    policy = policy or default_host_resource_policy()
    validation = validate_resource_policy(policy)
    plan_rows: list[dict[str, Any]] = []
    for plan in plans or []:
        plan_class = classify_plan_resource_class(plan, policy=policy)
        plan_rows.append(
            {
                "slug": _slug(plan),
                "name": getattr(plan, "name", _slug(plan)),
                "price_monthly_ghs": _price_ghs(plan),
                "configured_plan_ram_gb": _plan_ram_gb(plan),
                "configured_plan_storage_gb": _plan_storage_gb(plan),
                "plan_class": plan_class.value,
                "compatibility": evaluate_plan_compatibility(plan, policy=policy).value,
                "normal_target_ram_gb": resolve_normal_memory_target(plan, policy=policy),
                "burst_ceiling_ram_gb": resolve_burst_memory_limit(plan, policy=policy)[0],
                "storage_pool_support": supports_shared_storage_pool(plan, policy=policy).value,
            }
        )

    return {
        "policy": policy.snapshot(),
        "validation": {
            "ok": validation.ok,
            "errors": [asdict(e) for e in validation.errors],
            "warnings": [asdict(w) for w in validation.warnings],
        },
        "workloads": {
            "platform_core": [asdict(u) for u in _PLATFORM_CORE_UNITS],
            "first_party": [asdict(u) for u in _FIRST_PARTY_UNITS],
            "system_infrastructure": [asdict(u) for u in _SYSTEM_INFRA_UNITS],
            "isolation_violations": [asdict(u) for u in _ISOLATION_VIOLATION_UNITS],
        },
        "isolation_blockers": [asdict(b) for b in isolation_blockers()],
        "plan_compatibility": plan_rows,
        "phase_2_blockers": [b.code for b in isolation_blockers() if b.severity == IsolationSeverity.BLOCKER],
        "notes": [
            "Phase 1 policy only — no systemd/cgroup/quota enforcement.",
            "Live HostingPlan.ram_gb values must not be mutated by this module.",
            "Emergency 9 GiB is a single shared reserve — core and tenants must not each assume ownership.",
        ],
    }


def format_resource_policy_status(report: dict[str, Any]) -> str:
    pol = report["policy"]
    lines = [
        "Host Policy:",
        f"  RAM: {pol['host_ram_gb']} GB",
        f"  OS reserve: {pol['os_reserve_gb']} GB",
        f"  Core normal: {pol['core_normal_gb']} GB",
        f"  Tenant normal pool: {pol['tenant_normal_pool_gb']} GB",
        f"  Emergency reserve: {pol['emergency_pool_gb']} GB",
        "",
        "Shared hosting:",
        f"  Low normal: {pol['shared_low_normal_gb']} GB",
        f"  Standard normal: {pol['shared_standard_normal_gb']} GB",
        f"  Burst max: {pol['shared_burst_max_gb']} GB",
        "",
        "Storage:",
        f"  Core reserve: {pol['core_storage_reserve_gb']} GB",
        f"  Shared tenant pool: {pol['tenant_storage_pool_gb']} GB",
        "",
        "Plan Compatibility:",
    ]
    for row in report.get("plan_compatibility") or []:
        lines.append(
            f"  - {row['slug']}: {row['compatibility']} "
            f"(class={row['plan_class']}, configured_ram={row['configured_plan_ram_gb']} GB, "
            f"target={row['normal_target_ram_gb']} GiB)"
        )
    if not report.get("plan_compatibility"):
        lines.append("  (no plans provided)")
    lines.append("")
    lines.append("Isolation blockers:")
    for b in report.get("isolation_blockers") or []:
        lines.append(f"  - [{b['severity']}] {b['title']}: {b['detail']}")
    val = report.get("validation") or {}
    lines.append("")
    lines.append(f"Validation: {'OK' if val.get('ok') else 'FAILED'}")
    for err in val.get("errors") or []:
        lines.append(f"  ERROR: {err['message']}")
    for warn in val.get("warnings") or []:
        lines.append(f"  WARN: {warn['message']}")
    return "\n".join(lines)
