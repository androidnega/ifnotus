"""Phase 2B — per-environment PHP-FPM masters (canary + reusable migrate).

Groups hostname pools by CustomerEnvironment, generates an isolated FPM master
under ``/etc/php/8.3/ifnotus-envs/<shortid>/``, and runs:

  ifnotus-php-fpm@<shortid>.service
  → Slice=ifnotus-workloads-tenants-env-<shortid>.slice

Does NOT change tenant MemoryMax/CPUQuota/TasksMax or customer files.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterable
from uuid import UUID

from app.core.logging import get_logger
from app.services.platform.php_fpm_env_design import (
    HostnamePool,
    planned_fpm_service_name,
)
from app.services.platform.workload_slices import env_short_id, slice_name_for

logger = get_logger(__name__)

# Migration health states for drift detection.
STATE_MIGRATED_HEALTHY = "MIGRATED_HEALTHY"
STATE_GLOBAL_LEGACY = "GLOBAL_LEGACY"
STATE_PARTIAL_MIGRATION = "PARTIAL_MIGRATION"
STATE_SOCKET_CONFLICT = "SOCKET_CONFLICT"
STATE_DUPLICATE_POOL = "DUPLICATE_POOL"
STATE_BROKEN_ENV_FPM = "BROKEN_ENV_FPM"
STATE_STALE_DISABLED = "STALE_DISABLED"
DRIFT_STATES = (
    STATE_MIGRATED_HEALTHY,
    STATE_GLOBAL_LEGACY,
    STATE_PARTIAL_MIGRATION,
    STATE_SOCKET_CONFLICT,
    STATE_DUPLICATE_POOL,
    STATE_BROKEN_ENV_FPM,
    STATE_STALE_DISABLED,
)

PHP_VERSION = "8.3"
PHP_FPM_BIN = Path("/usr/sbin/php-fpm8.3")
GLOBAL_POOL_DIR = Path(f"/etc/php/{PHP_VERSION}/fpm/pool.d")
ENV_CONFIG_ROOT = Path(f"/etc/php/{PHP_VERSION}/ifnotus-envs")
SYSTEMD_DIR = Path("/etc/systemd/system")
BACKUP_ROOT = Path("/var/backups/ifnotus/php-fpm-env")
DISABLED_SUFFIX = ".ifnotus-disabled"
TEMPLATE_UNIT = "ifnotus-php-fpm@.service"

_POOL_NAME_RE = re.compile(r"[^a-z0-9]+")

CANARY_EXCLUDE_EXACT = frozenset(
    {
        "ifnotus.space",
        "www.ifnotus.space",
        "fpanel.ifnotus.space",
        "mail.ifnotus.space",
        "api.ifnotus.space",
        "votebridge.online",
        "quizsnap.online",
        "examflow.ifnotus.space",
    }
)


def fpm_pool_name(hostname: str) -> str:
    safe = _POOL_NAME_RE.sub("-", hostname.lower()).strip("-")[:40] or "site"
    return f"ifnotus-{safe}"


def fpm_socket_for(hostname: str) -> Path:
    return Path(f"/run/php/{fpm_pool_name(hostname)}.sock")


def estimate_tasksmax_risk(
    *,
    tasks_max: int,
    pm_max_children: int,
    has_node_runtime: bool = False,
    cron_slots: int = 2,
    other_processes: int = 2,
) -> dict[str, Any]:
    """Estimate TasksMax headroom for an env with a dedicated FPM master."""
    fpm_master = 1
    theoretical = fpm_master + pm_max_children + cron_slots + other_processes
    if has_node_runtime:
        theoretical += 4
    headroom = tasks_max - theoretical
    risk = headroom < 4
    return {
        "tasks_max": tasks_max,
        "pm_max_children": pm_max_children,
        "theoretical_peak": theoretical,
        "headroom": headroom,
        "code": "TASKSMAX_RISK" if risk else None,
        "risk": risk,
    }


def diagnose_migration_state(
    *,
    env_unit_active: bool,
    global_pools_active: list[str],
    global_pools_disabled: list[str],
    sockets_exist: list[bool],
    socket_conflicts: list[str],
    duplicate_pool_names: list[str],
) -> str:
    """Classify migration drift for one environment."""
    if socket_conflicts:
        return STATE_SOCKET_CONFLICT
    if duplicate_pool_names:
        return STATE_DUPLICATE_POOL
    if env_unit_active and global_pools_active and global_pools_disabled:
        return STATE_PARTIAL_MIGRATION
    if env_unit_active and global_pools_active and not global_pools_disabled:
        return STATE_DUPLICATE_POOL
    if env_unit_active and global_pools_disabled and not global_pools_active:
        if sockets_exist and not all(sockets_exist):
            return STATE_BROKEN_ENV_FPM
        return STATE_MIGRATED_HEALTHY
    if (not env_unit_active) and global_pools_active and not global_pools_disabled:
        return STATE_GLOBAL_LEGACY
    if (not env_unit_active) and global_pools_disabled and not global_pools_active:
        return STATE_STALE_DISABLED
    if env_unit_active and not global_pools_disabled and not global_pools_active:
        return STATE_BROKEN_ENV_FPM
    if not env_unit_active:
        return STATE_GLOBAL_LEGACY
    return STATE_PARTIAL_MIGRATION


def is_excluded_canary_domain(domain: str | None) -> bool:
    d = (domain or "").lower()
    if d in CANARY_EXCLUDE_EXACT:
        return True
    for part in ("votebridge", "quizsnap", "examflow", "adastrachambers", "csdttu"):
        if part in d:
            return True
    return False


@dataclass
class EnvPoolRef:
    hostname: str
    pool_name: str
    global_conf: Path
    listen: str
    user: str
    group: str
    body: str


@dataclass
class MigratePlan:
    environment_id: str
    short_id: str
    slice_name: str
    service_name: str
    config_root: str
    pools: list[EnvPoolRef] = field(default_factory=list)
    actions: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    rollback_steps: list[str] = field(default_factory=list)
    nginx_changes: list[dict[str, str]] = field(default_factory=list)
    memorymax_changed: bool = False
    cpuquota_changed: bool = False
    tasksmax_changed: bool = False

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["pools"] = [
            {
                "hostname": p.hostname,
                "pool_name": p.pool_name,
                "global_conf": str(p.global_conf),
                "listen": p.listen,
                "user": p.user,
                "group": p.group,
            }
            for p in self.pools
        ]
        return d


def _pool_listen(body: str) -> str | None:
    m = re.search(r"^listen\s*=\s*(.+)$", body, re.M)
    return m.group(1).strip() if m else None


def _pool_user(body: str) -> str:
    m = re.search(r"^user\s*=\s*(.+)$", body, re.M)
    return m.group(1).strip() if m else "www-data"


def _pool_group(body: str) -> str:
    m = re.search(r"^group\s*=\s*(.+)$", body, re.M)
    return m.group(1).strip() if m else _pool_user(body)


def render_env_master_conf(*, short_id: str, pool_glob: str) -> str:
    return "\n".join(
        [
            "; IFNOTUS per-environment PHP-FPM master — managed",
            f"; environment_short_id={short_id}",
            "[global]",
            f"pid = /run/php/ifnotus/{short_id}/php-fpm.pid",
            f"error_log = /var/log/php/ifnotus/{short_id}/master.log",
            "log_level = notice",
            "emergency_restart_threshold = 10",
            "emergency_restart_interval = 1m",
            "process_control_timeout = 10s",
            "daemonize = no",
            f"include = {pool_glob}",
            "",
        ]
    )


def render_systemd_template() -> str:
    return "\n".join(
        [
            "[Unit]",
            "Description=IFNOTUS PHP-FPM environment %i",
            "After=network.target",
            "Requires=ifnotus-workloads-tenants-env-%i.slice",
            "",
            "[Service]",
            "Type=notify",
            "# Master stays root so pool user= setuid works; cgroup is the env slice.",
            "Slice=ifnotus-workloads-tenants-env-%i.slice",
            "ExecStartPre=/usr/bin/mkdir -p /run/php/ifnotus/%i /var/log/php/ifnotus/%i",
            f"ExecStart={PHP_FPM_BIN} --nodaemonize --fpm-config {ENV_CONFIG_ROOT}/%i/php-fpm.conf",
            "ExecReload=/bin/kill -USR2 $MAINPID",
            "Restart=on-failure",
            "RestartSec=3",
            "TimeoutStopSec=20",
            "KillMode=mixed",
            "",
            "[Install]",
            "WantedBy=multi-user.target",
            "",
        ]
    )


class PhpFpmEnvironmentService:
    def __init__(
        self,
        *,
        pool_dir: Path | None = None,
        env_root: Path | None = None,
        systemd_dir: Path | None = None,
        backup_root: Path | None = None,
        php_bin: Path | None = None,
    ) -> None:
        self.pool_dir = pool_dir or GLOBAL_POOL_DIR
        self.env_root = env_root or ENV_CONFIG_ROOT
        self.systemd_dir = systemd_dir or SYSTEMD_DIR
        self.backup_root = backup_root or BACKUP_ROOT
        self.php_bin = php_bin or PHP_FPM_BIN

    def discover_hostnames(self, env, extra_names: Iterable[str] | None = None) -> list[str]:
        hosts: set[str] = set()
        if getattr(env, "domain", None):
            hosts.add(str(env.domain).lower().strip())
        for attr in ("domains", "customer_domains"):
            rel = getattr(env, attr, None)
            if not rel:
                continue
            for row in rel:
                name = getattr(row, "domain_name", None) or getattr(row, "name", None)
                if name:
                    hosts.add(str(name).lower().strip())
        for n in extra_names or []:
            if n:
                hosts.add(str(n).lower().strip())
        return sorted(h for h in hosts if h)

    def resolve_pools_for_environment(
        self, env, *, extra_hostnames: Iterable[str] | None = None
    ) -> list[EnvPoolRef]:
        hosts = self.discover_hostnames(env, extra_hostnames)
        refs: list[EnvPoolRef] = []
        seen: set[str] = set()
        for host in hosts:
            candidates = [host]
            if not host.startswith("www."):
                candidates.append(f"www.{host}")
            for h in candidates:
                name = fpm_pool_name(h)
                if name in seen:
                    continue
                active = self.pool_dir / f"{name}.conf"
                disabled = self.pool_dir / f"{name}.conf{DISABLED_SUFFIX}"
                src = active if active.is_file() else disabled if disabled.is_file() else None
                if src is None:
                    continue
                body = src.read_text(encoding="utf-8", errors="replace")
                refs.append(
                    EnvPoolRef(
                        hostname=h,
                        pool_name=name,
                        global_conf=self.pool_dir / f"{name}.conf",
                        listen=_pool_listen(body) or str(fpm_socket_for(h)),
                        user=_pool_user(body),
                        group=_pool_group(body),
                        body=body,
                    )
                )
                seen.add(name)
        return refs

    def validate_pools_belong_only_to_env(
        self,
        env,
        pools: list[EnvPoolRef],
        *,
        require_tenant_unix_user: bool = False,
        allow_legacy_www_data: bool = False,
    ) -> list[str]:
        """Validate pool Unix users.

        ``allow_legacy_www_data`` permits www-data pools for the target env without
        rewriting identity (recorded as LEGACY_IDENTITY_DEBT by plan_migrate).
        Cross-tenant ifn_* and root remain hard failures.
        """
        errors: list[str] = []
        expected = (getattr(env, "unix_username", None) or "").strip()
        if require_tenant_unix_user and (not expected or not expected.startswith("ifn_")):
            errors.append("INVALID_ENV_IDENTITY: missing ifn_* unix_username")
            return errors
        for p in pools:
            user = (p.user or "").strip()
            if user == "root":
                errors.append(f"ROOT_PHP_POOL_SECURITY_VIOLATION: pool {p.pool_name} user=root")
                continue
            if expected and user.startswith("ifn_") and user != expected:
                errors.append(
                    f"CROSS_TENANT_POOL_IDENTITY: pool {p.pool_name} user={user} expected={expected}"
                )
                continue
            if require_tenant_unix_user:
                if user == "www-data":
                    if allow_legacy_www_data:
                        continue
                    errors.append(f"LEGACY_SHARED_USER: pool {p.pool_name} user=www-data")
                elif expected and user != expected:
                    errors.append(
                        f"POOL_IDENTITY_MISMATCH: pool {p.pool_name} user={user} expected={expected}"
                    )
            elif expected and user not in {expected, "www-data"}:
                errors.append(
                    f"pool {p.pool_name} user={user} does not match env unix_username={expected}"
                )
        return errors

    def plan_migrate(
        self,
        env,
        *,
        extra_hostnames: Iterable[str] | None = None,
        allow_vps: bool = False,
        plan_class: str | None = None,
        require_tenant_unix_user: bool = False,
        allow_legacy_www_data: bool = False,
        allow_excluded_domain: bool = False,
    ) -> MigratePlan:
        short = env_short_id(env.id)
        plan = MigratePlan(
            environment_id=str(env.id),
            short_id=short,
            slice_name=slice_name_for(env.id),
            service_name=planned_fpm_service_name(env.id),
            config_root=str(self.env_root / short),
        )
        if plan_class in {"VPS_STYLE", "VDS_STYLE", "CUSTOM"} and not allow_vps:
            plan.errors.append(f"plan class {plan_class} excluded unless allow_vps")
            return plan
        domain = (getattr(env, "domain", None) or "").lower()
        if is_excluded_canary_domain(domain) and not allow_excluded_domain:
            plan.errors.append(f"domain {domain} excluded from migrate")
            return plan

        pools = self.resolve_pools_for_environment(env, extra_hostnames=extra_hostnames)
        plan.pools = pools
        if not pools:
            plan.errors.append("no global PHP pools found for environment hostnames")
            return plan
        plan.errors.extend(
            self.validate_pools_belong_only_to_env(
                env,
                pools,
                require_tenant_unix_user=require_tenant_unix_user,
                allow_legacy_www_data=allow_legacy_www_data,
            )
        )
        if any((p.user or "").strip() == "www-data" for p in pools):
            plan.warnings.append(
                "LEGACY_IDENTITY_DEBT: www-data pool user preserved (not converted to ifn_*)"
            )
        if plan.errors:
            return plan

        config_root = self.env_root / short
        pool_d = config_root / "pool.d"
        master = config_root / "php-fpm.conf"
        template = self.systemd_dir / TEMPLATE_UNIT
        unit = f"ifnotus-php-fpm@{short}.service"

        plan.actions.append(
            {
                "action": "ensure_dirs",
                "paths": [
                    str(config_root),
                    str(pool_d),
                    f"/run/php/ifnotus/{short}",
                    f"/var/log/php/ifnotus/{short}",
                ],
            }
        )
        plan.actions.append(
            {
                "action": "write_master_conf",
                "path": str(master),
                "content": render_env_master_conf(short_id=short, pool_glob=str(pool_d / "*.conf")),
            }
        )
        for p in pools:
            plan.actions.append(
                {
                    "action": "write_pool_conf",
                    "path": str(pool_d / f"{p.pool_name}.conf"),
                    "content": p.body,
                    "listen": p.listen,
                    "user": p.user,
                }
            )
        plan.actions.append(
            {"action": "write_systemd_template", "path": str(template), "content": render_systemd_template()}
        )
        plan.actions.append({"action": "php_fpm_test", "config": str(master)})
        plan.actions.append({"action": "ensure_slice", "slice": plan.slice_name})
        for p in pools:
            plan.actions.append(
                {
                    "action": "disable_global_pool",
                    "from": str(self.pool_dir / f"{p.pool_name}.conf"),
                    "to": str(self.pool_dir / f"{p.pool_name}.conf{DISABLED_SUFFIX}"),
                }
            )
        plan.actions.append({"action": "reload_global_fpm"})
        plan.actions.append({"action": "start_env_fpm", "unit": unit})
        plan.actions.append({"action": "nginx_unchanged_socket_preserved"})
        plan.nginx_changes = []
        plan.rollback_steps = [
            f"systemctl stop {unit}",
            f"rename *{DISABLED_SUFFIX} back to .conf",
            "systemctl reload php8.3-fpm",
        ]
        for p in pools:
            for conf in self.pool_dir.glob("*.conf"):
                if conf.name == f"{p.pool_name}.conf" or DISABLED_SUFFIX in conf.name:
                    continue
                try:
                    other = conf.read_text(encoding="utf-8", errors="replace")
                except OSError:
                    continue
                if _pool_listen(other) == p.listen:
                    plan.errors.append(f"socket collision: {p.listen} also in {conf.name}")
        return plan

    def apply_migrate(self, plan: MigratePlan, *, dry_run: bool = True) -> dict[str, Any]:
        report: dict[str, Any] = {"dry_run": dry_run, "ok": False, "steps": [], "errors": list(plan.errors)}
        if plan.errors:
            return report
        if dry_run:
            report["steps"] = [{"would": a} for a in plan.actions]
            report["ok"] = True
            report["note"] = "dry-run — no system changes"
            return report

        self.backup_root.mkdir(parents=True, exist_ok=True)
        try:
            for a in plan.actions:
                act = a["action"]
                if act == "ensure_dirs":
                    for p in a["paths"]:
                        Path(p).mkdir(parents=True, exist_ok=True)
                elif act in {"write_master_conf", "write_pool_conf", "write_systemd_template"}:
                    path = Path(a["path"])
                    path.parent.mkdir(parents=True, exist_ok=True)
                    if path.exists():
                        (self.backup_root / f"{plan.short_id}-{path.name}.bak").write_bytes(path.read_bytes())
                    path.write_text(a["content"], encoding="utf-8")
                elif act == "php_fpm_test":
                    ok, msg = self.validate_config(Path(a["config"]))
                    report["steps"].append({"php_fpm_test": ok, "msg": msg[:400]})
                    if not ok:
                        report["errors"].append(f"config test failed: {msg[:300]}")
                        return report
                elif act == "ensure_slice":
                    self._systemctl("start", a["slice"])
                elif act == "disable_global_pool":
                    src, dst = Path(a["from"]), Path(a["to"])
                    if src.is_file():
                        (self.backup_root / src.name).write_bytes(src.read_bytes())
                        if dst.exists():
                            dst.unlink()
                        src.rename(dst)
                    elif dst.is_file():
                        # Already disabled; ensure no active duplicate remains.
                        report["steps"].append({"already_disabled": dst.name})
                    else:
                        report["warnings"] = report.get("warnings") or []
                        report["warnings"].append(f"global pool missing for disable: {src}")
                elif act == "reload_global_fpm":
                    self._systemctl("reload", "php8.3-fpm.service")
                elif act == "start_env_fpm":
                    self._systemctl("daemon-reload")
                    self._systemctl("enable", a["unit"])
                    proc = self._systemctl("restart", a["unit"])
                    report["steps"].append(
                        {"start_env_fpm": a["unit"], "rc": proc.returncode, "err": (proc.stderr or "")[:300]}
                    )
                    if proc.returncode != 0:
                        report["errors"].append(f"start failed: {(proc.stderr or proc.stdout or '')[:400]}")
                        report["rollback"] = self.rollback(plan)
                        report["rolled_back"] = True
                        return report
                report["steps"].append({"done": act})
            report["ok"] = True
        except OSError as exc:
            report["errors"].append(str(exc))
            report["rollback"] = self.rollback(plan)
            report["rolled_back"] = True
        return report

    def rollback(self, plan: MigratePlan) -> dict[str, Any]:
        out: dict[str, Any] = {"steps": [], "ok": True}
        unit = f"ifnotus-php-fpm@{plan.short_id}.service"
        self._systemctl("stop", unit)
        out["steps"].append(f"stopped {unit}")
        for p in plan.pools:
            src = self.pool_dir / f"{p.pool_name}.conf{DISABLED_SUFFIX}"
            dst = self.pool_dir / f"{p.pool_name}.conf"
            if src.is_file():
                if dst.exists():
                    dst.unlink()
                src.rename(dst)
                out["steps"].append(f"restored {dst.name}")
            else:
                bak = self.backup_root / f"{p.pool_name}.conf"
                if bak.is_file() and not dst.exists():
                    shutil.copy2(bak, dst)
                    out["steps"].append(f"restored {dst.name} from backup")
        ok, msg = self._global_fpm_test()
        out["steps"].append({"global_fpm_test": ok, "msg": msg[:200]})
        self._systemctl("reload", "php8.3-fpm.service")
        out["steps"].append("reloaded php8.3-fpm")
        return out

    def validate_config(self, master_conf: Path) -> tuple[bool, str]:
        binary = str(self.php_bin if self.php_bin.exists() else "php-fpm8.3")
        proc = subprocess.run(
            [binary, "-t", "-y", str(master_conf)],
            capture_output=True,
            text=True,
            check=False,
            timeout=60,
        )
        return proc.returncode == 0, (proc.stdout or "") + (proc.stderr or "")

    def _global_fpm_test(self) -> tuple[bool, str]:
        binary = str(self.php_bin if self.php_bin.exists() else "php-fpm8.3")
        proc = subprocess.run([binary, "-t"], capture_output=True, text=True, check=False, timeout=60)
        return proc.returncode == 0, (proc.stdout or "") + (proc.stderr or "")

    def status(self, env, *, extra_hostnames: Iterable[str] | None = None) -> dict[str, Any]:
        short = env_short_id(env.id)
        unit = f"ifnotus-php-fpm@{short}.service"
        pools = self.resolve_pools_for_environment(env, extra_hostnames=extra_hostnames)
        active = (self._systemctl("is-active", unit).stdout or "").strip()
        main_pid = "0"
        for line in (self._systemctl("show", unit, "-p", "MainPID").stdout or "").splitlines():
            if line.startswith("MainPID="):
                main_pid = line.split("=", 1)[1].strip()
        workers: list[dict[str, Any]] = []
        cgroup = ""
        if main_pid not in {"", "0"}:
            workers = self._list_fpm_workers(int(main_pid), [p.pool_name for p in pools])
            try:
                cgroup = Path(f"/proc/{main_pid}/cgroup").read_text(encoding="utf-8").strip()
            except OSError:
                cgroup = ""
        rss_master = self._rss_mb(int(main_pid)) if main_pid not in {"", "0"} else 0.0
        global_active = [p.pool_name for p in pools if (self.pool_dir / f"{p.pool_name}.conf").is_file()]
        global_disabled = [
            p.pool_name for p in pools if (self.pool_dir / f"{p.pool_name}.conf{DISABLED_SUFFIX}").is_file()
        ]
        if global_disabled and active == "active":
            state = "migrated"
        elif global_active and active != "active":
            state = "global"
        elif active == "active":
            state = "env_master_running"
        else:
            state = "unknown"
        sock_ok = []
        for p in pools:
            listen = p.listen
            if listen.startswith("/"):
                sock_ok.append(Path(listen).exists())
            else:
                sock_ok.append(True)
        drift = diagnose_migration_state(
            env_unit_active=(active == "active"),
            global_pools_active=global_active,
            global_pools_disabled=global_disabled,
            sockets_exist=sock_ok,
            socket_conflicts=[],
            duplicate_pool_names=[],
        )
        # TasksMax risk: sum pm.max_children across all pools for this env master
        tasks_risk = None
        if pools:
            children = 0
            for p in pools:
                m = re.search(r"^pm\.max_children\s*=\s*(\d+)", p.body, re.M)
                children += int(m.group(1)) if m else 2
            tasks_max = 40
            show = self._systemctl("show", slice_name_for(env.id), "-p", "TasksMax")
            for line in (show.stdout or "").splitlines():
                if line.startswith("TasksMax="):
                    raw = line.split("=", 1)[1].strip()
                    if raw.isdigit():
                        tasks_max = int(raw)
            tasks_risk = estimate_tasksmax_risk(tasks_max=tasks_max, pm_max_children=children)
        return {
            "environment_id": str(env.id),
            "short_id": short,
            "hostnames": [p.hostname for p in pools],
            "global_pools_active": global_active,
            "global_pools_disabled": global_disabled,
            "env_master": {
                "unit": unit,
                "active": active,
                "main_pid": main_pid,
                "master_user": "root",
                "master_rss_mb": rss_master,
                "cgroup": cgroup,
                "config_root": str(self.env_root / short),
            },
            "workers": workers,
            "worker_rss_mb": sum(float(w.get("rss_mb") or 0) for w in workers),
            "slice": slice_name_for(env.id),
            "migration_state": state,
            "drift_state": drift,
            "sockets": [p.listen for p in pools],
            "tasksmax_risk": tasks_risk,
        }

    def _list_fpm_workers(self, master_pid: int, pool_names: list[str]) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        proc = subprocess.run(
            ["ps", "-eo", "user,pid,ppid,rss,cmd", "--no-headers"],
            capture_output=True,
            text=True,
            check=False,
        )
        for line in (proc.stdout or "").splitlines():
            parts = line.split(None, 4)
            if len(parts) < 5:
                continue
            user, pid_s, ppid_s, rss_s, cmd = parts
            if "php-fpm" not in cmd or "master" in cmd:
                continue
            if ppid_s != str(master_pid) and not any(n in cmd for n in pool_names):
                continue
            try:
                out.append(
                    {
                        "user": user,
                        "pid": int(pid_s),
                        "ppid": int(ppid_s),
                        "rss_mb": round(int(rss_s) / 1024, 1),
                        "cmd": cmd[:120],
                    }
                )
            except ValueError:
                continue
        return out

    @staticmethod
    def _rss_mb(pid: int) -> float:
        try:
            for line in Path(f"/proc/{pid}/status").read_text(encoding="utf-8").splitlines():
                if line.startswith("VmRSS:"):
                    return round(int(line.split()[1]) / 1024, 1)
        except (OSError, ValueError, IndexError):
            return 0.0
        return 0.0

    @staticmethod
    def _systemctl(*args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["systemctl", *args],
            capture_output=True,
            text=True,
            check=False,
            timeout=90,
        )


def hostname_pools_from_refs(environment_id: UUID, refs: list[EnvPoolRef]) -> list[HostnamePool]:
    return [
        HostnamePool(
            hostname=r.hostname,
            environment_id=environment_id,
            pool_name=r.pool_name,
            listen_socket=r.listen,
        )
        for r in refs
    ]
