"""Database management endpoints — create, browse, query MySQL/PostgreSQL/SQLite/MongoDB."""

from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any

from fastapi import APIRouter, Depends, File, Form, Query, Request, UploadFile
from fastapi.responses import FileResponse

from app.api.deps import CurrentUser, DbSession, RequirePermission, get_auth_service
from app.core.exceptions import AppException, AuthorizationError
from app.core.permissions import Permission
from app.models.platform import PlatformAuditLog
from app.schemas.auth import AuthenticatedUser
from app.schemas.databases import (
    DatabaseAdoptRequest,
    DatabaseBackupListResponse,
    DatabaseBackupRequest,
    DatabaseBackupSchema,
    DatabaseCreateRequest,
    DatabaseCreatedResponse,
    DatabaseDropOptions,
    DatabaseDropRequest,
    DatabaseEngine,
    DatabaseListResponse,
    DatabaseLiveDropRequest,
    DatabasePasswordResponse,
    DatabaseRestoreRequest,
    DbQueryRequest,
    DbQueryResponse,
    DbRowMutationRequest,
    DbRowsRequest,
    DbSchemaResponse,
    EngineStatusSchema,
)
from app.schemas.operations import OperationResult
from app.services.auth import AuthService
from app.services.hosting.databases import DatabaseManagerService
from app.services.hosting.db_studio import DatabaseStudioService

router = APIRouter()


def _db_service(request: Request) -> DatabaseManagerService:
    return DatabaseManagerService(request.app.state.container.config())


def _studio(request: Request) -> DatabaseStudioService:
    return DatabaseStudioService(_db_service(request))


async def _gate_staff_studio_write(
    *,
    user: AuthenticatedUser,
    auth_service: AuthService,
    body: DbQueryRequest,
    engine: str,
    database: str,
    target_id: str | None = None,
) -> str:
    """Enforce read vs write permission and destructive password confirm (PHASE 38I).

    Returns query_class: read | write | destructive.
    """
    qclass = DatabaseStudioService.query_class(
        sql=body.sql, script=body.script, engine=engine
    )
    if qclass == "read":
        return qclass
    if not auth_service.user_has_permission(user, Permission.DATABASES_WRITE.value):
        raise AuthorizationError(
            "Permission 'databases:write' required for write or DDL queries."
        )
    if qclass == "destructive":
        if not (body.confirm_password or "").strip():
            raise AppException(
                "Confirm your dashboard password to run destructive SQL (CREATE/ALTER/DROP/…).",
                code="db_confirm_required",
            )
        await auth_service.confirm_password(user, body.confirm_password)
    return qclass


def _audit_studio_write(
    session: Any,
    user: AuthenticatedUser,
    *,
    query_class: str,
    engine: str,
    database: str,
    target_id: str | None,
    body: DbQueryRequest,
) -> None:
    if query_class == "read":
        return
    verb = DatabaseStudioService.sql_verb(body.sql or body.script or "")
    session.add(
        PlatformAuditLog(
            customer_id=None,
            actor_id=user.id,
            action="database.studio_write",
            target_type="database",
            target_id=(target_id or database)[:64],
            result="success",
            metadata_json={
                "query_class": query_class,
                "engine": engine,
                "database": database[:128],
                "verb": verb,
                "actor": user.username,
            },
        )
    )


def _audit_row_mutation(
    session: Any,
    user: AuthenticatedUser,
    *,
    action: str,
    engine: str,
    database: str,
    target_id: str | None,
    table: str | None,
) -> None:
    session.add(
        PlatformAuditLog(
            customer_id=None,
            actor_id=user.id,
            action=f"database.studio_{action}",
            target_type="database",
            target_id=(target_id or database)[:64],
            result="success",
            metadata_json={
                "query_class": "write",
                "engine": engine,
                "database": database[:128],
                "table": (table or "")[:128] or None,
                "actor": user.username,
            },
        )
    )

@router.get(
    "",
    response_model=DatabaseListResponse,
    dependencies=[Depends(RequirePermission(Permission.DATABASES_READ))],
)
async def list_databases(request: Request, _user: CurrentUser) -> DatabaseListResponse:
    return await _db_service(request).overview()


@router.get(
    "/engines",
    response_model=list[EngineStatusSchema],
    dependencies=[Depends(RequirePermission(Permission.DATABASES_READ))],
)
async def list_engines(request: Request, _user: CurrentUser) -> list[EngineStatusSchema]:
    overview = await _db_service(request).overview()
    return overview.engines


@router.post(
    "",
    response_model=DatabaseCreatedResponse,
    dependencies=[Depends(RequirePermission(Permission.DATABASES_WRITE))],
)
async def create_database(
    body: DatabaseCreateRequest,
    request: Request,
    _user: CurrentUser,
) -> DatabaseCreatedResponse:
    return await _db_service(request).create(body)


@router.post(
    "/engines/{engine}/ensure",
    response_model=OperationResult,
    dependencies=[Depends(RequirePermission(Permission.DATABASES_WRITE))],
)
async def ensure_engine(
    engine: str,
    request: Request,
    _user: CurrentUser,
) -> OperationResult:
    return await _db_service(request).ensure_engine(engine)


@router.post(
    "/adopt",
    response_model=DatabaseCreatedResponse,
    dependencies=[Depends(RequirePermission(Permission.DATABASES_WRITE))],
)
async def adopt_database(
    body: DatabaseAdoptRequest,
    request: Request,
    _user: CurrentUser,
) -> DatabaseCreatedResponse:
    return await _db_service(request).adopt(body)


@router.get(
    "/backups",
    response_model=DatabaseBackupListResponse,
    dependencies=[Depends(RequirePermission(Permission.DATABASES_READ))],
)
async def list_backups(request: Request, _user: CurrentUser) -> DatabaseBackupListResponse:
    return DatabaseBackupListResponse(backups=await _db_service(request).list_backups())


@router.get(
    "/backups/{backup_id}/download",
    dependencies=[Depends(RequirePermission(Permission.DATABASES_READ))],
)
async def download_backup(backup_id: str, request: Request, _user: CurrentUser) -> FileResponse:
    path = _db_service(request).resolve_backup_file(backup_id)
    return FileResponse(path, filename=path.name, media_type="application/octet-stream")


@router.post(
    "/live/backup",
    response_model=DatabaseBackupSchema,
    dependencies=[Depends(RequirePermission(Permission.DATABASES_WRITE))],
)
async def backup_live_database(
    body: DatabaseBackupRequest,
    request: Request,
    _user: CurrentUser,
) -> DatabaseBackupSchema:
    if not body.engine or not body.name:
        from app.core.exceptions import AppException

        raise AppException("engine and name are required", code="db_backup_target")
    return await _db_service(request).backup_live(engine=body.engine, name=body.name, path=body.path)


@router.post(
    "/restore",
    response_model=OperationResult,
    dependencies=[Depends(RequirePermission(Permission.DATABASES_WRITE))],
)
async def restore_database(
    request: Request,
    user: CurrentUser,
    auth_service: AuthService = Depends(get_auth_service),
    confirm_password: str = Form(...),
    engine: DatabaseEngine = Form(...),
    name: str = Form(...),
    path: str | None = Form(None),
    backup_id: str | None = Form(None),
    create_if_missing: bool = Form(True),
    file: UploadFile | None = File(None),
) -> OperationResult:
    await auth_service.confirm_password(user, confirm_password)
    body = DatabaseRestoreRequest(
        confirm_password=confirm_password,
        engine=engine,
        name=name,
        path=path,
        backup_id=backup_id,
        create_if_missing=create_if_missing,
    )
    upload_path: Path | None = None
    tmp: NamedTemporaryFile | None = None
    try:
        if file is not None and file.filename:
            tmp = NamedTemporaryFile(delete=False, suffix=Path(file.filename).suffix or ".dump")
            tmp.write(await file.read())
            tmp.flush()
            upload_path = Path(tmp.name)
        return await _db_service(request).restore(body, upload_path)
    finally:
        if tmp is not None:
            tmp.close()
            try:
                Path(tmp.name).unlink(missing_ok=True)
            except OSError:
                pass


@router.post(
    "/live/drop",
    response_model=OperationResult,
    dependencies=[Depends(RequirePermission(Permission.DATABASES_WRITE))],
)
async def drop_live_database(
    body: DatabaseLiveDropRequest,
    request: Request,
    user: CurrentUser,
    auth_service: AuthService = Depends(get_auth_service),
) -> OperationResult:
    await auth_service.confirm_password(user, body.confirm_password)
    return await _db_service(request).drop_live(body)


# ── Live studio (before /{db_id} routes) ───────────────────────────────────


@router.get(
    "/live/{engine}/{name}/schema",
    response_model=DbSchemaResponse,
    dependencies=[Depends(RequirePermission(Permission.DATABASES_READ))],
)
async def live_schema(
    engine: DatabaseEngine,
    name: str,
    request: Request,
    _user: CurrentUser,
    path: str | None = None,
) -> DbSchemaResponse:
    return await _studio(request).schema_live(engine, name, path)


@router.get(
    "/live/{engine}/{name}/rows",
    response_model=DbQueryResponse,
    dependencies=[Depends(RequirePermission(Permission.DATABASES_READ))],
)
async def live_rows(
    engine: DatabaseEngine,
    name: str,
    request: Request,
    _user: CurrentUser,
    table: str | None = None,
    collection: str | None = None,
    schema_name: str | None = None,
    path: str | None = None,
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
) -> DbQueryResponse:
    body = DbRowsRequest(
        table=table, collection=collection, schema_name=schema_name, limit=limit, offset=offset
    )
    return await _studio(request).rows_live(engine, name, body, path)


@router.post(
    "/live/{engine}/{name}/query",
    response_model=DbQueryResponse,
    dependencies=[Depends(RequirePermission(Permission.DATABASES_READ))],
)
async def live_query(
    engine: DatabaseEngine,
    name: str,
    body: DbQueryRequest,
    request: Request,
    user: CurrentUser,
    session: DbSession,
    path: str | None = None,
    auth_service: AuthService = Depends(get_auth_service),
) -> DbQueryResponse:
    qclass = await _gate_staff_studio_write(
        user=user,
        auth_service=auth_service,
        body=body,
        engine=engine,
        database=name,
        target_id=f"live:{engine}:{name}",
    )
    result = await _studio(request).query_live(engine, name, body, path)
    _audit_studio_write(
        session,
        user,
        query_class=qclass,
        engine=engine,
        database=name,
        target_id=f"live:{engine}:{name}",
        body=body,
    )
    return result


@router.post(
    "/live/{engine}/{name}/rows/insert",
    response_model=DbQueryResponse,
    dependencies=[Depends(RequirePermission(Permission.DATABASES_WRITE))],
)
async def live_insert_row(
    engine: DatabaseEngine,
    name: str,
    body: DbRowMutationRequest,
    request: Request,
    user: CurrentUser,
    session: DbSession,
    path: str | None = None,
) -> DbQueryResponse:
    result = await _studio(request).insert_row_live(engine, name, body, path)
    _audit_row_mutation(
        session,
        user,
        action="insert",
        engine=engine,
        database=name,
        target_id=f"live:{engine}:{name}",
        table=body.table or body.collection,
    )
    return result


@router.patch(
    "/live/{engine}/{name}/rows",
    response_model=DbQueryResponse,
    dependencies=[Depends(RequirePermission(Permission.DATABASES_WRITE))],
)
async def live_update_row(
    engine: DatabaseEngine,
    name: str,
    body: DbRowMutationRequest,
    request: Request,
    user: CurrentUser,
    session: DbSession,
    path: str | None = None,
) -> DbQueryResponse:
    result = await _studio(request).update_row_live(engine, name, body, path)
    _audit_row_mutation(
        session,
        user,
        action="update",
        engine=engine,
        database=name,
        target_id=f"live:{engine}:{name}",
        table=body.table or body.collection,
    )
    return result


@router.post(
    "/live/{engine}/{name}/rows/delete",
    response_model=DbQueryResponse,
    dependencies=[Depends(RequirePermission(Permission.DATABASES_WRITE))],
)
async def live_delete_row(
    engine: DatabaseEngine,
    name: str,
    body: DbRowMutationRequest,
    request: Request,
    user: CurrentUser,
    session: DbSession,
    path: str | None = None,
) -> DbQueryResponse:
    result = await _studio(request).delete_row_live(engine, name, body, path)
    _audit_row_mutation(
        session,
        user,
        action="delete",
        engine=engine,
        database=name,
        target_id=f"live:{engine}:{name}",
        table=body.table or body.collection,
    )
    return result


# ── Managed studio ─────────────────────────────────────────────────────────


@router.get(
    "/{db_id}/schema",
    response_model=DbSchemaResponse,
    dependencies=[Depends(RequirePermission(Permission.DATABASES_READ))],
)
async def managed_schema(db_id: str, request: Request, _user: CurrentUser) -> DbSchemaResponse:
    return await _studio(request).schema_managed(db_id)


@router.get(
    "/{db_id}/rows",
    response_model=DbQueryResponse,
    dependencies=[Depends(RequirePermission(Permission.DATABASES_READ))],
)
async def managed_rows(
    db_id: str,
    request: Request,
    _user: CurrentUser,
    table: str | None = None,
    collection: str | None = None,
    schema_name: str | None = None,
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
) -> DbQueryResponse:
    body = DbRowsRequest(
        table=table, collection=collection, schema_name=schema_name, limit=limit, offset=offset
    )
    return await _studio(request).rows_managed(db_id, body)


@router.post(
    "/{db_id}/query",
    response_model=DbQueryResponse,
    dependencies=[Depends(RequirePermission(Permission.DATABASES_READ))],
)
async def managed_query(
    db_id: str,
    body: DbQueryRequest,
    request: Request,
    user: CurrentUser,
    session: DbSession,
    auth_service: AuthService = Depends(get_auth_service),
) -> DbQueryResponse:
    conn = _studio(request)._managed(db_id)
    engine = str(conn.get("engine") or "mysql")
    database = str(conn.get("name") or db_id)
    qclass = await _gate_staff_studio_write(
        user=user,
        auth_service=auth_service,
        body=body,
        engine=engine,
        database=database,
        target_id=db_id,
    )
    result = await _studio(request).query_managed(db_id, body)
    _audit_studio_write(
        session,
        user,
        query_class=qclass,
        engine=engine,
        database=database,
        target_id=db_id,
        body=body,
    )
    return result


@router.post(
    "/{db_id}/rows/insert",
    response_model=DbQueryResponse,
    dependencies=[Depends(RequirePermission(Permission.DATABASES_WRITE))],
)
async def managed_insert_row(
    db_id: str,
    body: DbRowMutationRequest,
    request: Request,
    user: CurrentUser,
    session: DbSession,
) -> DbQueryResponse:
    conn = _studio(request)._managed(db_id)
    result = await _studio(request).insert_row_managed(db_id, body)
    _audit_row_mutation(
        session,
        user,
        action="insert",
        engine=str(conn.get("engine") or ""),
        database=str(conn.get("name") or db_id),
        target_id=db_id,
        table=body.table or body.collection,
    )
    return result


@router.patch(
    "/{db_id}/rows",
    response_model=DbQueryResponse,
    dependencies=[Depends(RequirePermission(Permission.DATABASES_WRITE))],
)
async def managed_update_row(
    db_id: str,
    body: DbRowMutationRequest,
    request: Request,
    user: CurrentUser,
    session: DbSession,
) -> DbQueryResponse:
    conn = _studio(request)._managed(db_id)
    result = await _studio(request).update_row_managed(db_id, body)
    _audit_row_mutation(
        session,
        user,
        action="update",
        engine=str(conn.get("engine") or ""),
        database=str(conn.get("name") or db_id),
        target_id=db_id,
        table=body.table or body.collection,
    )
    return result


@router.post(
    "/{db_id}/rows/delete",
    response_model=DbQueryResponse,
    dependencies=[Depends(RequirePermission(Permission.DATABASES_WRITE))],
)
async def managed_delete_row(
    db_id: str,
    body: DbRowMutationRequest,
    request: Request,
    user: CurrentUser,
    session: DbSession,
) -> DbQueryResponse:
    conn = _studio(request)._managed(db_id)
    result = await _studio(request).delete_row_managed(db_id, body)
    _audit_row_mutation(
        session,
        user,
        action="delete",
        engine=str(conn.get("engine") or ""),
        database=str(conn.get("name") or db_id),
        target_id=db_id,
        table=body.table or body.collection,
    )
    return result


@router.post(
    "/{db_id}/backup",
    response_model=DatabaseBackupSchema,
    dependencies=[Depends(RequirePermission(Permission.DATABASES_WRITE))],
)
async def backup_managed_database(
    db_id: str,
    request: Request,
    _user: CurrentUser,
) -> DatabaseBackupSchema:
    return await _db_service(request).backup_managed(db_id)


@router.post(
    "/{db_id}/drop",
    response_model=OperationResult,
    dependencies=[Depends(RequirePermission(Permission.DATABASES_WRITE))],
)
async def drop_database(
    db_id: str,
    body: DatabaseDropRequest,
    request: Request,
    user: CurrentUser,
    auth_service: AuthService = Depends(get_auth_service),
) -> OperationResult:
    await auth_service.confirm_password(user, body.confirm_password)
    return await _db_service(request).drop(
        db_id,
        DatabaseDropOptions(drop_user=body.drop_user, remove_files=body.remove_files),
    )


@router.delete(
    "/{db_id}",
    response_model=OperationResult,
    dependencies=[Depends(RequirePermission(Permission.DATABASES_WRITE))],
    deprecated=True,
)
async def drop_database_legacy(
    db_id: str,
    body: DatabaseDropRequest,
    request: Request,
    user: CurrentUser,
    auth_service: AuthService = Depends(get_auth_service),
) -> OperationResult:
    await auth_service.confirm_password(user, body.confirm_password)
    return await _db_service(request).drop(
        db_id,
        DatabaseDropOptions(drop_user=body.drop_user, remove_files=body.remove_files),
    )


@router.post(
    "/{db_id}/password",
    response_model=DatabasePasswordResponse,
    dependencies=[Depends(RequirePermission(Permission.DATABASES_WRITE))],
)
async def reveal_password(
    db_id: str,
    request: Request,
    _user: CurrentUser,
) -> DatabasePasswordResponse:
    return await _db_service(request).reveal_password(db_id)
