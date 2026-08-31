"""Create and manage SQLite, MySQL, PostgreSQL, and MongoDB databases on the host."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import os
import re
import secrets
import shutil
import sqlite3
import string
import subprocess
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from cryptography.fernet import Fernet, InvalidToken

from app.core.config import Settings
from app.core.exceptions import AppException, NotFoundError
from app.core.logging import get_logger
from app.schemas.databases import (
    DatabaseAdoptRequest,
    DatabaseBackupSchema,
    DatabaseCreateRequest,
    DatabaseCreatedResponse,
    DatabaseDropOptions,
    DatabaseListResponse,
    DatabaseLiveDropRequest,
    DatabasePasswordResponse,
    DatabaseRecordSchema,
    DatabaseRestoreRequest,
    EngineStatusSchema,
    LiveDatabaseSchema,
)
from app.schemas.operations import OperationResult

logger = get_logger(__name__)

SYSTEM_MYSQL = {"information_schema", "mysql", "performance_schema", "sys"}
SYSTEM_PG = {"postgres", "template0", "template1"}
DEFAULT_SQLITE_ROOT = Path("/srv/apps")


def mysql_user_grant_sql(
    *,
    username: str,
    password: str,
    database: str,
    allow_remote: bool,
    escape,
) -> list[str]:
    """Build MySQL CREATE USER / GRANT statements scoped by remote entitlement.

    Always creates ``user@localhost``. Only creates ``user@'%'`` when
    ``allow_remote`` is True (PHASE 38H).
    """
    u = escape(username)
    p = escape(password)
    db = database.replace("`", "``")
    sql = [
        f"CREATE USER IF NOT EXISTS '{u}'@'localhost' IDENTIFIED BY '{p}';",
        f"ALTER USER '{u}'@'localhost' IDENTIFIED BY '{p}';",
        f"GRANT ALL PRIVILEGES ON `{db}`.* TO '{u}'@'localhost';",
    ]
    if allow_remote:
        sql.append(f"CREATE USER IF NOT EXISTS '{u}'@'%' IDENTIFIED BY '{p}';")
        sql.append(f"ALTER USER '{u}'@'%' IDENTIFIED BY '{p}';")
        sql.append(f"GRANT ALL PRIVILEGES ON `{db}`.* TO '{u}'@'%';")
    sql.append("FLUSH PRIVILEGES;")
    return sql


def mysql_revoke_remote_sql(*, username: str, escape) -> list[str]:
    """Drop the remote ``user@'%'`` account if present (localhost-only repair)."""
    u = escape(username)
    return [
        f"DROP USER IF EXISTS '{u}'@'%';",
        "FLUSH PRIVILEGES;",
    ]


class DatabaseManagerService:
    """Host-level database provisioning for operators and SNR Dev."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._registry_path = Path(getattr(settings, "databases_registry_path", ".ifnotus/databases/registry.json")).resolve()
        self._sqlite_root = Path(getattr(settings, "databases_sqlite_root", str(DEFAULT_SQLITE_ROOT))).resolve()
        self._backup_root = Path(
            getattr(settings, "databases_backup_root", ".ifnotus/databases/backups")
        ).resolve()
        self._backup_index = self._backup_root / "index.json"

    # ── Encryption / registry ──────────────────────────────────────────────

    def _fernet(self) -> Fernet:
        digest = hashlib.sha256(self._settings.secret_key.encode("utf-8")).digest()
        return Fernet(base64.urlsafe_b64encode(digest))

    def _encrypt(self, value: str) -> str:
        return self._fernet().encrypt(value.encode("utf-8")).decode("utf-8")

    def _decrypt(self, value: str) -> str | None:
        try:
            return self._fernet().decrypt(value.encode("utf-8")).decode("utf-8")
        except (InvalidToken, ValueError):
            return None

    def _read_registry(self) -> list[dict[str, Any]]:
        if not self._registry_path.exists():
            return []
        try:
            data = json.loads(self._registry_path.read_text(encoding="utf-8"))
            items = data.get("databases") if isinstance(data, dict) else data
            return list(items) if isinstance(items, list) else []
        except (OSError, json.JSONDecodeError):
            return []

    def _write_registry(self, items: list[dict[str, Any]]) -> None:
        self._registry_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"databases": items, "updated_at": datetime.now(UTC).isoformat()}
        tmp = self._registry_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        tmp.replace(self._registry_path)

    @staticmethod
    def _mask_password(password: str | None) -> str | None:
        if not password:
            return None
        if len(password) <= 4:
            return "••••••••"
        return f"{password[:2]}…{password[-2:]}"

    def _record_to_schema(self, raw: dict[str, Any], *, include_uri_password: bool = False) -> DatabaseRecordSchema:
        password = None
        enc = raw.get("password_encrypted")
        if enc:
            password = self._decrypt(str(enc))
        uri = self._build_uri(
            engine=str(raw.get("engine") or ""),
            name=str(raw.get("name") or ""),
            username=raw.get("username"),
            password=password if include_uri_password else None,
            host=raw.get("host"),
            port=raw.get("port"),
            path=raw.get("path"),
            mask_password=not include_uri_password,
        )
        return DatabaseRecordSchema(
            id=str(raw.get("id")),
            engine=raw.get("engine"),  # type: ignore[arg-type]
            name=str(raw.get("name") or ""),
            username=raw.get("username"),
            host=raw.get("host"),
            port=raw.get("port"),
            path=raw.get("path"),
            connection_uri=uri,
            password_set=bool(enc),
            password_masked=self._mask_password(password),
            notes=raw.get("notes"),
            created_at=raw.get("created_at"),
            managed=True,
            size_bytes=raw.get("size_bytes"),
            table_count=raw.get("table_count"),
        )

    @staticmethod
    def _build_uri(
        *,
        engine: str,
        name: str,
        username: str | None,
        password: str | None,
        host: str | None,
        port: int | None,
        path: str | None,
        mask_password: bool = False,
    ) -> str | None:
        if engine == "sqlite":
            return f"sqlite:///{path}" if path else None
        pwd = "••••••••" if mask_password and password else (password or "")
        user = username or ""
        auth = f"{user}:{pwd}@" if user else ""
        if engine == "mysql":
            return f"mysql://{auth}{host or '127.0.0.1'}:{port or 3306}/{name}"
        if engine == "postgresql":
            return f"postgresql://{auth}{host or '127.0.0.1'}:{port or 5432}/{name}"
        if engine == "mongodb":
            return f"mongodb://{auth}{host or '127.0.0.1'}:{port or 27017}/{name}"
        return None

    # ── Public API ─────────────────────────────────────────────────────────

    async def overview(self) -> DatabaseListResponse:
        engines, live = await asyncio.gather(
            asyncio.to_thread(self._probe_engines),
            asyncio.to_thread(self._list_live),
        )
        counts = {
            (item.engine, item.name): item.table_count
            for item in live
            if item.table_count is not None
        }
        path_counts = {
            item.path: item.table_count
            for item in live
            if item.path and item.table_count is not None
        }
        managed_raw = self._read_registry()
        for raw in managed_raw:
            raw["table_count"] = (
                path_counts.get(raw.get("path"))
                if raw.get("engine") == "sqlite"
                else counts.get((raw.get("engine"), raw.get("name")))
            )
        managed = [self._record_to_schema(r) for r in managed_raw]
        return DatabaseListResponse(engines=engines, managed=managed, live=live)

    @staticmethod
    def _strong_password(length: int = 24) -> str:
        """Generate a password that satisfies typical MySQL validate_password MEDIUM policy."""
        alphabet_upper = string.ascii_uppercase
        alphabet_lower = string.ascii_lowercase
        alphabet_digits = string.digits
        alphabet_special = "!@#$%^&*-_=+"
        # Guarantee one of each class, then fill with a mixed pool.
        required = [
            secrets.choice(alphabet_upper),
            secrets.choice(alphabet_lower),
            secrets.choice(alphabet_digits),
            secrets.choice(alphabet_special),
        ]
        pool = alphabet_upper + alphabet_lower + alphabet_digits + alphabet_special
        required += [secrets.choice(pool) for _ in range(max(0, length - len(required)))]
        secrets.SystemRandom().shuffle(required)
        return "".join(required)

    async def create(self, body: DatabaseCreateRequest) -> DatabaseCreatedResponse:
        password = body.password
        username = body.username
        if body.engine == "sqlite":
            username = None
            password = None
        elif body.create_user:
            username = username or body.name
            password = password or self._strong_password()

        if body.engine == "sqlite":
            result = await asyncio.to_thread(self._create_sqlite, body)
        elif body.engine == "mysql":
            result = await asyncio.to_thread(self._create_mysql, body, username, password)
        elif body.engine == "postgresql":
            result = await asyncio.to_thread(self._create_postgresql, body, username, password)
        elif body.engine == "mongodb":
            result = await asyncio.to_thread(self._create_mongodb, body, username, password)
        else:
            raise AppException(f"Unsupported engine: {body.engine}", code="db_engine_unsupported")

        record = {
            "id": str(uuid.uuid4()),
            "engine": body.engine,
            "name": body.name if body.engine != "sqlite" else Path(result["path"]).stem,
            "username": username,
            "password_encrypted": self._encrypt(password) if password else None,
            "host": result.get("host"),
            "port": result.get("port"),
            "path": result.get("path"),
            "notes": body.notes,
            "created_at": datetime.now(UTC).isoformat(),
            "size_bytes": result.get("size_bytes"),
        }
        items = self._read_registry()
        items.append(record)
        self._write_registry(items)

        schema = self._record_to_schema(record, include_uri_password=False)
        uri_full = self._build_uri(
            engine=body.engine,
            name=record["name"],
            username=username,
            password=password,
            host=record.get("host"),
            port=record.get("port"),
            path=record.get("path"),
            mask_password=False,
        )
        return DatabaseCreatedResponse(
            message=result.get("message") or f"{body.engine} database created.",
            database=schema,
            password=password,
            connection_uri=uri_full,
            details={k: v for k, v in result.items() if k != "message"},
        )

    async def drop(self, db_id: str, body: DatabaseDropOptions | None = None) -> OperationResult:
        opts = body or DatabaseDropOptions()
        items = self._read_registry()
        match = next((i for i in items if i.get("id") == db_id), None)
        if not match:
            raise NotFoundError(f"Managed database {db_id} not found.")

        backup = await asyncio.to_thread(
            self._create_backup,
            engine=str(match.get("engine") or ""),
            name=str(match.get("name") or ""),
            path=match.get("path"),
            kind="pre_drop",
        )
        password = self._decrypt(str(match["password_encrypted"])) if match.get("password_encrypted") else None
        await asyncio.to_thread(self._drop_engine_db, match, opts, password)
        remaining = [i for i in items if i.get("id") != db_id]
        self._write_registry(remaining)
        return OperationResult(
            success=True,
            message=f"Dropped {match.get('engine')} database {match.get('name')}. Backup saved first.",
            details={
                "backup_id": backup["id"],
                "backup_filename": backup["filename"],
                "backup_size_bytes": backup.get("size_bytes"),
            },
        )

    async def reveal_password(self, db_id: str) -> DatabasePasswordResponse:
        items = self._read_registry()
        match = next((i for i in items if i.get("id") == db_id), None)
        if not match:
            raise NotFoundError(f"Managed database {db_id} not found.")
        enc = match.get("password_encrypted")
        if not enc:
            raise AppException("No password stored for this database.", code="db_no_password")
        password = self._decrypt(str(enc))
        if not password:
            raise AppException("Could not decrypt stored password.", code="db_password_corrupt")
        uri = self._build_uri(
            engine=str(match.get("engine") or ""),
            name=str(match.get("name") or ""),
            username=match.get("username"),
            password=password,
            host=match.get("host"),
            port=match.get("port"),
            path=match.get("path"),
            mask_password=False,
        )
        return DatabasePasswordResponse(id=db_id, password=password, connection_uri=uri)

    async def adopt(self, body: DatabaseAdoptRequest) -> DatabaseCreatedResponse:
        items = self._read_registry()
        for existing in items:
            same_engine = existing.get("engine") == body.engine
            same_name = existing.get("name") == body.name
            same_path = body.path and existing.get("path") == body.path
            if same_engine and (same_path or (body.engine != "sqlite" and same_name)):
                raise AppException(
                    f"{body.engine} database `{body.name}` is already managed.",
                    code="db_already_managed",
                )

        host = body.host
        port = body.port
        path = body.path
        if body.engine == "sqlite":
            if not path:
                raise AppException("SQLite adopt requires a file path.", code="db_path_required")
            path_obj = Path(path).expanduser()
            if not path_obj.exists():
                raise NotFoundError(f"SQLite file not found: {path}")
            path = str(path_obj)
            host = None
            port = None
        elif body.engine == "mysql":
            host = host or "127.0.0.1"
            port = port or 3306
        elif body.engine == "postgresql":
            host = host or "127.0.0.1"
            port = port or 5432
        elif body.engine == "mongodb":
            host = host or "127.0.0.1"
            port = port or 27017

        record = {
            "id": str(uuid.uuid4()),
            "engine": body.engine,
            "name": Path(path).name if body.engine == "sqlite" and path else body.name,
            "username": body.username,
            "password_encrypted": self._encrypt(body.password) if body.password else None,
            "host": host,
            "port": port,
            "path": path,
            "notes": body.notes or "Adopted from live host database",
            "created_at": datetime.now(UTC).isoformat(),
            "size_bytes": Path(path).stat().st_size if body.engine == "sqlite" and path else None,
        }
        items.append(record)
        self._write_registry(items)
        schema = self._record_to_schema(record, include_uri_password=False)
        uri_full = self._build_uri(
            engine=body.engine,
            name=record["name"],
            username=body.username,
            password=body.password,
            host=host,
            port=port,
            path=path,
            mask_password=False,
        )
        return DatabaseCreatedResponse(
            message=f"Adopted {body.engine} database `{record['name']}` into managed registry.",
            database=schema,
            password=body.password,
            connection_uri=uri_full,
            details={"adopted": True},
        )

    async def drop_live(self, body: DatabaseLiveDropRequest) -> OperationResult:
        if body.engine == "sqlite" and not body.path:
            raise AppException("SQLite live drop requires a path.", code="db_path_required")
        match = {
            "engine": body.engine,
            "name": body.name,
            "path": body.path,
            "username": body.username,
        }
        backup = await asyncio.to_thread(
            self._create_backup,
            engine=body.engine,
            name=body.name,
            path=body.path,
            kind="pre_drop",
        )
        opts = body.as_options()
        await asyncio.to_thread(self._drop_engine_db, match, opts, None)

        # Remove matching managed registry entries so overview stays consistent.
        items = self._read_registry()
        remaining = []
        for item in items:
            same_engine = item.get("engine") == body.engine
            same_path = body.path and item.get("path") == body.path
            same_name = item.get("name") == body.name
            if same_engine and (same_path or (body.engine != "sqlite" and same_name)):
                continue
            remaining.append(item)
        if len(remaining) != len(items):
            self._write_registry(remaining)

        return OperationResult(
            success=True,
            message=f"Dropped live {body.engine} database `{body.name}`. Backup saved first.",
            details={
                "backup_id": backup["id"],
                "backup_filename": backup["filename"],
                "backup_size_bytes": backup.get("size_bytes"),
            },
        )

    async def backup_managed(self, db_id: str) -> DatabaseBackupSchema:
        items = self._read_registry()
        match = next((i for i in items if i.get("id") == db_id), None)
        if not match:
            raise NotFoundError(f"Managed database {db_id} not found.")
        raw = await asyncio.to_thread(
            self._create_backup,
            engine=str(match.get("engine") or ""),
            name=str(match.get("name") or ""),
            path=match.get("path"),
            kind="manual",
        )
        return DatabaseBackupSchema(**raw)

    async def backup_live(
        self, *, engine: str, name: str, path: str | None = None
    ) -> DatabaseBackupSchema:
        raw = await asyncio.to_thread(
            self._create_backup,
            engine=engine,
            name=name,
            path=path,
            kind="manual",
        )
        return DatabaseBackupSchema(**raw)

    async def list_backups(self) -> list[DatabaseBackupSchema]:
        return [DatabaseBackupSchema(**row) for row in self._read_backup_index()]

    def resolve_backup_file(self, backup_id: str) -> Path:
        match = next((b for b in self._read_backup_index() if b.get("id") == backup_id), None)
        if not match:
            raise NotFoundError(f"Backup {backup_id} not found.")
        path = Path(str(match["path"]))
        if not path.exists():
            raise NotFoundError(f"Backup file missing: {path}")
        if not self._is_under(path, self._backup_root):
            raise AppException("Backup path denied.", code="db_backup_denied")
        return path

    async def restore(self, body: DatabaseRestoreRequest, upload_path: Path | None = None) -> OperationResult:
        source: Path | None = None
        if body.backup_id:
            source = self.resolve_backup_file(body.backup_id)
        elif upload_path:
            source = upload_path
        if source is None or not source.exists():
            raise AppException("Provide backup_id or an uploaded dump file.", code="db_restore_source")

        await asyncio.to_thread(
            self._restore_engine_db,
            engine=body.engine,
            name=body.name,
            path=body.path,
            source=source,
            create_if_missing=body.create_if_missing,
        )
        return OperationResult(
            success=True,
            message=f"Restored {body.engine} database `{body.name}` from {source.name}.",
            details={"source": str(source), "engine": body.engine, "name": body.name},
        )

    async def ensure_engine(self, engine: str) -> OperationResult:
        if engine == "mongodb":
            return await asyncio.to_thread(self._ensure_mongodb)
        if engine == "mysql":
            return await asyncio.to_thread(self._ensure_systemd, "mysql", "mysqld")
        if engine == "postgresql":
            return await asyncio.to_thread(self._ensure_systemd, "postgresql", "postgres")
        if engine == "sqlite":
            return OperationResult(success=True, message="SQLite is always available (stdlib).")
        raise AppException(f"Unknown engine: {engine}", code="db_engine_unsupported")

    # ── Engine probes / live lists ─────────────────────────────────────────

    def _probe_engines(self) -> list[EngineStatusSchema]:
        return [
            self._probe_sqlite(),
            self._probe_mysql(),
            self._probe_postgresql(),
            self._probe_mongodb(),
        ]

    def _probe_sqlite(self) -> EngineStatusSchema:
        bin_path = shutil.which("sqlite3")
        version = None
        if bin_path:
            code, out, _ = self._run([bin_path, "--version"])
            if code == 0:
                version = out.strip().split()[0] if out.strip() else None
        return EngineStatusSchema(
            engine="sqlite",
            available=True,
            running=True,
            version=version or "stdlib",
            message=f"Files under {self._sqlite_root}",
            installable=False,
        )

    def _probe_mysql(self) -> EngineStatusSchema:
        running = self._systemd_active("mysql") or self._port_open(3306)
        version = None
        if shutil.which("mysql"):
            code, out, _ = self._run(["mysql", "--version"])
            if code == 0:
                version = out.strip()
        return EngineStatusSchema(
            engine="mysql",
            available=bool(shutil.which("mysql") or running),
            running=running,
            version=version,
            host="127.0.0.1",
            port=3306,
            message=None if running else "MySQL service not running.",
            installable=True,
        )

    def _probe_postgresql(self) -> EngineStatusSchema:
        running = self._systemd_active("postgresql") or self._port_open(5432)
        version = None
        if shutil.which("psql"):
            code, out, _ = self._run(["psql", "--version"])
            if code == 0:
                version = out.strip()
        return EngineStatusSchema(
            engine="postgresql",
            available=bool(shutil.which("psql") or running),
            running=running,
            version=version,
            host="127.0.0.1",
            port=5432,
            message=None if running else "PostgreSQL service not running.",
            installable=True,
        )

    def _probe_mongodb(self) -> EngineStatusSchema:
        running = self._systemd_active("mongod") or self._port_open(27017)
        bin_ok = bool(shutil.which("mongosh") or shutil.which("mongo") or shutil.which("mongod"))
        version = None
        for cmd in (["mongod", "--version"], ["mongosh", "--version"]):
            if not shutil.which(cmd[0]):
                continue
            code, out, _ = self._run(cmd)
            if code == 0 and out.strip():
                version = out.strip().splitlines()[0][:120]
                break
        return EngineStatusSchema(
            engine="mongodb",
            available=bin_ok or running,
            running=running,
            version=version,
            host="127.0.0.1",
            port=27017,
            message="MongoDB not installed. Use Ensure to install." if not (bin_ok or running) else None,
            installable=True,
        )

    def _list_live(self) -> list[LiveDatabaseSchema]:
        out: list[LiveDatabaseSchema] = []
        out.extend(self._live_mysql())
        out.extend(self._live_postgresql())
        out.extend(self._live_mongodb())
        out.extend(self._live_sqlite())
        return out

    def _live_mysql(self) -> list[LiveDatabaseSchema]:
        if not shutil.which("mysql"):
            return []
        code, stdout, _ = self._run(
            [
                "mysql",
                "-N",
                "-e",
                (
                    "SELECT s.SCHEMA_NAME, COUNT(t.TABLE_NAME) "
                    "FROM information_schema.SCHEMATA s "
                    "LEFT JOIN information_schema.TABLES t "
                    "ON t.TABLE_SCHEMA=s.SCHEMA_NAME AND t.TABLE_TYPE='BASE TABLE' "
                    "GROUP BY s.SCHEMA_NAME ORDER BY s.SCHEMA_NAME;"
                ),
            ]
        )
        if code != 0:
            return []
        rows: list[LiveDatabaseSchema] = []
        for line in stdout.splitlines():
            parts = line.split("\t")
            name = parts[0].strip() if parts else ""
            if not name or name in SYSTEM_MYSQL:
                continue
            count = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else None
            rows.append(LiveDatabaseSchema(engine="mysql", name=name, table_count=count))
        return rows

    def _live_postgresql(self) -> list[LiveDatabaseSchema]:
        code, stdout, _ = self._run_as_postgres(
            "SELECT datname, pg_catalog.pg_get_userbyid(datdba) FROM pg_database WHERE datistemplate = false;"
        )
        if code != 0:
            return []
        rows: list[LiveDatabaseSchema] = []
        for line in stdout.splitlines():
            parts = [p.strip() for p in line.split("|")]
            if len(parts) >= 1 and parts[0] and parts[0] not in SYSTEM_PG:
                count_code, count_out, _ = self._run(
                    [
                        "sudo",
                        "-u",
                        "postgres",
                        "psql",
                        "-d",
                        parts[0],
                        "-tAc",
                        (
                            "SELECT COUNT(*) FROM information_schema.tables "
                            "WHERE table_schema NOT IN ('pg_catalog','information_schema') "
                            "AND table_type='BASE TABLE';"
                        ),
                    ]
                )
                table_count = (
                    int(count_out.strip())
                    if count_code == 0 and count_out.strip().isdigit()
                    else None
                )
                rows.append(
                    LiveDatabaseSchema(
                        engine="postgresql",
                        name=parts[0],
                        owner=parts[1] if len(parts) > 1 else None,
                        table_count=table_count,
                    )
                )
        return rows

    def _live_mongodb(self) -> list[LiveDatabaseSchema]:
        if not (self._port_open(27017) or shutil.which("mongosh") or shutil.which("mongo")):
            return []
        code, stdout, _ = self._mongo_eval("db.adminCommand('listDatabases').databases.map(d => d.name).join('\\n')")
        if code != 0:
            return []
        skip = {"admin", "local", "config"}
        rows: list[LiveDatabaseSchema] = []
        for raw_name in stdout.splitlines():
            name = raw_name.strip()
            if not name or name in skip:
                continue
            count_code, count_out, _ = self._mongo_eval(
                f"db.getSiblingDB('{self._js_escape(name)}').getCollectionNames().length"
            )
            match = re.search(r"\d+", count_out) if count_code == 0 else None
            rows.append(
                LiveDatabaseSchema(
                    engine="mongodb",
                    name=name,
                    table_count=int(match.group()) if match else None,
                )
            )
        return rows

    def _live_sqlite(self) -> list[LiveDatabaseSchema]:
        found: list[LiveDatabaseSchema] = []
        if not self._sqlite_root.exists():
            return found
        skip_dirs = {
            "node_modules",
            "venv",
            ".venv",
            ".git",
            "vendor",
            "__pycache__",
            "dist",
            "build",
            ".next",
            "storage",
            "logs",
            "tmp",
            "cache",
        }
        suffixes = {".sqlite3", ".sqlite", ".db"}
        root = self._sqlite_root
        for dirpath, dirnames, filenames in os.walk(root):
            # Prune expensive / irrelevant trees early.
            dirnames[:] = [d for d in dirnames if d not in skip_dirs and not d.startswith(".")]
            depth = Path(dirpath).relative_to(root).parts
            if len(depth) > 5:
                dirnames.clear()
                continue
            for name in filenames:
                path = Path(dirpath) / name
                if path.suffix.lower() not in suffixes:
                    continue
                if not path.is_file():
                    continue
                try:
                    size = path.stat().st_size
                except OSError:
                    size = None
                found.append(
                    LiveDatabaseSchema(
                        engine="sqlite",
                        name=path.name,
                        path=str(path),
                        size_bytes=size,
                        table_count=None,
                    )
                )
                if len(found) >= 80:
                    return found
        return found

    # ── Create helpers ─────────────────────────────────────────────────────

    def _create_sqlite(self, body: DatabaseCreateRequest) -> dict[str, Any]:
        if body.path:
            path = Path(body.path).expanduser()
            if not path.is_absolute():
                path = (self._sqlite_root / path).resolve()
        else:
            folder = self._sqlite_root / body.name
            folder.mkdir(parents=True, exist_ok=True)
            path = folder / f"{body.name}.sqlite3"

        # Safety: only under allowed roots
        allowed = [self._sqlite_root, Path("/var/www"), Path("/opt")]
        if not any(self._is_under(path, root) for root in allowed):
            raise AppException(
                f"SQLite path must be under {self._sqlite_root} (or /var/www, /opt).",
                code="db_path_denied",
            )

        if path.exists() and not body.overwrite:
            raise AppException(f"SQLite file already exists: {path}", code="db_exists")
        path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(path))
        try:
            conn.execute("CREATE TABLE IF NOT EXISTS _ifnotus_meta (k TEXT PRIMARY KEY, v TEXT)")
            conn.execute(
                "INSERT OR REPLACE INTO _ifnotus_meta(k,v) VALUES (?,?)",
                ("created_by", "ifnotus"),
            )
            conn.commit()
        finally:
            conn.close()
        return {
            "path": str(path),
            "host": None,
            "port": None,
            "size_bytes": path.stat().st_size,
            "message": f"SQLite database created at {path}",
        }

    def _create_mysql(self, body: DatabaseCreateRequest, username: str | None, password: str | None) -> dict[str, Any]:
        if not shutil.which("mysql"):
            raise AppException("mysql client not available on this host.", code="db_mysql_missing")
        name = body.name
        allow_remote = bool(getattr(body, "remote_access", False))
        # Create DB
        sql = [
            f"CREATE DATABASE IF NOT EXISTS `{name}` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;"
        ]
        if body.create_user and username and password:
            sql.extend(
                mysql_user_grant_sql(
                    username=username,
                    password=password,
                    database=name,
                    allow_remote=allow_remote,
                    escape=self._sql_escape,
                )
            )
        code, _, err = self._run(["mysql", "-e", "\n".join(sql)])
        if code != 0:
            raise AppException(f"MySQL create failed: {err or 'unknown error'}", code="db_mysql_create_failed")
        access = "localhost + remote (%)" if allow_remote else "localhost only"
        return {
            "host": body.host or "127.0.0.1",
            "port": body.port or 3306,
            "path": None,
            "remote_access": allow_remote,
            "message": f"MySQL database `{name}` created"
            + (f" with user `{username}` ({access})" if username else "")
            + ".",
        }

    def _create_postgresql(
        self, body: DatabaseCreateRequest, username: str | None, password: str | None
    ) -> dict[str, Any]:
        name = body.name
        if body.create_user and username and password:
            # Role may already exist
            exists_code, exists_out, _ = self._run_as_postgres(
                f"SELECT 1 FROM pg_roles WHERE rolname = '{self._sql_escape(username)}';"
            )
            role_exists = exists_code == 0 and "1" in exists_out
            if role_exists:
                code, _, err = self._run_as_postgres(
                    f"ALTER ROLE \"{username}\" WITH LOGIN PASSWORD '{self._sql_escape(password)}';"
                )
            else:
                code, _, err = self._run_as_postgres(
                    f"CREATE ROLE \"{username}\" WITH LOGIN PASSWORD '{self._sql_escape(password)}';"
                )
            if code != 0:
                raise AppException(f"PostgreSQL user create failed: {err}", code="db_pg_user_failed")

        owner = username or "postgres"
        code, exists_out, err = self._run_as_postgres(
            f"SELECT 1 FROM pg_database WHERE datname = '{self._sql_escape(name)}';"
        )
        if code == 0 and "1" in exists_out:
            if not body.overwrite:
                raise AppException(f"PostgreSQL database already exists: {name}", code="db_exists")
        else:
            code, _, err = self._run_as_postgres(f'CREATE DATABASE "{name}" OWNER "{owner}";')
            if code != 0:
                raise AppException(f"PostgreSQL create failed: {err}", code="db_pg_create_failed")

        if username:
            self._run_as_postgres(f'GRANT ALL PRIVILEGES ON DATABASE "{name}" TO "{username}";')
        return {
            "host": body.host or "127.0.0.1",
            "port": body.port or 5432,
            "path": None,
            "message": f"PostgreSQL database `{name}` created"
            + (f" owned by `{username}`" if username else "")
            + ".",
        }

    def _create_mongodb(
        self, body: DatabaseCreateRequest, username: str | None, password: str | None
    ) -> dict[str, Any]:
        status = self._probe_mongodb()
        if not status.running:
            raise AppException(
                "MongoDB is not running. Open Databases → Ensure MongoDB first.",
                code="db_mongo_not_running",
            )
        name = body.name
        # Touch DB by inserting a meta doc, then remove if user asked empty — keep meta
        js_create = (
            f"db.getSiblingDB('{self._js_escape(name)}')"
            f".getCollection('_ifnotus_meta').insertOne({{created_by:'ifnotus', at:new Date()}})"
        )
        code, _, err = self._mongo_eval(js_create)
        if code != 0:
            raise AppException(f"MongoDB create failed: {err}", code="db_mongo_create_failed")

        if body.create_user and username and password:
            js_user = (
                "db.getSiblingDB('admin').createUser({"
                f"user:'{self._js_escape(username)}',"
                f"pwd:'{self._js_escape(password)}',"
                f"roles:[{{role:'readWrite',db:'{self._js_escape(name)}'}},"
                f"{{role:'dbAdmin',db:'{self._js_escape(name)}'}}]"
                "})"
            )
            code, _, err = self._mongo_eval(js_user)
            # Ignore duplicate user
            if code != 0 and "already exists" not in (err or "").lower() and "UserAlreadyExists" not in (err or ""):
                # Try update password
                js_upd = (
                    f"db.getSiblingDB('admin').changeUserPassword("
                    f"'{self._js_escape(username)}','{self._js_escape(password)}')"
                )
                code2, _, err2 = self._mongo_eval(js_upd)
                if code2 != 0:
                    raise AppException(
                        f"MongoDB user create failed: {err or err2}",
                        code="db_mongo_user_failed",
                    )

        return {
            "host": body.host or "127.0.0.1",
            "port": body.port or 27017,
            "path": None,
            "message": f"MongoDB database `{name}` created"
            + (f" with user `{username}`" if username else "")
            + ".",
        }

    # ── Backup / restore helpers ───────────────────────────────────────────

    def _read_backup_index(self) -> list[dict[str, Any]]:
        if not self._backup_index.exists():
            return []
        try:
            data = json.loads(self._backup_index.read_text(encoding="utf-8"))
            items = data.get("backups") if isinstance(data, dict) else data
            return list(items) if isinstance(items, list) else []
        except (OSError, json.JSONDecodeError):
            return []

    def _write_backup_index(self, items: list[dict[str, Any]]) -> None:
        self._backup_root.mkdir(parents=True, exist_ok=True)
        payload = {"backups": items[-200:], "updated_at": datetime.now(UTC).isoformat()}
        tmp = self._backup_index.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        tmp.replace(self._backup_index)

    def _create_backup(
        self,
        *,
        engine: str,
        name: str,
        path: str | None,
        kind: str = "manual",
    ) -> dict[str, Any]:
        self._backup_root.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        safe_name = re.sub(r"[^A-Za-z0-9_.-]+", "_", name)[:64] or "db"
        backup_id = str(uuid.uuid4())
        if engine == "sqlite":
            if not path:
                raise AppException("SQLite backup requires a path.", code="db_path_required")
            src = Path(path)
            if not src.exists():
                raise NotFoundError(f"SQLite file not found: {path}")
            filename = f"{safe_name}-{stamp}.sqlite3"
            dest = self._backup_root / filename
            shutil.copy2(src, dest)
        elif engine == "mysql":
            if not shutil.which("mysqldump"):
                raise AppException("mysqldump is not available on this host.", code="db_backup_tool")
            filename = f"{safe_name}-{stamp}.sql"
            dest = self._backup_root / filename
            code, out, err = self._run(
                ["mysqldump", "--single-transaction", "--routines", "--triggers", name],
                timeout=300,
            )
            if code != 0:
                raise AppException(f"mysqldump failed: {err or out}", code="db_backup_failed")
            dest.write_text(out, encoding="utf-8")
        elif engine == "postgresql":
            if not shutil.which("pg_dump"):
                raise AppException("pg_dump is not available on this host.", code="db_backup_tool")
            filename = f"{safe_name}-{stamp}.sql"
            dest = self._backup_root / filename
            code, out, err = self._run(
                ["sudo", "-u", "postgres", "pg_dump", "--no-owner", "--no-acl", name],
                timeout=300,
            )
            if code != 0:
                raise AppException(f"pg_dump failed: {err or out}", code="db_backup_failed")
            dest.write_text(out, encoding="utf-8")
        elif engine == "mongodb":
            filename = f"{safe_name}-{stamp}.archive"
            dest = self._backup_root / filename
            mongodump = shutil.which("mongodump")
            if mongodump:
                code, out, err = self._run([mongodump, f"--db={name}", f"--archive={dest}"])
                if code != 0:
                    raise AppException(f"mongodump failed: {err or out}", code="db_backup_failed")
            else:
                # Fallback JSON dump of collections
                code, out, err = self._mongo_eval(
                    f"JSON.stringify(db.getSiblingDB('{self._js_escape(name)}')"
                    f".getCollectionNames())"
                )
                if code != 0:
                    raise AppException(f"Mongo backup failed: {err or out}", code="db_backup_failed")
                dest.write_text(out or "[]", encoding="utf-8")
                filename = f"{safe_name}-{stamp}.json"
                renamed = self._backup_root / filename
                dest.rename(renamed)
                dest = renamed
        else:
            raise AppException(f"Unsupported engine: {engine}", code="db_engine_unsupported")

        try:
            size = dest.stat().st_size
        except OSError:
            size = None
        record = {
            "id": backup_id,
            "engine": engine,
            "database": name,
            "filename": filename,
            "path": str(dest),
            "size_bytes": size,
            "created_at": datetime.now(UTC).isoformat(),
            "kind": kind,
        }
        items = self._read_backup_index()
        items.append(record)
        self._write_backup_index(items)
        return record

    def _restore_engine_db(
        self,
        *,
        engine: str,
        name: str,
        path: str | None,
        source: Path,
        create_if_missing: bool,
    ) -> None:
        if engine == "sqlite":
            if not path:
                raise AppException("SQLite restore requires a destination path.", code="db_path_required")
            dest = Path(path)
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, dest)
            return
        if engine == "mysql":
            if create_if_missing:
                self._run(["mysql", "-e", f"CREATE DATABASE IF NOT EXISTS `{name}` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;"])
            sql = source.read_text(encoding="utf-8", errors="replace")
            code, _, err = self._run(["mysql", name], input_text=sql, timeout=300)
            if code != 0:
                raise AppException(f"MySQL restore failed: {err}", code="db_restore_failed")
            return
        if engine == "postgresql":
            if create_if_missing:
                exists_code, exists_out, _ = self._run_as_postgres(
                    f"SELECT 1 FROM pg_database WHERE datname = '{self._sql_escape(name)}';"
                )
                if not (exists_code == 0 and "1" in exists_out):
                    code, _, err = self._run_as_postgres(f'CREATE DATABASE "{name}";')
                    if code != 0:
                        raise AppException(f"PostgreSQL create for restore failed: {err}", code="db_restore_failed")
            code, out, err = self._run(
                ["sudo", "-u", "postgres", "psql", "-d", name, "-v", "ON_ERROR_STOP=1", "-f", str(source)],
                timeout=300,
            )
            if code != 0:
                raise AppException(f"PostgreSQL restore failed: {err or out}", code="db_restore_failed")
            return
        if engine == "mongodb":
            mongorestore = shutil.which("mongorestore")
            if mongorestore and source.suffix in {".archive", ""}:
                code, out, err = self._run(
                    [mongorestore, f"--nsInclude={name}.*", f"--archive={source}", "--drop"]
                )
                if code != 0:
                    raise AppException(f"mongorestore failed: {err or out}", code="db_restore_failed")
                return
            raise AppException(
                "Mongo restore currently requires mongorestore with an archive backup.",
                code="db_restore_unsupported",
            )
        raise AppException(f"Unsupported engine: {engine}", code="db_engine_unsupported")

    # ── Drop helpers ───────────────────────────────────────────────────────

    def _drop_engine_db(self, match: dict[str, Any], opts: DatabaseDropOptions, password: str | None) -> None:
        engine = match.get("engine")
        name = str(match.get("name") or "")
        username = match.get("username")
        if engine == "sqlite":
            path = Path(str(match.get("path") or ""))
            if opts.remove_files and path.exists():
                path.unlink()
            return
        if engine == "mysql":
            self._run(["mysql", "-e", f"DROP DATABASE IF EXISTS `{name}`;"])
            if opts.drop_user and username:
                self._run(["mysql", "-e", f"DROP USER IF EXISTS '{username}'@'localhost'; DROP USER IF EXISTS '{username}'@'%'; FLUSH PRIVILEGES;"])
            return
        if engine == "postgresql":
            self._run_as_postgres(
                f"SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = '{self._sql_escape(name)}' AND pid <> pg_backend_pid();"
            )
            self._run_as_postgres(f'DROP DATABASE IF EXISTS "{name}";')
            if opts.drop_user and username:
                self._run_as_postgres(f'DROP ROLE IF EXISTS "{username}";')
            return
        if engine == "mongodb":
            self._mongo_eval(f"db.getSiblingDB('{self._js_escape(name)}').dropDatabase()")
            if opts.drop_user and username:
                self._mongo_eval(f"db.getSiblingDB('admin').dropUser('{self._js_escape(username)}')")
            return

    # ── Ensure / install ───────────────────────────────────────────────────

    def _ensure_systemd(self, unit: str, process_hint: str) -> OperationResult:
        if self._systemd_active(unit):
            return OperationResult(success=True, message=f"{unit} is already running.")
        code, out, err = self._run(["systemctl", "start", unit])
        if code != 0:
            return OperationResult(success=False, message=err or out or f"Failed to start {unit}")
        return OperationResult(success=True, message=f"Started {unit}.")

    def _ensure_mongodb(self) -> OperationResult:
        if self._systemd_active("mongod") or self._port_open(27017):
            return OperationResult(success=True, message="MongoDB is already running.")

        # Prefer docker if present (no apt repo fights)
        if shutil.which("docker"):
            # Remove stale container then run
            self._run(["docker", "rm", "-f", "ifnotus-mongo"])
            code, out, err = self._run(
                [
                    "docker",
                    "run",
                    "-d",
                    "--name",
                    "ifnotus-mongo",
                    "--restart",
                    "unless-stopped",
                    "-p",
                    "127.0.0.1:27017:27017",
                    "-v",
                    "ifnotus_mongo_data:/data/db",
                    "mongo:7",
                ]
            )
            if code == 0:
                return OperationResult(
                    success=True,
                    message="MongoDB started via Docker (ifnotus-mongo on 127.0.0.1:27017).",
                    details={"container": "ifnotus-mongo", "stdout": out},
                )
            return OperationResult(success=False, message=f"Docker Mongo start failed: {err or out}")

        # Try apt packages
        for pkg in ("mongodb", "mongodb-server", "mongodb-org"):
            code, out, err = self._run(["apt-get", "install", "-y", pkg])
            if code == 0:
                self._run(["systemctl", "enable", "--now", "mongod"])
                self._run(["systemctl", "enable", "--now", "mongodb"])
                if self._port_open(27017) or self._systemd_active("mongod"):
                    return OperationResult(success=True, message=f"Installed and started MongoDB ({pkg}).")
        return OperationResult(
            success=False,
            message="Could not install MongoDB. Install Docker or mongodb-org, then retry Ensure.",
        )

    # ── Process helpers ────────────────────────────────────────────────────

    @staticmethod
    def _sql_escape(value: str) -> str:
        return value.replace("\\", "\\\\").replace("'", "''")

    @staticmethod
    def _js_escape(value: str) -> str:
        return value.replace("\\", "\\\\").replace("'", "\\'")

    @staticmethod
    def _is_under(path: Path, root: Path) -> bool:
        try:
            path.resolve().relative_to(root.resolve())
            return True
        except ValueError:
            return False

    @staticmethod
    def _run(cmd: list[str], *, input_text: str | None = None, timeout: int = 60) -> tuple[int, str, str]:
        try:
            proc = subprocess.run(
                cmd,
                input=input_text,
                capture_output=True,
                text=True,
                timeout=timeout,
                check=False,
            )
            return proc.returncode, proc.stdout or "", proc.stderr or ""
        except (OSError, subprocess.SubprocessError) as exc:
            return 1, "", str(exc)

    def _run_as_postgres(self, sql: str) -> tuple[int, str, str]:
        if shutil.which("sudo"):
            return self._run(["sudo", "-u", "postgres", "psql", "-tAc", sql])
        return self._run(["psql", "-tAc", sql])

    def _mongo_eval(self, js: str) -> tuple[int, str, str]:
        if shutil.which("mongosh"):
            return self._run(["mongosh", "--quiet", "--eval", js])
        if shutil.which("mongo"):
            return self._run(["mongo", "--quiet", "--eval", js])
        # docker exec fallback
        if shutil.which("docker"):
            code, _, _ = self._run(["docker", "inspect", "ifnotus-mongo"])
            if code == 0:
                return self._run(["docker", "exec", "ifnotus-mongo", "mongosh", "--quiet", "--eval", js])
        return 1, "", "mongosh/mongo not available"

    @staticmethod
    def _systemd_active(unit: str) -> bool:
        try:
            proc = subprocess.run(
                ["systemctl", "is-active", unit],
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
            return proc.stdout.strip() == "active"
        except (OSError, subprocess.SubprocessError):
            return False

    @staticmethod
    def _port_open(port: int) -> bool:
        import socket

        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.4):
                return True
        except OSError:
            return False
