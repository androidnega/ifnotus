"""Per-environment cron jobs for customer sites (jailed to document root)."""

from __future__ import annotations

import json
import re
import shlex
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.exceptions import AppException, NotFoundError, ValidationError
from app.core.logging import get_logger
from app.models.platform import CustomerEnvironment

logger = get_logger(__name__)

_SCHEDULE_RE = re.compile(
    r"^(\S+)\s+(\S+)\s+(\S+)\s+(\S+)\s+(\S+)$"
)
_MAX_JOBS = 20
_MAX_COMMAND_LEN = 500
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
        "artisan",  # rare as binary; usually php artisan
    }
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
    # cron weekday: 0-7 Sunday=0 or 7
    wd = when.weekday() + 1  # Mon=1 … Sun=7
    if wd == 7:
        cron_wd = 0
    else:
        cron_wd = wd
    return (
        _cron_field_matches(minute, when.minute, minimum=0, maximum=59)
        and _cron_field_matches(hour, when.hour, minimum=0, maximum=23)
        and _cron_field_matches(day, when.day, minimum=1, maximum=31)
        and _cron_field_matches(month, when.month, minimum=1, maximum=12)
        and (
            _cron_field_matches(weekday, cron_wd, minimum=0, maximum=7)
            or _cron_field_matches(weekday, wd % 7, minimum=0, maximum=7)
        )
    )


def validate_schedule(schedule: str) -> str:
    schedule = " ".join(schedule.split())
    if not _SCHEDULE_RE.match(schedule):
        raise ValidationError(
            "Schedule must be a 5-field cron expression, e.g. */15 * * * *",
            code="invalid_cron_schedule",
        )
    # Smoke-test fields with current time matcher internals
    now = datetime.now(UTC)
    try:
        schedule_matches(schedule, now)
    except Exception as exc:  # noqa: BLE001
        raise ValidationError(f"Invalid cron schedule: {exc}", code="invalid_cron_schedule") from exc
    return schedule


def validate_command(command: str, *, domain: str | None = None) -> str:
    command = command.strip()
    if not command:
        raise ValidationError("Command is required.")
    if len(command) > _MAX_COMMAND_LEN:
        raise ValidationError("Command is too long.")
    forbidden = ("`", "$(", "${", "\n", "\r", ">>", ">", "<", "&&", "||", ";", "|")
    # Allow simple pipes? Safer to ban. Allow &&? Ban.
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
        # Relative path only — no absolute paths outside jail (executor uses cwd=docroot)
        if binary.startswith("/"):
            raise ValidationError("Absolute command paths are not allowed. Use a path under your site.")
    else:
        raise ValidationError(
            f"Command binary `{binary}` is not allowed. "
            "Use php, node, npm, curl, python3, composer, or a ./script in your site.",
            code="invalid_cron_command",
        )
    # curl/wget must target own domain when URL-like
    if binary in {"curl", "wget"} and domain:
        joined = " ".join(parts[1:])
        if "://" in joined and domain not in joined:
            raise ValidationError("curl/wget may only call your own domain.")
    return command


class EnvironmentCronService:
    def __init__(self, settings: Settings, session: AsyncSession) -> None:
        self._settings = settings
        self._session = session

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
    ) -> dict[str, Any]:
        if not env.document_root:
            raise AppException("Environment has no document root.")
        jobs = self._load(env)
        if len(jobs) >= _MAX_JOBS:
            raise ValidationError(f"Maximum {_MAX_JOBS} cron jobs per site.")
        schedule = validate_schedule(schedule)
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
    ) -> dict[str, Any]:
        jobs = self._load(env)
        for job in jobs:
            if job.get("id") != job_id:
                continue
            if schedule is not None:
                job["schedule"] = validate_schedule(schedule)
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
        jobs = self._load(env)
        for job in jobs:
            if job.get("id") == job_id:
                return self._execute(env, job, jobs)
        raise NotFoundError("Cron job not found.")

    def _execute(
        self,
        env: CustomerEnvironment,
        job: dict[str, Any],
        jobs: list[dict[str, Any]],
    ) -> dict[str, Any]:
        root = Path(env.document_root or ".")
        if not root.is_dir():
            raise AppException("Document root missing.")
        command = str(job.get("command") or "")
        validate_command(command, domain=env.domain)
        started = datetime.now(UTC)
        try:
            proc = subprocess.run(
                ["bash", "-lc", command],
                cwd=str(root),
                capture_output=True,
                text=True,
                timeout=300,
                check=False,
                env={
                    "PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
                    "HOME": str(root),
                    "IFNOTUS_ENV_ID": str(env.id),
                    "IFNOTUS_DOMAIN": env.domain or "",
                },
            )
            output = ((proc.stdout or "") + (proc.stderr or ""))[-4000:]
            status = "success" if proc.returncode == 0 else "failed"
            exit_code = proc.returncode
        except subprocess.TimeoutExpired:
            output = "Job timed out after 300 seconds."
            status = "timeout"
            exit_code = -1
        except Exception as exc:  # noqa: BLE001
            output = str(exc)[:4000]
            status = "error"
            exit_code = -1

        job["last_run_at"] = started.isoformat()
        job["last_status"] = status
        job["last_exit_code"] = exit_code
        job["last_output"] = output[-1000:]
        self._save(env, jobs)

        log_dir = self._log_dir(env)
        log_dir.mkdir(parents=True, exist_ok=True)
        log_file = log_dir / f"{job['id']}.log"
        try:
            with log_file.open("a", encoding="utf-8") as fh:
                fh.write(f"\n--- {started.isoformat()} status={status} exit={exit_code} ---\n")
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
        for env in rows:
            jobs = self._load(env)
            if not jobs:
                continue
            checked += 1
            dirty = False
            for job in jobs:
                if not job.get("enabled"):
                    continue
                schedule = str(job.get("schedule") or "")
                if not schedule_matches(schedule, now):
                    continue
                # Skip if already ran in this minute
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
        return {"checked_envs": checked, "ran": ran, "failed": failed, "at": now.isoformat()}
