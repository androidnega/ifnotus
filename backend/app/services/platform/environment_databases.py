"""PHASE 27 — per-environment MySQL/PostgreSQL registry (multi-database product)."""

from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.exceptions import AppException, NotFoundError, ValidationError
from app.core.logging import get_logger
from app.models.platform import CustomerEnvironment, EnvironmentDatabase, HostingPlan, PlatformAuditLog
from app.schemas.databases import DatabaseCreateRequest, DatabaseDropOptions
from app.schemas.platform import (
    EnvironmentDatabaseCreateRequest,
    EnvironmentDatabaseImportResponse,
    EnvironmentDatabaseRevealResponse,
    EnvironmentDatabaseV2Response,
)
from app.services.hosting.databases import DatabaseManagerService
from app.services.platform.plan_matrix import feature_included, features_for, stack_allowed

logger = get_logger(__name__)

_SLUG_RE = re.compile(r"[^a-z0-9]+")
_LEGACY_PREFIX = "legacy-"


@dataclass(frozen=True)
class DatabaseEntitlements:
    mysql_databases: int
    postgres_databases: int
    database_storage_mb: int | None
    remote_database_access: bool
    database_backups: bool


def entitlements_for_plan(plan: HostingPlan | None) -> DatabaseEntitlements:
    feats = features_for(plan)
    return DatabaseEntitlements(
        mysql_databases=int(feats.get("mysql_databases") or 0),
        postgres_databases=int(feats.get("postgres_databases") or 0),
        database_storage_mb=feats.get("database_storage_mb"),
        remote_database_access=bool(feats.get("remote_database_access")),
        database_backups=feature_included(plan, "db_backups"),
    )


def _encode_host_ref(registry_id: str, host: str, port: int) -> str:
    return json.dumps({"registry_id": registry_id, "host": host, "port": port})


def _decode_host_ref(host_ref: str | None) -> dict[str, Any]:
    if not host_ref:
        return {}
    try:
        parsed = json.loads(host_ref)
        return parsed if isinstance(parsed, dict) else {"host": host_ref}
    except json.JSONDecodeError:
        return {"host": host_ref}


def _legacy_id(env_id: UUID) -> str:
    return f"{_LEGACY_PREFIX}{env_id}"


def _is_legacy_id(db_id: str) -> bool:
    return db_id.startswith(_LEGACY_PREFIX)


class EnvironmentDatabaseService:
    """Create/list/manage customer databases without exposing superusers."""

    def __init__(self, settings: Settings, session: AsyncSession) -> None:
        self._settings = settings
        self._session = session
        self._db = DatabaseManagerService(settings)

    async def list_databases(self, env: CustomerEnvironment, plan: HostingPlan | None) -> list[EnvironmentDatabaseV2Response]:
        rows: list[EnvironmentDatabaseV2Response] = []
        result = await self._session.execute(
            select(EnvironmentDatabase).where(EnvironmentDatabase.environment_id == env.id)
        )
        for item in result.scalars().all():
            meta = _decode_host_ref(item.host_ref)
            registry_id = str(meta.get("registry_id") or "")
            size_mb = await self._size_mb(item.engine, item.db_name, registry_id)
            host = str(meta.get("host") or "127.0.0.1")
            port = int(meta.get("port") or (5432 if item.engine == "postgresql" else 3306))
            rows.append(
                EnvironmentDatabaseV2Response(
                    id=str(item.id),
                    environment_id=env.id,
                    engine=item.engine,
                    logical_name=item.logical_name,
                    name=item.db_name,
                    username=item.username,
                    host=host,
                    port=port,
                    password_set=bool(item.credential_secret_ref),
                    legacy=False,
                    status=item.status,
                    size_mb=size_mb,
                    storage_limit_mb=item.storage_limit_mb,
                    remote_access_mode=item.remote_access_mode,
                    message=(
                        "Remote DB clients allowed."
                        if (item.remote_access_mode or "") not in {"", "localhost", "off"}
                        else "Access: localhost only (apps on this server)."
                    ),
                )
            )

        legacy_id = str(getattr(env, "db_registry_id", None) or _legacy_id(env.id))
        if env.db_name or env.db_engine:
            if not any(r.id == legacy_id or (r.legacy and r.name == env.db_name) for r in rows):
                size_mb = None
                if env.db_engine and env.db_name:
                    size_mb = await self._size_mb(env.db_engine, env.db_name, str(env.db_registry_id or ""))
                rows.append(
                    EnvironmentDatabaseV2Response(
                        id=legacy_id,
                        environment_id=env.id,
                        engine=env.db_engine,
                        logical_name="primary",
                        name=env.db_name,
                        username=env.db_username,
                        host=env.db_host or "127.0.0.1",
                        port=env.db_port or (5432 if env.db_engine == "postgresql" else 3306),
                        password_set=bool(env.db_password_encrypted),
                        legacy=True,
                        message="Primary site database from stack install.",
                        status="active",
                        size_mb=size_mb,
                    )
                )
        return rows

    async def create(
        self,
        env: CustomerEnvironment,
        plan: HostingPlan | None,
        body: EnvironmentDatabaseCreateRequest,
    ) -> EnvironmentDatabaseV2Response:
        engine = (body.engine or "").strip().lower()
        if engine not in {"mysql", "postgresql"}:
            raise ValidationError("Choose MySQL or PostgreSQL.", code="db_engine_unsupported")

        stack_key = "mysql" if engine == "mysql" else "postgres"
        if not stack_allowed(plan, stack_key):
            raise ValidationError(
                f"{engine.title()} is not included on this package.",
                code="pack_feature",
            )

        ent = entitlements_for_plan(plan)
        existing = await self.list_databases(env, plan)
        mysql_count = sum(1 for r in existing if (r.engine or "").lower() == "mysql")
        pg_count = sum(1 for r in existing if (r.engine or "").lower() in {"postgresql", "postgres"})
        limit = ent.mysql_databases if engine == "mysql" else ent.postgres_databases
        current = mysql_count if engine == "mysql" else pg_count
        if current >= limit:
            raise ValidationError(
                f"This package allows {limit} {engine} database(s). Delete one or upgrade.",
                code="db_quota",
            )

        logical = self._slug(body.logical_name or body.name or "db")
        short = str(env.id).replace("-", "")[:10]
        db_name = self._db_name(engine, short, logical)
        custom_user = self._slug(body.username) if body.username else db_name
        custom_pass = body.password.strip() if body.password else None

        created = await self._db.create(
            DatabaseCreateRequest(
                engine=engine,
                name=db_name,
                username=custom_user,
                password=custom_pass,
                create_user=True,
                remote_access=bool(ent.remote_database_access),
                notes=f"IFNOTUS env DB {env.id} / {logical}",
            )
        )
        password = created.password or custom_pass or ""
        host = created.database.host or "127.0.0.1"
        port = created.database.port or (5432 if engine == "postgresql" else 3306)
        remote_mode = "subnet" if ent.remote_database_access else "localhost"

        row = EnvironmentDatabase(
            environment_id=env.id,
            engine=engine,
            logical_name=logical,
            db_name=created.database.name,
            username=created.database.username or custom_user,
            credential_secret_ref=self._db._encrypt(password) if password else None,
            host_ref=_encode_host_ref(created.database.id, host, int(port)),
            storage_limit_mb=ent.database_storage_mb,
            remote_access_mode=remote_mode,
            status="active",
        )
        self._session.add(row)
        await self._session.flush()
        await self._audit(env, "database_create", {"engine": engine, "name": row.db_name})

        return EnvironmentDatabaseV2Response(
            id=str(row.id),
            environment_id=env.id,
            engine=row.engine,
            logical_name=row.logical_name,
            name=row.db_name,
            username=row.username,
            host=host,
            port=int(port),
            password_set=bool(password),
            legacy=False,
            status=row.status,
            size_mb=0.0,
            storage_limit_mb=row.storage_limit_mb,
            remote_access_mode=row.remote_access_mode,
            message=(
                f"{engine.title()} database `{db_name}` and user `{row.username}` created with full privileges. "
                + (
                    "Remote DB clients allowed per package."
                    if remote_mode != "localhost"
                    else "Database login is localhost-only (apps on this server)."
                )
            ),
        )

    async def reveal(self, env: CustomerEnvironment, db_id: str) -> EnvironmentDatabaseRevealResponse:
        if _is_legacy_id(db_id) or db_id == str(getattr(env, "db_registry_id", "") or ""):
            return await self._reveal_legacy(env)
        row = await self._get_row(env, db_id)
        meta = _decode_host_ref(row.host_ref)
        registry_id = str(meta.get("registry_id") or "")
        if registry_id:
            try:
                revealed = await self._db.reveal_password(registry_id)
                return EnvironmentDatabaseRevealResponse(
                    id=str(row.id),
                    engine=row.engine,
                    name=row.db_name,
                    username=row.username,
                    host=str(meta.get("host") or "127.0.0.1"),
                    port=int(meta.get("port") or (5432 if row.engine == "postgresql" else 3306)),
                    password=revealed.password,
                    connection_uri=revealed.connection_uri,
                )
            except Exception as exc:
                logger.warning("db_registry_item_not_found_fallback_to_secret", registry_id=registry_id, db_id=db_id, error=str(exc))
        
        password = None
        if row.credential_secret_ref:
            password = self._db._decrypt(row.credential_secret_ref)
        if not password and env.db_password_encrypted:
            password = self._db._decrypt(env.db_password_encrypted)
        
        if not password:
            # Generate and apply a fallback strong password so user credentials always work
            password = self._db._strong_password()
            try:
                await self._apply_password(row.engine, row.db_name, row.username, password)
                row.credential_secret_ref = self._db._encrypt(password)
                await self._session.flush()
            except Exception as exc:
                logger.warning("db_password_auto_heal_failed", db=row.db_name, error=str(exc))

        host = str(meta.get("host") or "127.0.0.1")
        port = int(meta.get("port") or (5432 if row.engine == "postgresql" else 3306))
        uri = self._db._build_uri(
            engine=row.engine,
            name=row.db_name,
            username=row.username,
            password=password or "",
            host=host,
            port=port,
            path=None,
            mask_password=False,
        )
        return EnvironmentDatabaseRevealResponse(
            id=str(row.id),
            engine=row.engine,
            name=row.db_name,
            username=row.username,
            host=host,
            port=port,
            password=password,
            connection_uri=uri,
        )

    async def reset_password(self, env: CustomerEnvironment, db_id: str) -> EnvironmentDatabaseRevealResponse:
        if _is_legacy_id(db_id):
            raise ValidationError("Reset the primary stack database from Stack or support.", code="legacy_db")
        row = await self._get_row(env, db_id)
        password = self._db._strong_password()
        await self._apply_password(row.engine, row.db_name, row.username, password)
        row.credential_secret_ref = self._db._encrypt(password)
        meta = _decode_host_ref(row.host_ref)
        registry_id = str(meta.get("registry_id") or "")
        if registry_id:
            items = self._db._read_registry()
            for item in items:
                if item.get("id") == registry_id:
                    item["password_encrypted"] = self._db._encrypt(password)
                    break
            self._db._write_registry(items)
        await self._session.flush()
        await self._audit(env, "database_reset_password", {"database_id": str(row.id), "name": row.db_name})
        return await self.reveal(env, db_id)

    async def delete(self, env: CustomerEnvironment, plan: HostingPlan | None, db_id: str) -> None:
        if _is_legacy_id(db_id):
            raise ValidationError(
                "The primary site database cannot be deleted here. Reset the stack instead.",
                code="legacy_db",
            )
        row = await self._get_row(env, db_id)
        meta = _decode_host_ref(row.host_ref)
        registry_id = str(meta.get("registry_id") or "")
        if registry_id:
            await self._db.drop(registry_id, DatabaseDropOptions(drop_user=True))
        await self._session.delete(row)
        await self._session.flush()
        await self._audit(env, "database_delete", {"database_id": db_id, "name": row.db_name})

    async def backup(self, env: CustomerEnvironment, plan: HostingPlan | None, db_id: str) -> dict[str, Any]:
        if not entitlements_for_plan(plan).database_backups:
            raise ValidationError("Database backups are not included on this package.", code="pack_feature")
        meta_id = await self._resolve_registry_id(env, db_id)
        backup = await self._db.backup_managed(meta_id)
        await self._audit(env, "database_backup", {"database_id": db_id, "backup_id": backup.id})
        return backup.model_dump()

    async def import_sql(
        self,
        env: CustomerEnvironment,
        db_id: str,
        sql_content: str,
    ) -> EnvironmentDatabaseImportResponse:
        revealed = await self.reveal(env, db_id)
        engine = (revealed.engine or "mysql").lower()
        db_name = revealed.name
        if not db_name:
            raise ValidationError("Target database name is missing.", code="db_missing")

        trimmed = (sql_content or "").strip()
        if not trimmed:
            raise ValidationError("SQL file/query is empty.", code="empty_sql")

        # Run SQL import via database engine
        if engine in {"mysql", "mariadb"}:
            code, out, err = self._db._run(["mysql", db_name], input_text=trimmed, timeout=300)
            if code != 0:
                raise AppException(f"MySQL import error: {err or out}", code="db_import_failed")
        elif engine in {"postgresql", "postgres"}:
            code, out, err = self._db._run(
                ["sudo", "-u", "postgres", "psql", "-d", db_name, "-v", "ON_ERROR_STOP=1"],
                input_text=trimmed,
                timeout=300,
            )
            if code != 0:
                raise AppException(f"PostgreSQL import error: {err or out}", code="db_import_failed")
        else:
            raise ValidationError(f"SQL import not supported for {engine}.", code="unsupported_engine")

        await self._audit(
            env,
            "database_import_sql",
            {"database": db_name, "engine": engine, "size_bytes": len(trimmed.encode("utf-8"))},
        )

        stmts = [s for s in trimmed.split(";") if s.strip()]
        return EnvironmentDatabaseImportResponse(
            success=True,
            message=f"SQL import complete for `{db_name}` ({len(stmts)} statement(s) processed).",
            database=db_name,
            engine=engine,
            statements_executed=len(stmts),
            imported_bytes=len(trimmed.encode("utf-8")),
        )

    async def _resolve_registry_id(self, env: CustomerEnvironment, db_id: str) -> str:
        if _is_legacy_id(db_id) or db_id == str(getattr(env, "db_registry_id", "") or ""):
            rid = getattr(env, "db_registry_id", None)
            if not rid:
                result = await self._session.execute(
                    select(EnvironmentDatabase).where(
                        EnvironmentDatabase.environment_id == env.id
                    ).order_by(EnvironmentDatabase.created_at.desc())
                )
                first_db = result.scalars().first()
                if first_db:
                    meta = _decode_host_ref(first_db.host_ref)
                    rid = meta.get("registry_id")
                    if rid:
                        return str(rid)
                raise NotFoundError("No managed registry id for legacy database.")
            return str(rid)
        row = await self._get_row(env, db_id)
        meta = _decode_host_ref(row.host_ref)
        registry_id = str(meta.get("registry_id") or "")
        if not registry_id:
            raise NotFoundError("Database is not linked to the host registry.")
        return registry_id

    async def _reveal_legacy(self, env: CustomerEnvironment) -> EnvironmentDatabaseRevealResponse:
        if not env.db_name:
            result = await self._session.execute(
                select(EnvironmentDatabase).where(
                    EnvironmentDatabase.environment_id == env.id
                ).order_by(EnvironmentDatabase.created_at.desc())
            )
            first_db = result.scalars().first()
            if first_db:
                return await self.reveal(env, str(first_db.id))
            raise NotFoundError("No database on this site yet.")
        password = None
        if env.db_password_encrypted:
            password = self._db._decrypt(env.db_password_encrypted)
        uri = None
        if password and env.db_engine:
            uri = self._db._build_uri(
                engine=env.db_engine,
                name=env.db_name,
                username=env.db_username,
                password=password,
                host=env.db_host or "127.0.0.1",
                port=env.db_port,
                path=None,
                mask_password=False,
            )
        return EnvironmentDatabaseRevealResponse(
            id=str(getattr(env, "db_registry_id", None) or _legacy_id(env.id)),
            engine=env.db_engine,
            name=env.db_name,
            username=env.db_username,
            host=env.db_host or "127.0.0.1",
            port=env.db_port or (5432 if env.db_engine == "postgresql" else 3306),
            password=password,
            connection_uri=uri,
        )

    async def _get_row(self, env: CustomerEnvironment, db_id: str) -> EnvironmentDatabase:
        uid: UUID | None = None
        try:
            uid = UUID(db_id)
        except ValueError:
            pass
        if uid is not None:
            result = await self._session.execute(
                select(EnvironmentDatabase).where(
                    EnvironmentDatabase.id == uid,
                    EnvironmentDatabase.environment_id == env.id,
                )
            )
            row = result.scalar_one_or_none()
            if row is not None:
                return row

        # Search by registry_id in host_ref, db_name, or return first database in environment
        res_all = await self._session.execute(
            select(EnvironmentDatabase).where(
                EnvironmentDatabase.environment_id == env.id,
            )
        )
        all_rows = list(res_all.scalars().all())
        for r in all_rows:
            meta = _decode_host_ref(r.host_ref)
            if meta.get("registry_id") == db_id or r.db_name == db_id or str(r.id) == db_id:
                return r
        if all_rows:
            return all_rows[0]
        raise NotFoundError("Database not found.")

    async def _size_mb(self, engine: str | None, name: str | None, registry_id: str) -> float | None:
        if not engine or not name:
            return None
        if registry_id:
            for item in self._db._read_registry():
                if item.get("id") == registry_id and item.get("size_bytes"):
                    return round(int(item["size_bytes"]) / (1024 * 1024), 2)
        eng = engine.lower()
        try:
            if eng == "mysql":
                code, out, _ = self._db._run(
                    [
                        "mysql",
                        "-N",
                        "-e",
                        (
                            "SELECT ROUND(SUM(data_length+index_length)/1024/1024,2) "
                            f"FROM information_schema.tables WHERE table_schema='{self._db._sql_escape(name)}';"
                        ),
                    ]
                )
                if code == 0 and out.strip():
                    return float(out.strip())
            elif eng in {"postgresql", "postgres"}:
                code, out, _ = self._db._run_as_postgres(
                    f"SELECT pg_database_size('{self._db._sql_escape(name)}')/1024/1024.0;"
                )
                if code == 0 and out.strip():
                    return round(float(out.strip()), 2)
        except (ValueError, subprocess.SubprocessError) as exc:
            logger.debug("db_size_probe_failed", engine=eng, name=name, error=str(exc))
        return None

    async def _apply_password(self, engine: str, db_name: str, username: str, password: str) -> None:
        esc = self._db._sql_escape(password)
        user_esc = self._db._sql_escape(username)
        if engine == "mysql":
            # Always reset localhost. Only touch @'%' when that account exists.
            stmts = [f"ALTER USER '{user_esc}'@'localhost' IDENTIFIED BY '{esc}';"]
            code_chk, out, _ = self._db._run(
                [
                    "mysql",
                    "-N",
                    "-e",
                    f"SELECT COUNT(*) FROM mysql.user WHERE User='{user_esc}' AND Host='%';",
                ]
            )
            if code_chk == 0 and (out or "").strip() not in {"", "0"}:
                stmts.append(f"ALTER USER '{user_esc}'@'%' IDENTIFIED BY '{esc}';")
            stmts.append("FLUSH PRIVILEGES;")
            code, _, err = self._db._run(["mysql", "-e", "\n".join(stmts)])
            if code != 0:
                raise AppException(f"MySQL password reset failed: {err}", code="db_mysql_reset_failed")
        elif engine == "postgresql":
            code, _, err = self._db._run_as_postgres(
                f"ALTER ROLE \"{username}\" WITH LOGIN PASSWORD '{esc}';"
            )
            if code != 0:
                raise AppException(f"PostgreSQL password reset failed: {err}", code="db_pg_reset_failed")
        else:
            raise ValidationError(f"Unsupported engine: {engine}", code="db_engine_unsupported")

    async def repair_mysql_remote_scope(
        self,
        env: CustomerEnvironment,
        plan: HostingPlan | None,
        *,
        actor: str = "system",
    ) -> dict[str, Any]:
        """Drop MySQL user@'%' when the plan is localhost-only (PHASE 38H repair)."""
        from app.services.hosting.databases import mysql_revoke_remote_sql

        ent = entitlements_for_plan(plan)
        allow_remote = bool(ent.remote_database_access)
        repaired: list[str] = []
        skipped: list[str] = []

        result = await self._session.execute(
            select(EnvironmentDatabase).where(
                EnvironmentDatabase.environment_id == env.id,
                EnvironmentDatabase.engine == "mysql",
            )
        )
        for row in result.scalars().all():
            if not row.username:
                continue
            if allow_remote:
                row.remote_access_mode = "subnet"
                skipped.append(row.username)
                continue
            sql = "\n".join(mysql_revoke_remote_sql(username=row.username, escape=self._db._sql_escape))
            code, _, err = self._db._run(["mysql", "-e", sql])
            if code != 0:
                skipped.append(f"{row.username}:{(err or 'fail')[-80:]}")
                continue
            row.remote_access_mode = "localhost"
            repaired.append(row.username)

        # Legacy primary MySQL on the environment row
        if (env.db_engine or "").lower() == "mysql" and env.db_username and not allow_remote:
            sql = "\n".join(mysql_revoke_remote_sql(username=env.db_username, escape=self._db._sql_escape))
            code, _, err = self._db._run(["mysql", "-e", sql])
            if code == 0:
                repaired.append(env.db_username)
            elif err:
                skipped.append(f"legacy:{(err or '')[-80:]}")

        await self._audit(
            env,
            "database_repair_remote_scope",
            {"repaired": repaired, "skipped": skipped, "allow_remote": allow_remote, "actor": actor},
        )
        await self._session.flush()
        return {"repaired": repaired, "skipped": skipped, "allow_remote": allow_remote}

    async def _audit(self, env: CustomerEnvironment, action: str, details: dict[str, Any]) -> None:
        self._session.add(
            PlatformAuditLog(
                customer_id=env.customer_id,
                action=f"environment.{action}",
                target_type="environment",
                target_id=str(env.id),
                result="success",
                metadata_json=details,
            )
        )

    @staticmethod
    def _slug(value: str) -> str:
        slug = _SLUG_RE.sub("_", value.lower().strip()).strip("_")
        return (slug[:32] or "db")

    @staticmethod
    def _db_name(engine: str, env_short: str, logical: str) -> str:
        prefix = "m" if engine == "mysql" else "p"
        base = f"{prefix}{env_short}_{logical}"[:63]
        return base
