"""Phase 2B-3 — controlled shared PHP-FPM mass rollout orchestration.

Builds on PhpFpmEnvironmentService. Does NOT change MemoryMax/CPUQuota/TasksMax
or customer filesystem ownership.
"""

from __future__ import annotations

import json
import re
import statistics
import subprocess
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable
from uuid import UUID

from app.core.logging import get_logger
from app.services.platform.php_fpm_environment import (
    DISABLED_SUFFIX,
    GLOBAL_POOL_DIR,
    PhpFpmEnvironmentService,
    STATE_MIGRATED_HEALTHY,
    diagnose_migration_state,
    estimate_tasksmax_risk,
    fpm_pool_name,
    is_excluded_canary_domain,
)
from app.services.platform.resource_policy import (
    PlanResourceClass,
    VDS_STYLE_SLUGS,
    VPS_STYLE_SLUGS,
    classify_plan_resource_class,
    default_host_resource_policy,
)
from app.services.platform.workload_slices import (
    env_short_id,
    read_cgroup_memory_current,
    resolve_slice_cgroup_path,
    slice_name_for,
)

logger = get_logger(__name__)

CHECKPOINT_PATH = Path("/var/lib/ifnotus/php-fpm-rollout-state.json")

CLASS_ALREADY_MIGRATED = "ALREADY_MIGRATED"
CLASS_ELIGIBLE = "ELIGIBLE_SHARED_PHP"
CLASS_NO_PHP = "NO_PHP"
CLASS_SUSPENDED = "SUSPENDED"
CLASS_VPS = "VPS_STYLE"
CLASS_VDS = "VDS_STYLE"
CLASS_FIRST_PARTY = "FIRST_PARTY"
CLASS_SPECIAL = "SPECIAL_APPLICATION"
CLASS_POOL_MISMATCH = "POOL_IDENTITY_MISMATCH"
CLASS_UNHEALTHY = "UNHEALTHY"
CLASS_MANUAL = "REQUIRES_MANUAL_REVIEW"

IDENTITY_SAFE_IFN = "SAFE_IFN_USER"
IDENTITY_LEGACY_WWW = "LEGACY_WWW_DATA"
IDENTITY_ROOT = "ROOT"
IDENTITY_CROSS = "CROSS_TENANT"
IDENTITY_UNKNOWN = "UNKNOWN"

ROLL_NOT_STARTED = "NOT_STARTED"
ROLL_PREFLIGHT_FAILED = "PREFLIGHT_FAILED"
ROLL_MIGRATING = "MIGRATING"
ROLL_MIGRATED = "MIGRATED"
ROLL_VERIFIED = "VERIFIED"
ROLL_ROLLED_BACK = "ROLLED_BACK"
ROLL_MANUAL_REVIEW = "MANUAL_REVIEW"

FIRST_PARTY_DOMAINS = frozenset(
    {
        "votebridge.online",
        "quizsnap.online",
        "examflow.ifnotus.space",
        "ifnotus.space",
        "www.ifnotus.space",
    }
)
SPECIAL_DOMAIN_MARKERS = frozenset({"adastrachambers", "csdttu"})


@dataclass
class EnvInventoryRow:
    environment_id: str
    short_id: str
    domain: str | None
    status: str
    unix_username: str | None
    plan_slug: str | None
    plan_name: str | None
    price_monthly: float | None
    plan_class: str | None
    classification: str
    pool_count: int = 0
    hostname_count: int = 0
    pool_users: list[str] = field(default_factory=list)
    identity_codes: list[str] = field(default_factory=list)
    reject_codes: list[str] = field(default_factory=list)
    http_status: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def classify_pool_identity(*, expected_unix: str | None, pool_user: str | None) -> str:
    """Classify a single pool's Unix identity relative to the environment."""
    expected = (expected_unix or "").strip()
    user = (pool_user or "").strip()
    if not user:
        return IDENTITY_UNKNOWN
    if user == "root":
        return IDENTITY_ROOT
    if user == "www-data":
        return IDENTITY_LEGACY_WWW
    if expected and user == expected:
        return IDENTITY_SAFE_IFN
    if user.startswith("ifn_") and expected and user != expected:
        return IDENTITY_CROSS
    if user.startswith("ifn_") and not expected:
        return IDENTITY_UNKNOWN
    return IDENTITY_UNKNOWN


def tasksmax_warning(*, tasks_max: int, theoretical_peak: int, tasks_current: int | None = None) -> str | None:
    headroom_abs = tasks_max - theoretical_peak
    headroom_pct = (headroom_abs / tasks_max) if tasks_max > 0 else 0.0
    if headroom_abs < 4 or headroom_pct < 0.25:
        return "TASKSMAX_WARNING"
    if tasks_current is not None and tasks_max > 0 and (tasks_max - tasks_current) < 4:
        return "TASKSMAX_WARNING"
    return None


def recommended_tasksmax(*, pm_max_children: int, has_node: bool = False) -> int:
    base = 1 + pm_max_children + 2 + 2 + (4 if has_node else 0)
    # Keep ≥25% spare and at least +8 absolute slots.
    return max(base + 8, int(base / 0.75) + 1)


class PhpFpmRolloutCheckpoint:
    """JSON checkpoint under /var/lib/ifnotus (not customer trees)."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or CHECKPOINT_PATH

    def load(self) -> dict[str, Any]:
        if not self.path.is_file():
            return {
                "version": 1,
                "updated_at": None,
                "batch": 0,
                "environments": {},
                "batches": [],
                "stopped": False,
                "stop_reason": None,
            }
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {
                "version": 1,
                "updated_at": None,
                "batch": 0,
                "environments": {},
                "batches": [],
                "stopped": False,
                "stop_reason": None,
                "corrupt": True,
            }

    def save(self, state: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        state["updated_at"] = datetime.now(timezone.utc).isoformat()
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(state, indent=2, sort_keys=True), encoding="utf-8")
        tmp.replace(self.path)

    def set_env(self, state: dict[str, Any], env_id: str, **fields: Any) -> dict[str, Any]:
        envs = state.setdefault("environments", {})
        row = dict(envs.get(env_id) or {"environment_id": env_id, "status": ROLL_NOT_STARTED})
        row.update(fields)
        envs[env_id] = row
        return state


class PhpFpmRolloutService:
    """Inventory + sequential batch migration for ordinary shared PHP envs."""

    def __init__(
        self,
        *,
        fpm: PhpFpmEnvironmentService | None = None,
        checkpoint: PhpFpmRolloutCheckpoint | None = None,
        pool_dir: Path | None = None,
    ) -> None:
        self.fpm = fpm or PhpFpmEnvironmentService()
        self.checkpoint = checkpoint or PhpFpmRolloutCheckpoint()
        self.pool_dir = pool_dir or GLOBAL_POOL_DIR

    def _systemctl(self, *args: str) -> subprocess.CompletedProcess[str]:
        try:
            return subprocess.run(
                ["systemctl", *args],
                capture_output=True,
                text=True,
                check=False,
                timeout=60,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            return subprocess.CompletedProcess(args=["systemctl", *args], returncode=1, stdout="", stderr=str(exc))

    def host_memory_snapshot(self) -> dict[str, Any]:
        mem: dict[str, Any] = {}
        try:
            for line in Path("/proc/meminfo").read_text(encoding="utf-8").splitlines():
                if line.startswith(("MemTotal:", "MemAvailable:", "SwapTotal:", "SwapFree:")):
                    key, raw, *_ = line.replace(":", "").split()
                    mem[key] = int(raw)  # kB
        except OSError:
            pass
        swap_used = None
        if "SwapTotal" in mem and "SwapFree" in mem:
            swap_used = mem["SwapTotal"] - mem["SwapFree"]
        out = {
            "mem_total_gb": round(mem.get("MemTotal", 0) / (1024 * 1024), 2),
            "mem_available_gb": round(mem.get("MemAvailable", 0) / (1024 * 1024), 2),
            "swap_used_mb": round((swap_used or 0) / 1024, 1),
        }
        for label, unit in (
            ("tenants", "ifnotus-workloads-tenants.slice"),
            ("priority", "ifnotus-workloads-priority.slice"),
            ("core", "ifnotus-workloads-priority-core.slice"),
            ("products", "ifnotus-workloads-priority-products.slice"),
        ):
            cg = resolve_slice_cgroup_path(unit)
            cur = read_cgroup_memory_current(cg) if cg else None
            out[f"{label}_memory_current_gb"] = round((cur or 0) / (1024**3), 3) if cur is not None else None
        return out

    def service_health(self) -> dict[str, str]:
        mapping = {
            "nginx": "nginx.service",
            "global_fpm": "php8.3-fpm.service",
            "ifnotus_api": "ifnotus-api.service",
            "ifnotus_worker": "ifnotus-worker.service",
            "postgresql": "postgresql.service",
            "redis": "redis-server.service",
        }
        out: dict[str, str] = {}
        for key, unit in mapping.items():
            proc = self._systemctl("is-active", unit)
            val = (proc.stdout or "").strip() or "unknown"
            if val != "active" and key == "redis":
                alt = self._systemctl("is-active", "redis.service")
                val = (alt.stdout or "").strip() or val
            if val != "active" and key == "postgresql":
                # debian often uses postgresql@*-main
                listed = subprocess.run(
                    ["systemctl", "list-units", "postgresql*", "--no-legend", "--state=active"],
                    capture_output=True,
                    text=True,
                    check=False,
                )
                if listed.stdout and "postgresql" in listed.stdout:
                    val = "active"
            out[key] = val
        return out

    def http_status(self, host: str) -> str:
        if not host:
            return "none"
        proc = subprocess.run(
            [
                "curl",
                "-sk",
                "-o",
                "/dev/null",
                "-w",
                "%{http_code}",
                "--max-time",
                "15",
                "--resolve",
                f"{host}:443:127.0.0.1",
                f"https://{host}/",
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        return (proc.stdout or "000").strip() or "000"

    def classify_environment(
        self,
        env,
        *,
        extra_hostnames: Iterable[str] | None = None,
        plan=None,
        plan_slug: str | None = None,
        plan_name: str | None = None,
        price_monthly: float | None = None,
        check_http: bool = False,
    ) -> EnvInventoryRow:
        short = env_short_id(env.id)
        domain = getattr(env, "domain", None)
        status = str(getattr(env, "status", "") or "")
        unix = (getattr(env, "unix_username", None) or "").strip() or None
        slug = (plan_slug or getattr(plan, "slug", None) or "").strip().lower() or None
        plan_class = None
        if plan is not None:
            try:
                plan_class = classify_plan_resource_class(plan, policy=default_host_resource_policy()).value
            except Exception:  # noqa: BLE001
                plan_class = None

        active = (self._systemctl("is-active", f"ifnotus-php-fpm@{short}.service").stdout or "").strip() == "active"
        pools = self.fpm.resolve_pools_for_environment(env, extra_hostnames=extra_hostnames)
        hosts = self.fpm.discover_hostnames(env, extra_hostnames)
        pool_users = [p.user for p in pools]
        identities = [classify_pool_identity(expected_unix=unix, pool_user=u) for u in pool_users]
        reject: list[str] = []
        d = (domain or "").lower()

        if active:
            classification = CLASS_ALREADY_MIGRATED
        elif status != "active":
            classification = CLASS_SUSPENDED
        elif d in FIRST_PARTY_DOMAINS or any(x in d for x in ("votebridge", "quizsnap", "examflow")):
            classification = CLASS_FIRST_PARTY
            reject.append("FIRST_PARTY")
        elif any(m in d for m in SPECIAL_DOMAIN_MARKERS) or is_excluded_canary_domain(domain):
            classification = CLASS_SPECIAL
            reject.append("SPECIAL_APPLICATION")
        elif slug in VPS_STYLE_SLUGS or (slug and "vps" in slug) or plan_class == PlanResourceClass.VPS_STYLE.value:
            classification = CLASS_VPS
            reject.append("VPS_STYLE")
        elif slug in VDS_STYLE_SLUGS or (slug and "vds" in slug) or plan_class == PlanResourceClass.VDS_STYLE.value:
            classification = CLASS_VDS
            reject.append("VDS_STYLE")
        elif not pools:
            classification = CLASS_NO_PHP
        elif not unix or not unix.startswith("ifn_"):
            classification = CLASS_MANUAL
            reject.append("INVALID_ENV_IDENTITY")
        elif IDENTITY_ROOT in identities:
            classification = CLASS_POOL_MISMATCH
            reject.append("ROOT_PHP_POOL")
        elif IDENTITY_CROSS in identities:
            classification = CLASS_POOL_MISMATCH
            reject.append("CROSS_TENANT_POOL_IDENTITY")
        elif IDENTITY_LEGACY_WWW in identities:
            classification = CLASS_POOL_MISMATCH
            reject.append("LEGACY_SHARED_USER")
            reject.append("POOL_IDENTITY_MISMATCH")
        elif IDENTITY_UNKNOWN in identities or not all(i == IDENTITY_SAFE_IFN for i in identities):
            classification = CLASS_POOL_MISMATCH
            reject.append("POOL_IDENTITY_MISMATCH")
        else:
            classification = CLASS_ELIGIBLE

        http = None
        if check_http and domain and classification in {CLASS_ELIGIBLE, CLASS_ALREADY_MIGRATED}:
            http = self.http_status(domain)
            if classification == CLASS_ELIGIBLE and http in {"000", "502", "503", "504"}:
                classification = CLASS_UNHEALTHY
                reject.append("BROKEN_EXISTING_SITE")

        # Ambiguous partial migration without active unit
        if classification == CLASS_ELIGIBLE:
            global_active = [p.pool_name for p in pools if (self.pool_dir / f"{p.pool_name}.conf").is_file()]
            global_disabled = [
                p.pool_name for p in pools if (self.pool_dir / f"{p.pool_name}.conf{DISABLED_SUFFIX}").is_file()
            ]
            drift = diagnose_migration_state(
                env_unit_active=False,
                global_pools_active=global_active,
                global_pools_disabled=global_disabled,
                sockets_exist=[True] * len(pools),
                socket_conflicts=[],
                duplicate_pool_names=[],
            )
            if drift not in {"GLOBAL_LEGACY"} and global_disabled:
                classification = CLASS_MANUAL
                reject.append("PARTIAL_MIGRATION")

        return EnvInventoryRow(
            environment_id=str(env.id),
            short_id=short,
            domain=domain,
            status=status,
            unix_username=unix,
            plan_slug=slug,
            plan_name=plan_name or getattr(plan, "name", None),
            price_monthly=price_monthly,
            plan_class=plan_class,
            classification=classification,
            pool_count=len(pools),
            hostname_count=len(hosts),
            pool_users=pool_users,
            identity_codes=identities,
            reject_codes=reject,
            http_status=http,
        )

    def preflight(self, env, *, extra_hostnames: Iterable[str] | None = None, plan_class: str | None = None) -> dict[str, Any]:
        """Strict preflight for automatic rollout (rejects www-data)."""
        row = self.classify_environment(env, extra_hostnames=extra_hostnames, check_http=True)
        plan = self.fpm.plan_migrate(
            env,
            extra_hostnames=extra_hostnames,
            plan_class=plan_class,
            require_tenant_unix_user=True,
        )
        out: dict[str, Any] = {
            "ok": False,
            "inventory": row.to_dict(),
            "plan_errors": list(plan.errors),
            "reject_codes": list(row.reject_codes),
        }
        if row.classification != CLASS_ELIGIBLE:
            out["reject_codes"].append(row.classification)
            return out
        if plan.errors:
            out["reject_codes"].extend(plan.errors)
            return out
        # Slice limits (read-only)
        show = self._systemctl("show", slice_name_for(env.id), "-p", "MemoryMax", "-p", "CPUQuota", "-p", "TasksMax")
        limits: dict[str, str] = {}
        for line in (show.stdout or "").splitlines():
            if "=" in line:
                k, v = line.split("=", 1)
                limits[k] = v
        out["limits"] = limits
        out["ok"] = True
        out["migrate_plan"] = {
            "service_name": plan.service_name,
            "pools": [p.pool_name for p in plan.pools],
            "sockets": [p.listen for p in plan.pools],
        }
        return out

    def verify_migrated(self, env, *, extra_hostnames: Iterable[str] | None = None) -> dict[str, Any]:
        status = self.fpm.status(env, extra_hostnames=extra_hostnames)
        drift = status.get("drift_state")
        hosts = status.get("hostnames") or []
        http: dict[str, str] = {}
        for h in hosts:
            http[h] = self.http_status(h)
        cg = resolve_slice_cgroup_path(slice_name_for(env.id))
        mem = read_cgroup_memory_current(cg) if cg else None
        from app.services.platform.systemd_env_slice import EnvironmentSliceService

        usage = EnvironmentSliceService().read_usage(env)
        bad_http = [h for h, c in http.items() if c in {"502", "503", "504", "000"}]
        ok = (
            drift == STATE_MIGRATED_HEALTHY
            and (status.get("env_master") or {}).get("active") == "active"
            and not bad_http
            and usage.get("cgroup_path")
            and "tenants-env-" in str(usage.get("cgroup_path") or "")
            and not status.get("global_pools_active")
        )
        risk = status.get("tasksmax_risk") or {}
        warn = tasksmax_warning(
            tasks_max=int(risk.get("tasks_max") or 0),
            theoretical_peak=int(risk.get("theoretical_peak") or 0),
            tasks_current=usage.get("process_count"),
        )
        return {
            "ok": ok,
            "drift_state": drift,
            "http": http,
            "memory_current_mb": round((mem or 0) / (1024 * 1024), 1) if mem is not None else None,
            "read_usage_mb": usage.get("memory_current_mb"),
            "cgroup_path": usage.get("cgroup_path"),
            "tasksmax_warning": warn,
            "tasksmax_risk": risk,
            "status": status,
        }

    def migrate_one(
        self,
        env,
        *,
        extra_hostnames: Iterable[str] | None = None,
        plan_class: str | None = None,
        dry_run: bool = True,
        state: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        eid = str(env.id)
        state = state if state is not None else self.checkpoint.load()
        pre = self.preflight(env, extra_hostnames=extra_hostnames, plan_class=plan_class)
        if not pre["ok"]:
            self.checkpoint.set_env(
                state,
                eid,
                status=ROLL_PREFLIGHT_FAILED,
                short_id=env_short_id(env.id),
                reject_codes=pre.get("reject_codes"),
            )
            self.checkpoint.save(state)
            return {"ok": False, "phase": "preflight", "preflight": pre, "state": state}

        plan = self.fpm.plan_migrate(
            env,
            extra_hostnames=extra_hostnames,
            plan_class=plan_class,
            require_tenant_unix_user=True,
        )
        if dry_run:
            report = self.fpm.apply_migrate(plan, dry_run=True)
            return {"ok": True, "phase": "dry_run", "preflight": pre, "report": report, "state": state}

        self.checkpoint.set_env(state, eid, status=ROLL_MIGRATING, short_id=env_short_id(env.id))
        self.checkpoint.save(state)
        report = self.fpm.apply_migrate(plan, dry_run=False)
        if not report.get("ok"):
            rb = report.get("rollback") or self.fpm.rollback(plan)
            http = {h: self.http_status(h) for h in self.fpm.discover_hostnames(env, extra_hostnames)}
            restored = all(c not in {"502", "503", "504", "000"} for c in http.values()) if http else True
            self.checkpoint.set_env(
                state,
                eid,
                status=ROLL_ROLLED_BACK,
                rollback=rb,
                http=http,
                restored=restored,
            )
            state["stopped"] = True
            state["stop_reason"] = f"migration_failed:{env_short_id(env.id)}"
            self.checkpoint.save(state)
            return {
                "ok": False,
                "phase": "rolled_back",
                "report": report,
                "rollback": rb,
                "http": http,
                "restored": restored,
                "state": state,
            }

        time.sleep(0.5)
        verify = self.verify_migrated(env, extra_hostnames=extra_hostnames)
        if not verify["ok"]:
            rb = self.fpm.rollback(plan)
            http = verify.get("http") or {}
            restored = all(c not in {"502", "503", "504", "000"} for c in http.values()) if http else False
            self.checkpoint.set_env(
                state,
                eid,
                status=ROLL_ROLLED_BACK,
                verify=verify,
                rollback=rb,
                restored=restored,
            )
            state["stopped"] = True
            state["stop_reason"] = f"verify_failed:{env_short_id(env.id)}"
            self.checkpoint.save(state)
            return {
                "ok": False,
                "phase": "verify_failed_rolled_back",
                "verify": verify,
                "rollback": rb,
                "restored": restored,
                "state": state,
            }

        self.checkpoint.set_env(
            state,
            eid,
            status=ROLL_VERIFIED,
            verify={
                "drift_state": verify.get("drift_state"),
                "memory_current_mb": verify.get("memory_current_mb"),
                "http": verify.get("http"),
                "tasksmax_warning": verify.get("tasksmax_warning"),
            },
        )
        self.checkpoint.save(state)
        return {"ok": True, "phase": "verified", "verify": verify, "report": report, "state": state}

    def select_batch(
        self,
        eligible: list[EnvInventoryRow],
        *,
        batch_size: int,
        exclude: set[str] | None = None,
        only: set[str] | None = None,
        state: dict[str, Any] | None = None,
    ) -> list[EnvInventoryRow]:
        exclude = exclude or set()
        state = state or self.checkpoint.load()
        done = {
            eid
            for eid, row in (state.get("environments") or {}).items()
            if row.get("status")
            in {ROLL_VERIFIED, ROLL_MIGRATED, ROLL_MANUAL_REVIEW, ROLL_PREFLIGHT_FAILED, ROLL_ROLLED_BACK}
        }
        out: list[EnvInventoryRow] = []
        # Prefer fewer hostnames / lower price as lower risk
        ordered = sorted(
            eligible,
            key=lambda r: (r.hostname_count, r.pool_count, r.price_monthly or 9999, r.short_id),
        )
        for row in ordered:
            if row.environment_id in done or row.short_id in exclude or row.environment_id in exclude:
                continue
            if only and row.environment_id not in only and row.short_id not in only:
                continue
            out.append(row)
            if len(out) >= batch_size:
                break
        return out

    def pool_identity_summary(self, rows: list[EnvInventoryRow]) -> dict[str, int]:
        counts = {
            "safe_ifn_user": 0,
            "legacy_www_data": 0,
            "root": 0,
            "cross_tenant": 0,
            "unknown": 0,
        }
        for row in rows:
            for code in row.identity_codes or [IDENTITY_UNKNOWN]:
                if code == IDENTITY_SAFE_IFN:
                    counts["safe_ifn_user"] += 1
                elif code == IDENTITY_LEGACY_WWW:
                    counts["legacy_www_data"] += 1
                elif code == IDENTITY_ROOT:
                    counts["root"] += 1
                elif code == IDENTITY_CROSS:
                    counts["cross_tenant"] += 1
                else:
                    counts["unknown"] += 1
            if not row.identity_codes and row.pool_count == 0:
                pass
        return counts


def idle_fpm_stats(values_mb: list[float]) -> dict[str, float]:
    if not values_mb:
        return {"min": 0, "median": 0, "mean": 0, "p95": 0, "max": 0}
    ordered = sorted(values_mb)
    n = len(ordered)
    p95_idx = min(n - 1, max(0, int(round(0.95 * (n - 1)))))
    return {
        "min": round(ordered[0], 1),
        "median": round(statistics.median(ordered), 1),
        "mean": round(statistics.fmean(ordered), 1),
        "p95": round(ordered[p95_idx], 1),
        "max": round(ordered[-1], 1),
    }
