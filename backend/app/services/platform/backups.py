"""Customer environment backup + restore (files archive + optional DB dump)."""

from __future__ import annotations

import hashlib
import json
import shutil
import tarfile
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.exceptions import AppException, NotFoundError, ValidationError
from app.core.logging import get_logger
from app.models.platform import (
    CustomerEnvironment,
    EnvironmentBackup,
    PlatformAuditLog,
    PlatformJob,
)
from app.services.hosting.databases import DatabaseManagerService
from app.services.platform.enqueue import enqueue_task
from app.services.platform.notifications import NotificationService

logger = get_logger(__name__)


class EnvironmentBackupService:
    def __init__(self, settings: Settings, session: AsyncSession) -> None:
        self._settings = settings
        self._session = session
        self._db = DatabaseManagerService(settings)

    def _backup_dir(self, customer_id: UUID) -> Path:
        path = Path(self._settings.operations_backup_dir) / "customers" / str(customer_id)
        path.mkdir(parents=True, exist_ok=True)
        return path

    async def get_owned_backup(
        self, customer_id: UUID, environment_id: UUID, backup_id: UUID
    ) -> EnvironmentBackup:
        result = await self._session.execute(
            select(EnvironmentBackup).where(
                EnvironmentBackup.id == backup_id,
                EnvironmentBackup.customer_id == customer_id,
                EnvironmentBackup.environment_id == environment_id,
            )
        )
        row = result.scalar_one_or_none()
        if row is None:
            raise NotFoundError("Backup not found.")
        return row

    async def list_backups(
        self, customer_id: UUID, environment_id: UUID
    ) -> list[EnvironmentBackup]:
        result = await self._session.execute(
            select(EnvironmentBackup)
            .where(
                EnvironmentBackup.customer_id == customer_id,
                EnvironmentBackup.environment_id == environment_id,
            )
            .order_by(EnvironmentBackup.created_at.desc())
            .limit(100)
        )
        return list(result.scalars().all())

    async def queue_backup(
        self,
        customer_id: UUID,
        environment_id: UUID,
        *,
        reason: str = "manual",
    ) -> EnvironmentBackup:
        env = await self._session.get(CustomerEnvironment, environment_id)
        if env is None or env.customer_id != customer_id:
            raise NotFoundError("Environment not found.")
        if env.status == "terminated":
            raise AppException("Cannot back up a terminated environment.")
        if not env.document_root:
            raise AppException("Environment has no document root.")

        row = EnvironmentBackup(
            customer_id=customer_id,
            environment_id=environment_id,
            filename="",
            backup_type="full",
            status="pending",
        )
        self._session.add(row)
        await self._session.flush()

        job = PlatformJob(
            job_type="backup_environment",
            customer_id=customer_id,
            environment_id=environment_id,
            status="pending",
            payload={
                "backup_id": str(row.id),
                "environment_id": str(environment_id),
                "reason": reason,
            },
        )
        self._session.add(job)
        await self._session.flush()

        task_id = await enqueue_task(
            self._settings,
            "backup_environment",
            {
                "backup_id": str(row.id),
                "environment_id": str(environment_id),
                "job_id": str(job.id),
                "reason": reason,
            },
        )
        if task_id:
            job.status = "queued"
            row.status = "queued"
        else:
            # Inline fallback when Redis is down
            await self.run_backup(row.id)
        await self._session.flush()
        return row

    async def queue_restore(
        self,
        customer_id: UUID,
        environment_id: UUID,
        backup_id: UUID,
    ) -> PlatformJob:
        env = await self._session.get(CustomerEnvironment, environment_id)
        if env is None or env.customer_id != customer_id:
            raise NotFoundError("Environment not found.")
        if env.status == "terminated":
            raise AppException("Cannot restore into a terminated environment.")
        backup = await self.get_owned_backup(customer_id, environment_id, backup_id)
        if backup.status != "success":
            raise ValidationError("Only successful backups can be restored.")
        if not backup.filename or not Path(backup.filename).exists():
            raise AppException("Backup archive file is missing on disk.")

        job = PlatformJob(
            job_type="restore_environment_backup",
            customer_id=customer_id,
            environment_id=environment_id,
            status="pending",
            payload={
                "backup_id": str(backup.id),
                "environment_id": str(environment_id),
            },
        )
        self._session.add(job)
        await self._session.flush()

        task_id = await enqueue_task(
            self._settings,
            "restore_environment_backup",
            {
                "backup_id": str(backup.id),
                "environment_id": str(environment_id),
                "job_id": str(job.id),
            },
        )
        if task_id:
            job.status = "queued"
        else:
            await self.run_restore(backup.id, environment_id)
            job.status = "success"
            job.completed_at = datetime.now(UTC)
        await self._session.flush()
        return job

    async def run_backup(self, backup_id: UUID) -> EnvironmentBackup:
        backup = await self._session.get(EnvironmentBackup, backup_id)
        if backup is None:
            raise NotFoundError("Backup not found.")
        env = await self._session.get(CustomerEnvironment, backup.environment_id)
        if env is None:
            backup.status = "failed"
            await self._fail(backup, env=None, error="Environment missing")
            raise AppException("Environment missing for backup.")

        backup.status = "running"
        await self._session.flush()

        try:
            archive_path, checksum, size, meta = await self._build_archive(env)
            backup.filename = str(archive_path)
            backup.checksum = checksum
            backup.file_size = size
            backup.status = "success"
            backup.verified_at = datetime.now(UTC)
            self._session.add(
                PlatformAuditLog(
                    customer_id=backup.customer_id,
                    action="environment.backup",
                    target_type="backup",
                    target_id=str(backup.id),
                    result="success",
                    metadata_json=meta,
                )
            )
            await self._prune_old(backup.customer_id, backup.environment_id)
            await self._session.flush()
            return backup
        except Exception as exc:  # noqa: BLE001
            logger.exception("backup_failed", backup_id=str(backup_id))
            backup.status = "failed"
            # Worker commits failure notify after rollback of this session when queued;
            # for inline fallback, flush notify here.
            await self._fail(backup, env=env, error=str(exc))
            raise

    async def run_restore(self, backup_id: UUID, environment_id: UUID) -> dict:
        backup = await self._session.get(EnvironmentBackup, backup_id)
        env = await self._session.get(CustomerEnvironment, environment_id)
        if backup is None or env is None:
            raise NotFoundError("Backup or environment not found.")
        if backup.environment_id != env.id:
            raise AppException("Backup does not belong to this environment.")
        archive = Path(backup.filename)
        if not archive.exists():
            raise AppException("Backup archive missing on disk.")
        if not env.document_root:
            raise AppException("Environment has no document root.")

        meta = await self._extract_archive(archive, Path(env.document_root), env)
        await NotificationService(self._session, self._settings).notify(
            env.customer_id,
            title="Backup restored",
            body=f"Restored {env.domain or env.id} from backup {backup.id}.",
            kind="backup",
            deliver=False,
        )
        self._session.add(
            PlatformAuditLog(
                customer_id=env.customer_id,
                action="environment.backup_restore",
                target_type="backup",
                target_id=str(backup.id),
                result="success",
                metadata_json=meta,
            )
        )
        await self._session.flush()
        return meta

    async def enqueue_daily(self) -> dict:
        """Queue backups for active environments that lack a successful backup today."""
        today = datetime.now(UTC).date()
        result = await self._session.execute(
            select(CustomerEnvironment).where(CustomerEnvironment.status == "active")
        )
        envs = list(result.scalars().all())
        queued = 0
        skipped = 0
        for env in envs:
            recent = await self._session.execute(
                select(EnvironmentBackup)
                .where(
                    EnvironmentBackup.environment_id == env.id,
                    EnvironmentBackup.status.in_(["success", "queued", "running", "pending"]),
                )
                .order_by(EnvironmentBackup.created_at.desc())
                .limit(5)
            )
            rows = list(recent.scalars().all())
            already = False
            for row in rows:
                created = row.created_at
                if created is None:
                    continue
                if created.tzinfo is None:
                    created = created.replace(tzinfo=UTC)
                if created.date() == today and row.status in {
                    "success",
                    "queued",
                    "running",
                    "pending",
                }:
                    already = True
                    break
            if already:
                skipped += 1
                continue
            await self.queue_backup(env.customer_id, env.id, reason="daily")
            queued += 1
        await self._session.flush()
        platform = self.dump_platform_postgres()
        return {"queued": queued, "skipped": skipped, "active": len(envs), "platform": platform}

    def dump_platform_postgres(self) -> dict:
        """Daily dump of the IFNOTUS database onto the host backup path (copy off-box separately)."""
        import os
        import subprocess

        dest_dir = Path(self._settings.platform_backup_dir)
        try:
            dest_dir.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            logger.warning("platform_backup_dir_failed", error=str(exc))
            return {"ok": False, "error": "mkdir"}
        stamp = datetime.now(UTC).strftime("%Y%m%d")
        dest = dest_dir / f"ifnotus-{stamp}.sql.gz"
        if dest.exists() and dest.stat().st_size > 0:
            offsite = self._run_offsite_sync(dest)
            return {"ok": True, "skipped": True, "path": str(dest), "offsite": offsite}
        try:
            from sqlalchemy.engine.url import make_url

            url = make_url(self._settings.database_url_sync().replace("postgresql+psycopg2://", "postgresql://"))
        except Exception as exc:  # noqa: BLE001
            logger.warning("platform_backup_url_failed", error=str(exc))
            return {"ok": False, "error": "url"}
        env = os.environ.copy()
        if url.password:
            env["PGPASSWORD"] = url.password
        dump = subprocess.run(
            [
                "pg_dump",
                "-h",
                url.host or "127.0.0.1",
                "-p",
                str(url.port or 5432),
                "-U",
                url.username or "ifnotus",
                "-d",
                url.database or "ifnotus",
                "--no-owner",
                "--no-acl",
            ],
            capture_output=True,
            env=env,
            check=False,
            timeout=300,
        )
        if dump.returncode != 0:
            logger.warning("platform_pg_dump_failed", error=(dump.stderr or b"")[-400:].decode("utf-8", "replace"))
            return {"ok": False, "error": "pg_dump"}
        import gzip

        dest.write_bytes(gzip.compress(dump.stdout))
        logger.info("platform_postgres_dumped", path=str(dest), bytes=dest.stat().st_size)
        self._prune_platform_dumps(dest_dir, keep=7)
        offsite = self._run_offsite_sync(dest)
        return {"ok": True, "path": str(dest), "bytes": dest.stat().st_size, "offsite": offsite}

    def _run_offsite_sync(self, dump_path: Path) -> dict:
        """Copy dumps off this disk. Same-disk copies are not disaster recovery."""
        import os
        import shlex
        import subprocess

        raw = (getattr(self._settings, "platform_backup_offsite_cmd", None) or "").strip()
        if not raw:
            return {
                "ok": False,
                "skipped": True,
                "reason": "PLATFORM_BACKUP_OFFSITE_CMD not set — dumps stay on this VPS only.",
            }
        cmd = raw.replace("{path}", str(dump_path)).replace(
            "{dir}", str(dump_path.parent)
        )
        try:
            proc = subprocess.run(
                cmd if os.name == "nt" else ["bash", "-lc", cmd],
                capture_output=True,
                text=True,
                timeout=600,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            logger.warning("platform_backup_offsite_failed", error=str(exc))
            return {"ok": False, "error": str(exc)}
        if proc.returncode != 0:
            err = (proc.stderr or proc.stdout or "")[-400:]
            logger.warning("platform_backup_offsite_failed", error=err, cmd=shlex.quote(cmd[:120]))
            return {"ok": False, "error": err or "offsite_cmd_failed"}
        logger.info("platform_backup_offsite_ok", path=str(dump_path))
        return {"ok": True}

    def _prune_platform_dumps(self, dest_dir: Path, *, keep: int) -> None:
        files = sorted(dest_dir.glob("ifnotus-*.sql.gz"), key=lambda p: p.stat().st_mtime, reverse=True)
        for old in files[keep:]:
            try:
                old.unlink()
            except OSError:
                pass

    async def _fail(
        self,
        backup: EnvironmentBackup,
        *,
        env: CustomerEnvironment | None,
        error: str,
    ) -> None:
        domain = (env.domain if env else None) or str(backup.environment_id)
        await NotificationService(self._session, self._settings).notify(
            backup.customer_id,
            title="Backup failed",
            body=f"Daily/manual backup for {domain} failed: {error[:400]}",
            kind="backup",
        )
        self._session.add(
            PlatformAuditLog(
                customer_id=backup.customer_id,
                action="environment.backup",
                target_type="backup",
                target_id=str(backup.id),
                result="failed",
                metadata_json={"error": error[:1000]},
            )
        )
        await self._session.flush()

    async def _build_archive(self, env: CustomerEnvironment) -> tuple[Path, str, int, dict]:
        doc = Path(env.document_root or "").resolve()
        if not doc.exists() or not doc.is_dir():
            raise AppException(f"Document root missing: {doc}")

        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        out_dir = self._backup_dir(env.customer_id)
        archive = out_dir / f"{env.id}_{stamp}.tar.gz"

        with tempfile.TemporaryDirectory(prefix="ifnotus-bak-") as tmp:
            stage = Path(tmp)
            files_dir = stage / "files"
            files_dir.mkdir(parents=True)
            # Copy tree (follow_symlinks=False to avoid escaping jail)
            for child in doc.iterdir():
                dest = files_dir / child.name
                if child.is_dir() and not child.is_symlink():
                    shutil.copytree(child, dest, symlinks=False, ignore_dangling_symlinks=True)
                elif child.is_file() and not child.is_symlink():
                    shutil.copy2(child, dest)

            db_meta: dict | None = None
            if env.db_engine and env.db_name:
                db_meta = self._dump_database(env, stage)

            manifest = {
                "environment_id": str(env.id),
                "customer_id": str(env.customer_id),
                "domain": env.domain,
                "document_root": str(doc),
                "created_at": datetime.now(UTC).isoformat(),
                "database": db_meta,
            }
            (stage / "manifest.json").write_text(
                json.dumps(manifest, indent=2), encoding="utf-8"
            )

            with tarfile.open(archive, "w:gz") as tar:
                tar.add(stage / "manifest.json", arcname="manifest.json")
                tar.add(files_dir, arcname="files")
                for name in ("database.sql", "database.sqlite3", "database.dump"):
                    path = stage / name
                    if path.exists():
                        tar.add(path, arcname=name)

        checksum = self._sha256(archive)
        size = archive.stat().st_size
        meta = {
            "filename": str(archive),
            "checksum": checksum,
            "file_size": size,
            "includes_database": bool(db_meta),
            "domain": env.domain,
        }
        return archive, checksum, size, meta

    def _dump_database(self, env: CustomerEnvironment, stage: Path) -> dict:
        engine = (env.db_engine or "").lower()
        name = env.db_name or ""
        if engine == "sqlite":
            # Prefer path under document_root / registry path via dump helper
            path = None
            if env.db_registry_id:
                items = self._db._read_registry()
                match = next((i for i in items if i.get("id") == str(env.db_registry_id)), None)
                if match:
                    path = match.get("path")
            if not path:
                # Common provision path
                candidate = Path(env.document_root or ".") / "data"
                if candidate.is_dir():
                    sqlite_files = list(candidate.glob("*.sqlite3"))
                    if sqlite_files:
                        path = str(sqlite_files[0])
            if not path:
                raise AppException("SQLite path not found for environment database.")
            dest = stage / "database.sqlite3"
            shutil.copy2(path, dest)
            return {"engine": "sqlite", "name": name, "file": "database.sqlite3", "source": path}

        # Use host dump tools (postgres/mysql) into staging
        record = self._db._create_backup(
            engine=engine,
            name=name,
            path=None,
            kind="environment",
        )
        src = Path(str(record["path"]))
        if engine in {"postgresql", "mysql"}:
            dest = stage / "database.sql"
        else:
            dest = stage / "database.dump"
        shutil.copy2(src, dest)
        return {
            "engine": engine,
            "name": name,
            "file": dest.name,
            "managed_backup_id": record.get("id"),
        }

    async def _extract_archive(
        self, archive: Path, document_root: Path, env: CustomerEnvironment
    ) -> dict:
        document_root.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="ifnotus-restore-") as tmp:
            stage = Path(tmp)
            with tarfile.open(archive, "r:gz") as tar:
                # Safe extract — members must stay under stage
                for member in tar.getmembers():
                    target = (stage / member.name).resolve()
                    if not str(target).startswith(str(stage.resolve())):
                        raise AppException("Unsafe path in backup archive.")
                try:
                    tar.extractall(stage, filter="data")  # type: ignore[call-arg]
                except TypeError:
                    tar.extractall(stage)

            manifest_path = stage / "manifest.json"
            manifest = {}
            if manifest_path.exists():
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

            files_dir = stage / "files"
            if files_dir.is_dir():
                # Replace document root contents
                for child in list(document_root.iterdir()):
                    if child.is_dir() and not child.is_symlink():
                        shutil.rmtree(child)
                    else:
                        child.unlink(missing_ok=True)
                for child in files_dir.iterdir():
                    dest = document_root / child.name
                    if child.is_dir():
                        shutil.copytree(child, dest, symlinks=False)
                    else:
                        shutil.copy2(child, dest)

            db_info = (manifest.get("database") or {}) if isinstance(manifest, dict) else {}
            engine = (db_info.get("engine") or env.db_engine or "").lower()
            db_name = db_info.get("name") or env.db_name
            sql_file = stage / "database.sql"
            sqlite_file = stage / "database.sqlite3"
            if engine == "sqlite" and sqlite_file.exists():
                path = None
                if env.db_registry_id:
                    items = self._db._read_registry()
                    match = next(
                        (i for i in items if i.get("id") == str(env.db_registry_id)), None
                    )
                    if match:
                        path = match.get("path")
                if not path:
                    path = str(document_root / "data" / f"{db_name or 'db'}.sqlite3")
                Path(path).parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(sqlite_file, path)
                manifest["restored_database"] = {"engine": "sqlite", "path": path}
            elif engine in {"postgresql", "mysql"} and sql_file.exists() and db_name:
                self._db._restore_engine_db(
                    engine=engine,
                    name=db_name,
                    path=None,
                    source=sql_file,
                    create_if_missing=True,
                )
                manifest["restored_database"] = {"engine": engine, "name": db_name}

            return {
                "archive": str(archive),
                "document_root": str(document_root),
                "manifest": manifest,
            }

    async def _prune_old(self, customer_id: UUID, environment_id: UUID) -> None:
        keep = int(getattr(self._settings, "backup_retention_count", 7) or 7)
        result = await self._session.execute(
            select(EnvironmentBackup)
            .where(
                EnvironmentBackup.customer_id == customer_id,
                EnvironmentBackup.environment_id == environment_id,
                EnvironmentBackup.status == "success",
            )
            .order_by(EnvironmentBackup.created_at.desc())
        )
        rows = list(result.scalars().all())
        for old in rows[keep:]:
            try:
                if old.filename:
                    Path(old.filename).unlink(missing_ok=True)
            except OSError:
                pass
            await self._session.delete(old)

    @staticmethod
    def _sha256(path: Path) -> str:
        h = hashlib.sha256()
        with path.open("rb") as fh:
            while True:
                chunk = fh.read(1024 * 1024)
                if not chunk:
                    break
                h.update(chunk)
        return h.hexdigest()
