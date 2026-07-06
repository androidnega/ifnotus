"""Platform-level operations service."""

from __future__ import annotations

import os
import re
import shutil
import smtplib
import ssl
from datetime import UTC, datetime
from email.message import EmailMessage
from pathlib import Path

import psutil

from app.core.config import Settings
from app.core.exceptions import AppException
from app.repositories.applications import ApplicationRepository
from app.schemas.health import HealthStatus
from app.schemas.operations import (
    BackupEntry,
    BackupsResponse,
    CronJob,
    CronResponse,
    DatabaseResponse,
    DatabaseStatus,
    EnvVariable,
    EnvironmentResponse,
    FileEntry,
    FileListResponse,
    OperationResult,
    OperationsOverview,
    QueueStatus,
    StorageResponse,
    StorageVolume,
)
from app.services.applications.readers.ssl import SSLReader
from app.services.monitoring.subprocess_util import resolve_binary, run_command
from app.workers.queue import TaskQueue


class OperationsService:
    """Host and platform operations."""

    def __init__(self, settings: Settings, task_queue: TaskQueue | None = None) -> None:
        self._settings = settings
        self._queue = task_queue
        self._apps = ApplicationRepository(settings)
        self._ssl = SSLReader()

    async def overview(self) -> OperationsOverview:
        apps = self._apps.list_all()
        backups = await self.list_backups()
        cron = await self.list_cron()
        depth = 0
        if self._queue:
            depth = await self._queue.get_queue_depth()

        nginx = resolve_binary("nginx", self._settings.nginx_binary)

        return OperationsOverview(
            timestamp=datetime.now(UTC),
            nginx_available=nginx is not None,
            worker_queue_depth=depth,
            backup_count=len(backups.backups),
            cron_job_count=len(cron.jobs),
            applications_total=len(apps),
            applications_enabled=sum(1 for a in apps if a.enabled),
        )

    async def platform_environment(self, *, reveal: bool = False) -> EnvironmentResponse:
        secret_keys = {
            "SECRET_KEY",
            "DATABASE_URL",
            "REDIS_URL",
            "SMTP_PASSWORD",
            "MYSQL_URL",
        }
        variables: list[EnvVariable] = []
        for key, value in self._settings.model_dump().items():
            env_key = key.upper()
            is_secret = any(s in env_key for s in ("SECRET", "PASSWORD", "URL", "KEY", "TOKEN"))
            if env_key in secret_keys:
                is_secret = True
            variables.append(
                EnvVariable(
                    key=env_key,
                    value=str(value) if reveal and not is_secret else ("***" if is_secret else str(value)),
                    secret=is_secret,
                    source="settings",
                )
            )
        return EnvironmentResponse(
            timestamp=datetime.now(UTC),
            variables=sorted(variables, key=lambda v: v.key),
            revealed=reveal,
        )

    async def test_smtp(self, to_email: str, subject: str, body: str) -> OperationResult:
        host = self._settings.smtp_host
        if not host:
            return OperationResult(
                success=False,
                message="SMTP not configured. Set SMTP_HOST and related env vars.",
            )

        msg = EmailMessage()
        msg["Subject"] = subject
        msg["From"] = self._settings.smtp_from or self._settings.smtp_username or "noreply@ifnotus.local"
        msg["To"] = to_email
        msg.set_content(body)

        try:
            if self._settings.smtp_use_tls:
                context = ssl.create_default_context()
                with smtplib.SMTP(host, self._settings.smtp_port, timeout=30) as server:
                    server.starttls(context=context)
                    if self._settings.smtp_username and self._settings.smtp_password:
                        server.login(self._settings.smtp_username, self._settings.smtp_password)
                    server.send_message(msg)
            else:
                with smtplib.SMTP(host, self._settings.smtp_port, timeout=30) as server:
                    if self._settings.smtp_username and self._settings.smtp_password:
                        server.login(self._settings.smtp_username, self._settings.smtp_password)
                    server.send_message(msg)
        except Exception as exc:
            return OperationResult(success=False, message=f"SMTP test failed: {exc}")

        return OperationResult(success=True, message=f"Test email sent to {to_email}.")

    async def restart_nginx(self) -> OperationResult:
        nginx = resolve_binary("nginx", self._settings.nginx_binary)
        systemctl = resolve_binary("systemctl")

        if systemctl:
            code, stdout, stderr = await run_command(systemctl, "reload", "nginx", timeout=30)
            if code == 0:
                return OperationResult(success=True, message="Nginx reloaded via systemctl.")

        if nginx:
            code, stdout, stderr = await run_command(nginx, "-s", "reload", timeout=30)
            if code == 0:
                return OperationResult(success=True, message="Nginx reloaded.")

        return OperationResult(success=False, message=stderr or stdout or "Failed to reload nginx.")

    async def restart_worker(self) -> OperationResult:
        unit = self._settings.worker_service_name
        systemctl = resolve_binary("systemctl")

        if unit and systemctl:
            code, stdout, stderr = await run_command(systemctl, "restart", unit, timeout=60)
            if code == 0:
                return OperationResult(success=True, message=f"Worker service {unit} restarted.")
            return OperationResult(success=False, message=stderr or stdout)

        if self._queue:
            task_id = await self._queue.enqueue(
                "worker.ping",
                {"action": "restart_requested"},
                queue="control",
            )
            return OperationResult(
                success=True,
                message="Worker restart signal enqueued (no systemd unit configured).",
                task_id=str(task_id),
            )

        return OperationResult(
            success=False,
            message="Set WORKER_SERVICE_NAME for systemd restart or ensure Redis queue is available.",
        )

    async def queue_status(self) -> list[QueueStatus]:
        if not self._queue:
            return []
        depth = await self._queue.get_queue_depth()
        return [
            QueueStatus(queue="default", depth=depth),
        ]

    async def list_backups(self) -> BackupsResponse:
        backup_root = Path(self._settings.operations_backup_dir)
        if not backup_root.is_absolute():
            backup_root = Path.cwd() / backup_root

        entries: list[BackupEntry] = []
        if backup_root.exists():
            for path in sorted(backup_root.rglob("*"), reverse=True):
                if not path.is_file():
                    continue
                stat = path.stat()
                entries.append(
                    BackupEntry(
                        id=path.stem,
                        name=path.name,
                        path=str(path),
                        size_bytes=stat.st_size,
                        created=datetime.fromtimestamp(stat.st_mtime, tz=UTC),
                    )
                )

        for app in self._apps.list_all():
            app_backup = Path(app.root_path) / ".ifnotus" / "backups"
            if app_backup.exists():
                for path in sorted(app_backup.glob("*"), reverse=True):
                    if path.is_file():
                        stat = path.stat()
                        entries.append(
                            BackupEntry(
                                id=f"{app.id}-{path.stem}",
                                name=path.name,
                                path=str(path),
                                size_bytes=stat.st_size,
                                created=datetime.fromtimestamp(stat.st_mtime, tz=UTC),
                                application_id=app.id,
                            )
                        )

        return BackupsResponse(timestamp=datetime.now(UTC), backups=entries[:100])

    async def create_backup(self, name: str | None = None) -> OperationResult:
        backup_root = Path(self._settings.operations_backup_dir)
        if not backup_root.is_absolute():
            backup_root = Path.cwd() / backup_root
        backup_root.mkdir(parents=True, exist_ok=True)

        stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
        filename = name or f"platform-backup-{stamp}.json"
        path = backup_root / filename

        overview = await self.overview()
        path.write_text(
            overview.model_dump_json(indent=2),
            encoding="utf-8",
        )
        return OperationResult(success=True, message=f"Backup created at {path}", details={"path": str(path)})

    async def list_cron(self) -> CronResponse:
        jobs: list[CronJob] = []
        idx = 0

        cron_dirs = [Path("/etc/cron.d"), Path("/etc/cron.daily")]
        for cron_dir in cron_dirs:
            if not cron_dir.exists():
                continue
            for path in cron_dir.iterdir():
                if path.is_file() and not path.name.startswith("."):
                    jobs.append(
                        CronJob(
                            id=f"cron-{idx}",
                            schedule="system",
                            command=path.name,
                            source=str(cron_dir),
                            enabled=True,
                        )
                    )
                    idx += 1

        code, stdout, _ = await run_command("crontab", "-l", timeout=10)
        if code == 0 and stdout:
            for line in stdout.splitlines():
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                parts = line.split(None, 5)
                if len(parts) >= 6:
                    schedule = " ".join(parts[:5])
                    command = parts[5]
                else:
                    schedule = "unknown"
                    command = line
                jobs.append(
                    CronJob(
                        id=f"user-{idx}",
                        schedule=schedule,
                        command=command,
                        source="crontab",
                        user=os.environ.get("USER"),
                        enabled=True,
                    )
                )
                idx += 1

        return CronResponse(timestamp=datetime.now(UTC), jobs=jobs)

    async def list_files(self, path: str = ".", *, app_id: str | None = None) -> FileListResponse:
        base = self._safe_base(app_id)
        target = self._safe_path(base, path)

        if not target.exists():
            raise AppException(f"Path not found: {path}", code="not_found")

        entries: list[FileEntry] = []
        if target.is_dir():
            for child in sorted(target.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower())):
                if child.name.startswith(".") and child.name not in {".ifnotus"}:
                    continue
                stat = child.stat()
                rel = str(child.relative_to(base))
                entries.append(
                    FileEntry(
                        name=child.name,
                        path=rel,
                        is_dir=child.is_dir(),
                        size_bytes=None if child.is_dir() else stat.st_size,
                        modified=datetime.fromtimestamp(stat.st_mtime, tz=UTC),
                    )
                )

        parent = None
        if target != base:
            parent = str(target.parent.relative_to(base)) if target.parent != base else "."

        rel_path = str(target.relative_to(base)) if target != base else "."
        return FileListResponse(
            timestamp=datetime.now(UTC),
            path=rel_path,
            entries=entries,
            parent=parent,
        )

    async def storage_check(self) -> StorageResponse:
        volumes: list[StorageVolume] = []
        for part in psutil.disk_partitions(all=False):
            try:
                usage = psutil.disk_usage(part.mountpoint)
            except PermissionError:
                continue
            volumes.append(
                StorageVolume(
                    mount=part.mountpoint,
                    total_bytes=usage.total,
                    used_bytes=usage.used,
                    free_bytes=usage.free,
                    percent=usage.percent,
                )
            )
        return StorageResponse(timestamp=datetime.now(UTC), volumes=volumes)

    async def ssl_status(self) -> list[dict]:
        results = []
        for app in self._apps.list_all():
            ssl = await self._ssl.read(app.ssl.certificate, app.ssl.domain)
            results.append(
                {
                    "application_id": app.id,
                    "application_name": app.name,
                    "domain": app.ssl.domain or app.nginx.server_name,
                    "ssl": ssl.model_dump(),
                }
            )
        return results

    async def database_status(self) -> DatabaseResponse:
        databases: list[DatabaseStatus] = []

        db_url = str(self._settings.database_url)
        if "postgresql" in db_url:
            try:
                from app.services.monitoring.collectors.postgresql import PostgreSQLCollector

                collector = PostgreSQLCollector(self._settings)
                stats = await collector.collect()
                databases.append(
                    DatabaseStatus(
                        engine="postgresql",
                        status=HealthStatus.HEALTHY if stats.connected else HealthStatus.UNHEALTHY,
                        size_bytes=stats.memory_bytes,
                        connections=stats.connections,
                    )
                )
            except Exception as exc:
                databases.append(
                    DatabaseStatus(
                        engine="postgresql",
                        status=HealthStatus.UNHEALTHY,
                        message=str(exc),
                    )
                )

        redis_url = str(self._settings.redis_url)
        if redis_url:
            try:
                from app.services.monitoring.collectors.redis_collector import RedisCollector

                collector = RedisCollector(self._settings, None)
                stats = await collector.collect()
                databases.append(
                    DatabaseStatus(
                        engine="redis",
                        status=HealthStatus.HEALTHY if stats.connected else HealthStatus.UNHEALTHY,
                        connections=stats.connections,
                        size_bytes=stats.memory_bytes,
                    )
                )
            except Exception as exc:
                databases.append(
                    DatabaseStatus(
                        engine="redis",
                        status=HealthStatus.UNHEALTHY,
                        message=str(exc),
                    )
                )

        return DatabaseResponse(timestamp=datetime.now(UTC), databases=databases)

    async def database_action(self, action: str) -> OperationResult:
        action = action.lower()
        if action == "ping":
            resp = await self.database_status()
            ok = all(d.status == HealthStatus.HEALTHY for d in resp.databases)
            return OperationResult(
                success=ok,
                message="All databases reachable." if ok else "One or more databases unreachable.",
            )

        if action == "migrate":
            alembic = shutil.which("alembic")
            if not alembic:
                return OperationResult(success=False, message="alembic not found in PATH.")
            code, stdout, stderr = await run_command(alembic, "upgrade", "head", timeout=300)
            return OperationResult(
                success=code == 0,
                message=stdout or stderr or "Migration finished.",
            )

        return OperationResult(success=False, message=f"Unknown database action: {action}")

    def _safe_base(self, app_id: str | None) -> Path:
        if app_id:
            app = self._apps.get(app_id)
            root = Path(app.paths.root)
            if not root.is_absolute() and app.source_file:
                return (Path(app.source_file).parent / root).resolve()
            return root.resolve()
        return Path.cwd().resolve()

    def _safe_path(self, base: Path, path: str) -> Path:
        base = base.resolve()
        target = (base / path.lstrip("/")).resolve()
        if not str(target).startswith(str(base)):
            raise AppException("Path traversal denied.", code="forbidden")
        return target
