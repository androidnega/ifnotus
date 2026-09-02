"""Phase 2B PHP-FPM architecture — DESIGN ONLY (not deployed).

Preferred model: one PHP-FPM master per CustomerEnvironment, loading all
hostname pools that belong to that environment, placed in the environment
systemd slice so workers inherit MemoryMax/CPUQuota accounting.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Any
from uuid import UUID


PHASE_2B_PHP_ENV_MASTER_DESIGN: dict[str, Any] = {
    "recommended_model": "ONE_FPM_MASTER_PER_CUSTOMER_ENVIRONMENT",
    "not_recommended": "one FPM master per hostname (~171)",
    "systemd_template": "ifnotus-php-fpm@.service",
    "slice": "ifnotus-workloads-tenants-env-<shortid>.slice",
    "config_layout": {
        "root": "/etc/php/8.3/ifnotus-envs/<env-shortid>/",
        "main": "php-fpm.conf",
        "pools": "pool.d/*.conf",
        "reuse": "include shared snippets from /etc/php/8.3/fpm/conf.d where safe",
    },
    "socket_strategy": (
        "Keep per-hostname Unix sockets (e.g. /run/php/ifnotus-<host>.sock) so Nginx "
        "fastcgi_pass stays unchanged; all pools load in the same env master."
    ),
    "pid_layout": "/run/php/ifnotus-env-<shortid>.pid",
    "log_layout": "/var/log/php8.3-fpm/ifnotus-env-<shortid>/{error,slow}.log",
    "opcache": (
        "Separate masters mean separate OPCache arenas — expect ~N * opcache.memory_consumption "
        "overhead; size canaries carefully; do not share OPCache across tenants."
    ),
    "reload_behavior": "systemctl reload ifnotus-php-fpm@<env> affects only that environment",
    "failure_isolation": "crash of one env master does not take down other tenants",
    "deployment_complexity": "medium — generator + systemd template + nginx socket path unchanged",
    "memory_policy": "Phase 2B proves containment only; MemoryHigh/Max 2/6/12 deferred to Phase 2C",
    "canary_strategy": [
        "Pick one low-risk shared PHP tenant (not IFNOTUS/VoteBridge/QuizSnap/critical)",
        "Migrate that environment's pools into ifnotus-php-fpm@env; verify site/PHP/session/upload/DB",
        "Confirm worker /proc/<pid>/cgroup is under tenants-env-<id>.slice",
        "Confirm EnvironmentSliceService.read_usage reflects PHP RSS",
        "Expand to 2–3 low-risk environments",
        "Gradual rollout remaining shared PHP envs",
        "Do not change MemoryMax entitlements in Phase 2B",
    ],
    "success_criteria": [
        "site loads",
        "PHP executes",
        "sessions work",
        "uploads work",
        "database access works",
        "mail calls if relevant",
        "cron still works",
        "no nginx 502",
        "FPM logs clean",
        "worker cgroup = env slice",
        "usage visible in monitoring",
    ],
}


@dataclass(frozen=True)
class HostnamePool:
    hostname: str
    environment_id: UUID
    pool_name: str
    listen_socket: str


def group_pools_by_environment(pools: list[HostnamePool]) -> dict[UUID, list[HostnamePool]]:
    """Map hostname pools → one future FPM service per CustomerEnvironment."""
    grouped: dict[UUID, list[HostnamePool]] = defaultdict(list)
    for pool in pools:
        grouped[pool.environment_id].append(pool)
    return dict(grouped)


def planned_fpm_service_name(environment_id: UUID | str) -> str:
    short = str(environment_id).split("-")[0].lower()
    return f"ifnotus-php-fpm@{short}.service"


def estimate_master_overhead(
    *,
    environment_count: int,
    baseline_master_rss_kib: int,
) -> dict[str, Any]:
    """Rough RSS estimate for N env masters (design planning only)."""
    total_kib = environment_count * baseline_master_rss_kib
    return {
        "environment_count": environment_count,
        "baseline_master_rss_kib": baseline_master_rss_kib,
        "estimated_total_rss_kib": total_kib,
        "estimated_total_rss_mib": round(total_kib / 1024, 1),
        "note": "Workers dominate RAM; master overhead is additive but smaller than per-host masters",
    }


def assert_environments_never_share_instance(
    grouped: dict[UUID, list[HostnamePool]],
) -> None:
    """Invariant: each HostnamePool maps to exactly one env key; no cross-env merge."""
    seen_hosts: set[str] = set()
    for env_id, pools in grouped.items():
        for pool in pools:
            assert pool.environment_id == env_id
            key = pool.hostname.lower()
            assert key not in seen_hosts, f"hostname {key} assigned to multiple env groups"
            seen_hosts.add(key)
