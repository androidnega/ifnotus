"""Per-environment cron jobs — package-aware, tenant-identity execution (PHASE 31)."""

from __future__ import annotations

import json
import re
import shlex
import shutil
import subprocess
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.exceptions import AppException, NotFoundError, ValidationError
from app.core.logging import get_logger
from app.models.platform import CustomerEnvironment, HostingPlan
from app.services.platform.plan_matrix import features_for

logger = get_logger(__name__)

_SCHEDULE_RE = re.compile(r"^(\S+)\s+(\S+)\s+(\S+)\s+(\S+)\s+(\S+)$")
_MAX_COMMAND_LEN = 500
_RUN_TIMEOUT_SECONDS = 300
_ALLOWED_BINARIES = frozenset(
    {
        "php",
        "node",
        "npm",
        "npx",
        "python",
        "python3",
        "curl",
        "wget",
        "bash",
        "sh",
        "composer",
        "wp",
        "artisan",
    }
)


@dataclass(frozen=True)
class CronEntitlements:
    enabled: bool
    max_jobs: int
    min_interval_minutes: int


def entitlements_for_plan(plan: HostingPlan | None) -> CronEntitlements:
    feats = features_for(plan)
    level = str(feats.get("cron") or "no")
    enabled = level in {"yes", "limited"}
    max_jobs = int(feats.get("cron_jobs") or (2 if level == "limited" else 10 if enabled else 0))
    min_interval = int(
        feats.get("cron_min_interval_minutes")
        or (15 if level == "limited" else 5 if enabled else 60)
    )
    return CronEntitlements(
        enabled=enabled,
        max_jobs=max(0, max_jobs),
        min_interval_minutes=max(1, min_interval),
    )


def _cron_field_matches(field: str, value: int, *, minimum: int, maximum: int) -> bool:
    if field == "*":
        return True
    for part in field.split(","):
        part = part.strip()
        if not part:
            continue
        step = 1
        base = part
        if "/" in part:
            base, step_s = part.split("/", 1)
            try:
                step = max(1, int(step_s))
            except ValueError:
                return False
            if not base:
                base = "*"
        if base == "*":
            if (value - minimum) % step == 0:
                return True
            continue
        if "-" in base:
            try:
                start_s, end_s = base.split("-", 1)
                start, end = int(start_s), int(end_s)
            except ValueError:
                return False
            if start <= value <= end and (value - start) % step == 0:
                return True
            continue
        try:
            num = int(base)
        except ValueError:
            return False
        if step == 1:
            if value == num:
                return True
        elif value >= num and (value - num) % step == 0:
            return True
    return False


def schedule_matches(schedule: str, when: datetime) -> bool:
    """Return True if a 5-field cron schedule matches ``when`` (minute resolution)."""
    m = _SCHEDULE_RE.match(schedule.strip())
    if not m:
        return False
    minute, hour, day, month, weekday = m.groups()
    wd = when.weekday() + 1  # Mon=1 … Sun=7
    cron_wd = 0 if wd == 7 else wd
    return bool(
        _cron_field_matches(minute, when.minute, minimum=0, maximum=59)
        and _cron_field_matches(hour, when.hour, minimum=0, maximum=23)
        and _cron_field_matches(day, when.day, minimum=1, maximum=31)
        and _cron_field_matches(month, when.month, minimum=1, maximum=12)
        and (
            _cron_field_matches(weekday, cron_wd, minimum=0, maximum=7)
            or _cron_field_matches(weekday, wd % 7, minimum=0, maximum=7)
        )
    )


def estimate_min_interval_minutes(schedule: str) -> int | None:
    """Best-effort minimum gap between runs (minutes). None if unparseable."""
    m = _SCHEDULE_RE.match(schedule.strip())
    if not m:
        return None
    minute, hour, day, month, weekday = m.groups()

    def _values(field: str, minimum: int, maximum: int) -> list[int] | None:
        if field == "*":
            return list(range(minimum, maximum + 1))
        if field.startswith("*/"):
            try:
                step = max(1, int(field[2:]))
            except ValueError:
                return None
            return list(range(minimum, maximum + 1, step))
        out: list[int] = []
        for part in field.split(","):
            part = part.strip()
            if not part:
                continue
            if "/" in part:
                base, step_s = part.split("/", 1)
                try:
                    step = max(1, int(step_s))
                except ValueError:
                    return None
                if base == "*":
                    out.extend(range(minimum, maximum + 1, step))
                    continue
                if "-" in base:
                    try:
                        a, b = map(int, base.split("-", 1))
                    except ValueError:
                        return None
                    out.extend(range(a, b + 1, step))
                    continue
                try:
                    start = int(base)
                except ValueError:
                    return None
                out.extend(range(start, maximum + 1, step))
                continue
            if "-" in part:
                try:
                    a, b = map(int, part.split("-", 1))
                except ValueError:
                    return None
                out.extend(range(a, b + 1))
                continue
            try:
                out.append(int(part))
            except ValueError:
                return None
        return sorted(set(out)) if out else None

    mins = _values(minute, 0, 59)
    if mins is None:
        return None
    if len(mins) >= 2:
        gaps = [mins[i + 1] - mins[i] for i in range(len(mins) - 1)]
        gaps.append((mins[0] + 60) - mins[-1])
        min_gap = min(gaps) if gaps else 60
    else:
        min_gap = 60

    hours = _values(hour, 0, 23)
    if hours is None:
        return None
    if hour == "*" or (hours and len(hours) >= 24):
        return max(1, min_gap)
    if hours and len(hours) >= 2:
        hour_gaps = [hours[i + 1] - hours[i] for i in range(len(hours) - 1)]
        hour_gaps.append((hours[0] + 24) - hours[-1])
        return max(1, min(hour_gaps) * 60)
    if day == "*" and month == "*" and weekday == "*":
        return 24 * 60
    return 24 * 60


def validate_schedule(schedule: str, *, min_interval_minutes: int | None = None) -> str:
    schedule = " ".join(schedule.split())
    if not _SCHEDULE_RE.match(schedule):
        raise ValidationError(
            "Schedule must be a 5-field cron expression, e.g. */15 * * * *",
            code="invalid_cron_schedule",
        )
    now = datetime.now(UTC)
    try:
        schedule_matches(schedule, now)
    except Exception as exc:  # noqa: BLE001
        raise ValidationError(f"Invalid cron schedule: {exc}", code="invalid_cron_schedule") from exc

    if min_interval_minutes and min_interval_minutes > 1:
        estimated = estimate_min_interval_minutes(schedule)
        if estimated is not None and estimated < min_interval_minutes:
            raise ValidationError(
                f"This package requires at least {min_interval_minutes} minutes between runs "
                f"(your schedule fires about every {estimated} minute(s)). "
                f"Try */{min_interval_minutes} * * * *",
                code="cron_interval_too_short",
            )
    return schedule


def validate_command(command: str, *, domain: str | None = None) -> str:
    command = command.strip()
    if not command:
        raise ValidationError("Command is required.")
    if len(command) > _MAX_COMMAND_LEN:
        raise ValidationError("Command is too long.")
    forbidden = ("`", "$(", "${", "\n", "\r", ">>", ">", "<", "&&", "||", ";", "|")
    for token in forbidden:
        if token in command:
            raise ValidationError(
                f"Command contains disallowed token `{token}`.",
                code="invalid_cron_command",
            )
    try:
        parts = shlex.split(command)
    except ValueError as exc:
        raise ValidationError(f"Could not parse command: {exc}") from exc
    if not parts:
        raise ValidationError("Command is empty.")
    binary = parts[0]
    if binary.startswith("./") or binary.startswith("php") or binary in _ALLOWED_BINARIES:
        pass
    elif "/" in binary:
        if binary.startswith("/"):
            raise ValidationError("Absolute command paths are not allowed. Use a path under your site.")
    else:
        raise ValidationError(
            f"Command binary `{binary}` is not allowed. "
            "Use php, node, npm, curl, python3, composer, or a ./script in your site.",
            code="invalid_cron_command",
        )
    if binary in {"curl", "wget"} and domain:
        joined = " ".join(parts[1:])
        if "://" in joined and domain not in joined:
            raise ValidationError("curl/wget may only call your own domain.")
    return command


class EnvironmentCronService:
    def __init__(self, settings: Settings, session: AsyncSession) -> None:
        self._settings = settings
        self._session = session

    def entitlements(self, plan: HostingPlan | None) -> CronEntitlements:
        return entitlements_for_plan(plan)

    def _cron_path(self, env: CustomerEnvironment) -> Path:
        return Path(env.document_root or ".") / ".ifnotus" / "cron.json"

    def _log_dir(self, env: CustomerEnvironment) -> Path:
        return Path(env.document_root or ".") / ".ifnotus" / "cron-logs"

    def _load(self, env: CustomerEnvironment) -> list[dict[str, Any]]:
        path = self._cron_path(env)
        if not path.exists():
            return []
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return list(data.get("jobs") or []) if isinstance(data, dict) else []
        except (OSError, json.JSONDecodeError):
            return []

    def _save(self, env: CustomerEnvironment, jobs: list[dict[str, Any]]) -> None:
        path = self._cron_path(env)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps({"jobs": jobs, "updated_at": datetime.now(UTC).isoformat()}, indent=2),
            encoding="utf-8",
        )

    def list_jobs(self, env: CustomerEnvironment) -> list[dict[str, Any]]:
        return self._load(env)

    def add_job(
        self,
        env: CustomerEnvironment,
        *,
        schedule: str,
        command: str,
        enabled: bool = True,
        plan: HostingPlan | None = None,
    ) -> dict[str, Any]:
        if not env.document_root:
            raise AppException("Environment has no document root.")
        ent = entitlements_for_plan(plan)
        if not ent.enabled:
            raise ValidationError("Cron jobs are not included on this package.", code="pack_feature")
        jobs = self._load(env)
        if len(jobs) >= ent.max_jobs:
            raise ValidationError(
                f"This package allows {ent.max_jobs} cron job(s). Delete one or upgrade.",
                code="cron_quota",
            )
        schedule = validate_schedule(schedule, min_interval_minutes=ent.min_interval_minutes)
        command = validate_command(command, domain=env.domain)
        job = {
            "id": str(uuid4()),
            "schedule": schedule,
            "command": command,
            "enabled": bool(enabled),
            "created_at": datetime.now(UTC).isoformat(),
            "last_run_at": None,
            "last_status": None,
            "last_exit_code": None,
            "last_output": None,
        }
        jobs.append(job)
        self._save(env, jobs)
        return job

    def update_job(
        self,
        env: CustomerEnvironment,
        job_id: str,
        *,
        schedule: str | None = None,
        command: str | None = None,
        enabled: bool | None = None,
        plan: HostingPlan | None = None,
    ) -> dict[str, Any]:
        ent = entitlements_for_plan(plan)
        jobs = self._load(env)
        for job in jobs:
            if job.get("id") != job_id:
                continue
            if schedule is not None:
                job["schedule"] = validate_schedule(
                    schedule, min_interval_minutes=ent.min_interval_minutes
                )
            if command is not None:
                job["command"] = validate_command(command, domain=env.domain)
            if enabled is not None:
                job["enabled"] = bool(enabled)
            self._save(env, jobs)
            return job
        raise NotFoundError("Cron job not found.")

    def delete_job(self, env: CustomerEnvironment, job_id: str) -> None:
        jobs = self._load(env)
        new_jobs = [j for j in jobs if j.get("id") != job_id]
        if len(new_jobs) == len(jobs):
            raise NotFoundError("Cron job not found.")
        self._save(env, new_jobs)

    def run_job(self, env: CustomerEnvironment, job_id: str) -> dict[str, Any]:
        if str(getattr(env, "status", "") or "").lower() != "active":
            raise AppException(
                "Cron is disabled while this hosting environment is not active.",
                code="cron_env_not_active",
            )
        jobs = self._load(env)
        for job in jobs:
            if job.get("id") == job_id:
                return self._execute(env, job, jobs)
        raise NotFoundError("Cron job not found.")

    def _require_tenant_unix_user(self, env: CustomerEnvironment) -> str:
        """PHASE 38B — cron must never fall back to the worker (often root)."""
        import pwd

        username = (getattr(env, "unix_username", None) or "").strip()
        if not username:
            raise AppException(
                "Cron cannot run until a tenant Unix user is provisioned for this environment.",
                code="cron_missing_unix_user",
            )
        try:
            pwd.getpwnam(username)
        except KeyError as exc:
            raise AppException(
                f"Tenant Unix user {username!r} does not exist on this host.",
                code="cron_unix_user_missing",
            ) from exc
        return username

    def _build_argv(self, env: CustomerEnvironment, command: str) -> list[str]:
        """Build argv that always runs as the tenant Unix user — never as the worker."""
        username = self._require_tenant_unix_user(env)
        inner = ["bash", "-lc", command]
        runuser = shutil.which("runuser")
        if runuser:
            return [runuser, "-u", username, "--", *inner]
        sudo = shutil.which("sudo")
        if sudo:
            return [sudo, "-n", "-u", username, "--", *inner]
        raise AppException(
            "Cannot run cron as tenant: neither runuser nor sudo is available on this host.",
            code="cron_run_helper_unavailable",
        )

    def _execute(
        self,
        env: CustomerEnvironment,
        job: dict[str, Any],
        jobs: list[dict[str, Any]],
    ) -> dict[str, Any]:
        if str(getattr(env, "status", "") or "").lower() != "active":
            raise AppException(
                "Cron is disabled while this hosting environment is not active.",
                code="cron_env_not_active",
            )
        root = Path(env.document_root or ".")
        if not root.is_dir():
            raise AppException("Document root missing.")
        try:
            resolved = root.resolve(strict=True)
        except OSError as exc:
            raise AppException("Document root is not usable.") from exc
        command = str(job.get("command") or "")
        validate_command(command, domain=env.domain)
        username = self._require_tenant_unix_user(env)
        started = datetime.now(UTC)
        try:
            argv = self._build_argv(env, command)
        except AppException as exc:
            job["last_run_at"] = started.isoformat()
            job["last_status"] = "error"
            job["last_exit_code"] = -1
            job["last_output"] = str(exc)[:1000]
            job["last_execution_user"] = None
            job["last_failure_reason"] = getattr(exc, "code", None) or "cron_rejected"
            self._save(env, jobs)
            raise

        run_env = {
            "PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
            "HOME": str(resolved),
            "IFNOTUS_ENV_ID": str(env.id),
            "IFNOTUS_DOMAIN": env.domain or "",
            "IFNOTUS_UNIX_USER": username,
            "USER": username,
            "LOGNAME": username,
        }
        failure_reason: str | None = None
        try:
            proc = subprocess.run(
                argv,
                cwd=str(resolved),
                capture_output=True,
                text=True,
                timeout=_RUN_TIMEOUT_SECONDS,
                check=False,
                env=run_env,
            )
            output = ((proc.stdout or "") + (proc.stderr or ""))[-4000:]
            status = "success" if proc.returncode == 0 else "failed"
            exit_code = proc.returncode
            if status != "success":
                failure_reason = f"exit_{exit_code}"
        except subprocess.TimeoutExpired:
            output = f"Job timed out after {_RUN_TIMEOUT_SECONDS} seconds."
            status = "timeout"
            exit_code = -1
            failure_reason = "timeout"
        except Exception as exc:  # noqa: BLE001
            output = str(exc)[:4000]
            status = "error"
            exit_code = -1
            failure_reason = "exception"

        runtime_ms = int((datetime.now(UTC) - started).total_seconds() * 1000)
        job["last_run_at"] = started.isoformat()
        job["last_status"] = status
        job["last_exit_code"] = exit_code
        job["last_output"] = output[-1000:]
        job["last_execution_user"] = username
        job["last_runtime_ms"] = runtime_ms
        job["last_failure_reason"] = failure_reason
        self._save(env, jobs)

        log_dir = self._log_dir(env)
        log_dir.mkdir(parents=True, exist_ok=True)
        log_file = log_dir / f"{job['id']}.log"
        try:
            with log_file.open("a", encoding="utf-8") as fh:
                fh.write(
                    f"\n--- {started.isoformat()} status={status} exit={exit_code} "
                    f"user={username} runtime_ms={runtime_ms} ---\n"
                )
                fh.write(output)
                fh.write("\n")
        except OSError:
            pass

        logger.info(
            "env_cron_ran",
            environment_id=str(env.id),
            job_id=job.get("id"),
            status=status,
            exit_code=exit_code,
            unix_user=username,
            runtime_ms=runtime_ms,
            failure_reason=failure_reason,
        )
        return job

    async def tick_all(self, *, limit_envs: int = 200) -> dict[str, Any]:
        """Run due jobs for active environments (called every minute by worker)."""
        now = datetime.now(UTC).replace(second=0, microsecond=0)
        rows = (
            await self._session.execute(
                select(CustomerEnvironment)
                .where(CustomerEnvironment.status == "active")
                .limit(limit_envs)
            )
        ).scalars().all()
        ran = 0
        failed = 0
        checked = 0
        skipped_interval = 0
        for env in rows:
            jobs = self._load(env)
            if not jobs:
                continue
            checked += 1
            from app.services.platform.tenant import TenantService

            plan = await TenantService(self._session).plan_for_environment(env)
            ent = entitlements_for_plan(plan)
            dirty = False
            for job in jobs:
                if not job.get("enabled"):
                    continue
                schedule = str(job.get("schedule") or "")
                estimated = estimate_min_interval_minutes(schedule)
                if estimated is not None and estimated < ent.min_interval_minutes:
                    skipped_interval += 1
                    continue
                if not schedule_matches(schedule, now):
                    continue
                last = job.get("last_run_at")
                if last:
                    try:
                        last_dt = datetime.fromisoformat(str(last).replace("Z", "+00:00"))
                        if last_dt.tzinfo is None:
                            last_dt = last_dt.replace(tzinfo=UTC)
                        if abs((now - last_dt.replace(second=0, microsecond=0)).total_seconds()) < 30:
                            continue
                    except ValueError:
                        pass
                try:
                    self._execute(env, job, jobs)
                    dirty = True
                    if job.get("last_status") == "success":
                        ran += 1
                    else:
                        failed += 1
                except Exception as exc:  # noqa: BLE001
                    failed += 1
                    logger.warning("env_cron_tick_job_failed", error=str(exc), env=str(env.id))
            if dirty:
                self._save(env, jobs)
        return {
            "checked_envs": checked,
            "ran": ran,
            "failed": failed,
            "skipped_interval": skipped_interval,
            "at": now.isoformat(),
        }
