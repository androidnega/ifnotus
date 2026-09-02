"""Per-environment systemd/cgroup v2 resource slices.

Phase 2A nests environment slices under::

  ifnotus-workloads-tenants-env-<shortid>.slice

Legacy ``ifnotus-env-<shortid>.slice`` names are still recognized for migration
and usage fallback. Individual MemoryMax / CPUQuota / TasksMax stay at the
environment's current plan-derived values (not the future 2/6/12 GiB targets).
"""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.core.logging import get_logger
from app.models.platform import CustomerEnvironment
from app.services.platform.resource_enforcement import limits_for_plan
from app.services.platform.workload_slices import (
    ENV_SLICE_PREFIX,
    legacy_slice_name_for,
    render_env_slice_unit,
    resolve_slice_cgroup_path,
    slice_name_for,
)

logger = get_logger(__name__)

_SLICE_DIR = Path("/etc/systemd/system")
_CGROUP_ROOT = Path("/sys/fs/cgroup")

__all__ = [
    "EnvSliceLimits",
    "EnvironmentSliceService",
    "apply_env_resource_limits",
    "cgroup_v2_available",
    "legacy_slice_name_for",
    "limits_from_env",
    "slice_name_for",
    "systemd_available",
]


@dataclass(frozen=True)
class EnvSliceLimits:
    cpu_quota_percent: int
    memory_max_bytes: int
    tasks_max: int
    slice_name: str


def limits_from_env(env: CustomerEnvironment, plan=None) -> EnvSliceLimits:
    cpu = float(env.cpu_limit or 0) or 0.25
    ram_gb = float(env.ram_limit_gb or 0) or 0.25
    app_limits = limits_for_plan(plan)
    cpu_pct = max(5, min(400, int(round(cpu * 100))))
    mem_bytes = max(64 * 1024 * 1024, int(ram_gb * 1024 * 1024 * 1024))
    tasks = max(16, int(app_limits.max_processes or 10) * 4)
    return EnvSliceLimits(
        cpu_quota_percent=cpu_pct,
        memory_max_bytes=mem_bytes,
        tasks_max=tasks,
        slice_name=slice_name_for(env.id),
    )


def cgroup_v2_available() -> bool:
    controllers = _CGROUP_ROOT / "cgroup.controllers"
    if not controllers.is_file():
        return False
    try:
        text = controllers.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False
    return "cpu" in text and "memory" in text


def systemd_available() -> bool:
    return shutil.which("systemctl") is not None and _SLICE_DIR.is_dir()


class EnvironmentSliceService:
    """Install / resize / remove / sample per-environment systemd slices."""

    def ensure_slice(self, env: CustomerEnvironment, plan=None) -> dict[str, Any]:
        limits = limits_from_env(env, plan)
        result: dict[str, Any] = {
            "slice": limits.slice_name,
            "cpu_quota_percent": limits.cpu_quota_percent,
            "memory_max_bytes": limits.memory_max_bytes,
            "tasks_max": limits.tasks_max,
            "legacy_slice": legacy_slice_name_for(env.id),
        }
        if not systemd_available():
            result["skipped"] = "systemd_unavailable"
            return result
        if not cgroup_v2_available():
            result["skipped"] = "cgroup_v2_unavailable"
            return result

        unit_path = _SLICE_DIR / limits.slice_name
        body = self._unit_body(limits)
        legacy_path = _SLICE_DIR / legacy_slice_name_for(env.id)
        try:
            previous = unit_path.read_text(encoding="utf-8") if unit_path.exists() else ""
            if previous != body:
                unit_path.write_text(body, encoding="utf-8")
                self._systemctl("daemon-reload")
            self._systemctl("start", limits.slice_name)
            self._systemctl(
                "set-property",
                limits.slice_name,
                f"CPUQuota={limits.cpu_quota_percent}%",
                f"MemoryMax={limits.memory_max_bytes}",
                f"TasksMax={limits.tasks_max}",
            )
            if legacy_path.exists() and legacy_path != unit_path:
                self._systemctl("stop", legacy_path.name)
                try:
                    legacy_path.unlink()
                    self._systemctl("daemon-reload")
                    result["legacy_removed"] = legacy_path.name
                except OSError as exc:
                    result["legacy_remove_error"] = str(exc)
            result["applied"] = True
        except OSError as exc:
            logger.warning("env_slice_ensure_failed", slice=limits.slice_name, error=str(exc))
            result["error"] = str(exc)
        return result

    def resize_slice(self, env: CustomerEnvironment, plan=None) -> dict[str, Any]:
        return self.ensure_slice(env, plan)

    def remove_slice(self, env: CustomerEnvironment) -> dict[str, Any]:
        names = [slice_name_for(env.id), legacy_slice_name_for(env.id)]
        result: dict[str, Any] = {"slices": names}
        if not systemd_available():
            result["skipped"] = "systemd_unavailable"
            return result
        removed: list[str] = []
        for name in names:
            unit_path = _SLICE_DIR / name
            try:
                self._systemctl("stop", name)
            except Exception:  # noqa: BLE001
                pass
            try:
                if unit_path.exists():
                    unit_path.unlink()
                    removed.append(name)
            except OSError as exc:
                result["error"] = str(exc)
        if removed:
            self._systemctl("daemon-reload")
            result["removed"] = removed
        return result

    def read_usage(self, env: CustomerEnvironment) -> dict[str, Any]:
        """Read live usage from the slice cgroup, falling back to unix-user psutil."""
        name = slice_name_for(env.id)
        legacy = legacy_slice_name_for(env.id)
        out: dict[str, Any] = {
            "slice": name,
            "source": None,
            "cpu_percent": None,
            "memory_bytes": None,
            "memory_mb": None,
            "process_count": None,
            "available": False,
            "cgroup_path": None,
        }
        cg = resolve_slice_cgroup_path(name) or resolve_slice_cgroup_path(legacy)
        if cg is not None:
            out["cgroup_path"] = str(cg)
            out["slice"] = name if ENV_SLICE_PREFIX in cg.name else legacy
            mem = self._read_int(cg / "memory.current")
            pids = self._read_int(cg / "pids.current")
            cpu_usec = self._read_cpu_usage_usec(cg / "cpu.stat")
            out["source"] = "cgroup"
            out["available"] = True
            if mem is not None:
                out["memory_bytes"] = mem
                out["memory_mb"] = round(mem / (1024 * 1024), 1)
            if pids is not None:
                out["process_count"] = pids
            out["cpu_usage_usec"] = cpu_usec

        from app.services.platform.environment_monitoring import environment_live_stats

        proc = environment_live_stats(
            unix_username=getattr(env, "unix_username", None),
            unix_uid=getattr(env, "unix_uid", None),
            document_root=getattr(env, "document_root", None),
            domain=getattr(env, "domain", None),
        )
        if proc.get("available"):
            if out["source"] is None:
                out["source"] = str(proc.get("source") or "psutil")
                out["available"] = True
            elif out.get("source") == "cgroup" and proc.get("source"):
                out["source"] = f"cgroup+{proc.get('source')}"
            out["cpu_percent"] = float(proc.get("cpu_percent") or 0)
            proc_mem = float(proc.get("memory_rss_mb") or 0)
            if out.get("memory_mb") is None or (float(out.get("memory_mb") or 0) <= 0 and proc_mem > 0):
                out["memory_mb"] = proc_mem
                out["memory_bytes"] = int(proc_mem * 1024 * 1024)
            proc_count = int(proc.get("process_count") or 0)
            if out.get("process_count") is None or (int(out.get("process_count") or 0) <= 0 and proc_count > 0):
                out["process_count"] = proc_count
            out["available"] = True
        elif out.get("cpu_percent") is None and out.get("available"):
            out["cpu_percent"] = 0.0
            if out.get("memory_mb") is None:
                out["memory_mb"] = 0.0
                out["memory_bytes"] = 0
            if out.get("process_count") is None:
                out["process_count"] = 0
        return out

    def wrap_command_in_slice(
        self,
        command: str,
        env: CustomerEnvironment,
        *,
        plan=None,
    ) -> str:
        """Prefix a shell command with systemd-run --slice when possible."""
        if not command.strip():
            return command
        if not systemd_available() or not shutil.which("systemd-run"):
            return command
        limits = limits_from_env(env, plan)
        self.ensure_slice(env, plan)
        uid = getattr(env, "unix_uid", None)
        user_args = f"--uid={int(uid)} " if uid is not None else ""
        return (
            f"systemd-run --quiet --collect --scope "
            f"--slice={limits.slice_name} {user_args}-- {command}"
        )

    @staticmethod
    def _unit_body(limits: EnvSliceLimits) -> str:
        return render_env_slice_unit(
            slice_name=limits.slice_name,
            cpu_quota=f"{limits.cpu_quota_percent}%",
            memory_max=str(limits.memory_max_bytes),
            tasks_max=str(limits.tasks_max),
        )

    @staticmethod
    def _systemctl(*args: str) -> None:
        systemctl = shutil.which("systemctl")
        if not systemctl:
            return
        subprocess.run(
            [systemctl, *args],
            check=False,
            capture_output=True,
            text=True,
            timeout=30,
        )

    @staticmethod
    def _slice_cgroup_path(slice_name: str) -> Path | None:
        return resolve_slice_cgroup_path(slice_name)

    @staticmethod
    def _read_int(path: Path) -> int | None:
        try:
            return int(path.read_text(encoding="utf-8").strip())
        except (OSError, ValueError):
            return None

    @staticmethod
    def _read_cpu_usage_usec(path: Path) -> int | None:
        try:
            for line in path.read_text(encoding="utf-8").splitlines():
                if line.startswith("usage_usec"):
                    return int(line.split()[1])
        except (OSError, ValueError, IndexError):
            return None
        return None


def apply_env_resource_limits(env: CustomerEnvironment, plan=None) -> dict[str, Any]:
    """Apply filesystem slice + keep Docker path separate (caller may also resize container)."""
    return EnvironmentSliceService().ensure_slice(env, plan)
