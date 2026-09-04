"""PHASE 26 — OS-level runtime resource limits for customer applications."""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppException
from app.models.platform import ApplicationInstance, CustomerEnvironment, HostingPlan
from app.services.platform.plan_matrix import feature_included, features_for, stack_level, NO

RUNTIME_FAMILIES = {
    "python": "python",
    "flask": "python",
    "fastapi": "python",
    "django": "python",
    "nodejs": "node",
    "express": "node",
    "react": "node",
    "vue": "node",
    "nextjs": "node",
    "php": "php",
    "laravel": "php",
    "wordpress": "php",
    "static": "php",
}


@dataclass(frozen=True)
class AppResourceLimits:
    python_apps: int
    node_apps: int
    php_apps: int
    app_memory_mb: int
    max_workers: int
    max_processes: int
    max_open_ports: int
    cpu_shares: int  # supervisor/docker relative weight


def runtime_family(framework: str | None) -> str:
    return RUNTIME_FAMILIES.get((framework or "").strip().lower(), "other")


def limits_for_plan(plan: HostingPlan | None) -> AppResourceLimits:
    """Derive per-app limits from frozen plan features (not UI-only)."""
    feats = features_for(plan)
    ram_gb = float(getattr(plan, "ram_gb", None) or feats.get("ram_gb") or 1)

    def _int(key: str, default: int) -> int:
        raw = feats.get(key)
        if raw is None:
            return default
        try:
            return max(0, int(raw))
        except (TypeError, ValueError):
            return default

    py_default = 1 if stack_level(plan, "python") != NO else 0
    node_default = 1 if stack_level(plan, "nodejs") != NO else 0
    php_default = 2 if stack_level(plan, "php") != NO else 0

    mem_default = max(256, min(2048, int(ram_gb * 1024 / max(1, py_default + node_default + php_default + 1))))

    return AppResourceLimits(
        python_apps=_int("python_apps", py_default),
        node_apps=_int("node_apps", node_default),
        php_apps=_int("php_apps", php_default),
        app_memory_mb=_int("app_memory_mb", mem_default),
        max_workers=max(1, _int("max_workers", 2)),
        max_processes=max(4, _int("max_processes", 10)),
        max_open_ports=max(1, _int("max_open_ports", 5)),
        cpu_shares=max(64, _int("cpu_shares", 256)),
    )


def limits_to_dict(limits: AppResourceLimits) -> dict[str, Any]:
    return {
        "python_apps": limits.python_apps,
        "node_apps": limits.node_apps,
        "php_apps": limits.php_apps,
        "app_memory_mb": limits.app_memory_mb,
        "max_workers": limits.max_workers,
        "max_processes": limits.max_processes,
        "max_open_ports": limits.max_open_ports,
        "cpu_shares": limits.cpu_shares,
    }


class ResourceEnforcementService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def count_apps(self, environment_id) -> dict[str, int]:
        result = await self._session.execute(
            select(ApplicationInstance).where(
                ApplicationInstance.environment_id == environment_id,
                ApplicationInstance.status.notin_(["terminated", "deleted"]),
            )
        )
        counts = {"python": 0, "node": 0, "php": 0, "other": 0, "total": 0}
        for app in result.scalars().all():
            fam = runtime_family(app.framework)
            counts[fam] = counts.get(fam, 0) + 1
            counts["total"] += 1
        return counts

    async def assert_can_create(
        self,
        env: CustomerEnvironment,
        plan: HostingPlan | None,
        framework: str,
    ) -> AppResourceLimits:
        limits = limits_for_plan(plan)
        fam = runtime_family(framework)
        counts = await self.count_apps(env.id)

        caps = {
            "python": limits.python_apps,
            "node": limits.node_apps,
            "php": limits.php_apps,
        }
        cap = caps.get(fam, 0)

        if fam in caps and counts.get(fam, 0) >= cap:
            raise AppException(
                f"Your plan allows {cap} {fam} application(s). Remove one or upgrade.",
                code="app_quota_exceeded",
            )
        if counts["total"] >= limits.max_open_ports:
            raise AppException(
                f"Your plan allows {limits.max_open_ports} concurrent application(s) with open ports.",
                code="app_port_quota_exceeded",
            )
        return limits

    def apply_to_instance(self, app: ApplicationInstance, limits: AppResourceLimits) -> None:
        app.memory_limit_mb = limits.app_memory_mb
        app.worker_limit = limits.max_workers
        cfg = dict(app.config_json or {})
        cfg["resource_limits"] = limits_to_dict(limits)
        app.config_json = cfg

    @staticmethod
    def wrap_command(command: str, limits: AppResourceLimits) -> str:
        """Prefix start/build commands with prlimit when available (kernel enforcement)."""
        prlimit = shutil.which("prlimit")
        if not prlimit or not command.strip():
            return command
        mem_bytes = int(limits.app_memory_mb) * 1024 * 1024
        # V8/Node map far more virtual address space than RSS; RLIMIT_AS at the
        # advertised RAM ceiling kills `node` immediately. Keep a floor of 1GiB
        # VAS and 8× the plan memory. On Linux, threads also count toward
        # RLIMIT_NPROC — raise the floor so Node can start.
        as_limit = max(mem_bytes * 8, 1024 * 1024 * 1024)
        nproc = max(int(limits.max_processes or 10), 64)
        return (
            f"{prlimit} --as={as_limit} --nproc={nproc} "
            f"--nofile=4096 -- {command}"
        )

    @staticmethod
    def supervisor_program_block(
        *,
        program: str,
        user_line: str,
        directory: str,
        start_cmd: str,
        limits: AppResourceLimits,
        log_path: str,
        env_lines: str,
    ) -> str:
        wrapped = ResourceEnforcementService.wrap_command(start_cmd, limits)
        # Apps bind a single PORT; supervisor numprocs>1 causes "Address already in use".
        # Concurrency belongs to gunicorn/uvicorn/node workers, not duplicate listeners.
        numprocs = 1
        return f"""[program:{program}]
{user_line}directory={directory}
command={wrapped}
autostart=true
autorestart=true
numprocs={numprocs}
process_name=%(program_name)s_%(process_num)02d
stdout_logfile={log_path}
stderr_logfile={log_path}
stopasgroup=true
killasgroup=true
priority={limits.cpu_shares}
{env_lines}
"""

    @staticmethod
    def environment_docker_limits(env: CustomerEnvironment) -> tuple[str, str]:
        """Return docker --cpus and --memory for the environment container."""
        from app.services.platform.isolation import docker_cpus, docker_memory

        return docker_cpus(env.cpu_limit), docker_memory(env.ram_limit_gb)
