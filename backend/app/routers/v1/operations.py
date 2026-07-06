"""Platform operations endpoints."""

from fastapi import APIRouter, Depends, Query, Request

from app.api.deps import CurrentUser, RequirePermission, get_auth_service
from app.api.operations import get_operations_service
from app.core.permissions import Permission
from app.services.auth import AuthService
from app.schemas.common import MessageResponse
from app.schemas.operations import (
    BackupsResponse,
    CronResponse,
    DatabaseResponse,
    EnvironmentResponse,
    FileListResponse,
    OperationResult,
    OperationsOverview,
    QueueStatus,
    SmtpTestRequest,
    StorageResponse,
)

router = APIRouter()


@router.get(
    "/overview",
    response_model=OperationsOverview,
    dependencies=[Depends(RequirePermission(Permission.SYSTEM_READ))],
)
async def operations_overview(request: Request, _user: CurrentUser) -> OperationsOverview:
    return await get_operations_service(request).overview()


@router.get(
    "/environment",
    response_model=EnvironmentResponse,
    dependencies=[Depends(RequirePermission(Permission.SYSTEM_READ))],
)
async def platform_environment(
    request: Request,
    user: CurrentUser,
    auth_service: AuthService = Depends(get_auth_service),
    reveal: bool = Query(default=False),
) -> EnvironmentResponse:
    if reveal and not auth_service.user_has_permission(user, Permission.SYSTEM_ADMIN.value):
        from app.core.exceptions import AuthorizationError

        raise AuthorizationError("Permission 'system:admin' required to reveal secrets.")
    return await get_operations_service(request).platform_environment(reveal=reveal)


@router.post(
    "/smtp/test",
    response_model=OperationResult,
    dependencies=[Depends(RequirePermission(Permission.EMAIL_WRITE))],
)
async def smtp_test(
    body: SmtpTestRequest,
    request: Request,
    _user: CurrentUser,
) -> OperationResult:
    return await get_operations_service(request).test_smtp(body.to_email, body.subject, body.body)


@router.post(
    "/nginx/restart",
    response_model=OperationResult,
    dependencies=[Depends(RequirePermission(Permission.SERVERS_WRITE))],
)
async def restart_nginx(request: Request, _user: CurrentUser) -> OperationResult:
    return await get_operations_service(request).restart_nginx()


@router.post(
    "/worker/restart",
    response_model=OperationResult,
    dependencies=[Depends(RequirePermission(Permission.SERVERS_WRITE))],
)
async def restart_worker(request: Request, _user: CurrentUser) -> OperationResult:
    return await get_operations_service(request).restart_worker()


@router.get(
    "/queue",
    response_model=list[QueueStatus],
    dependencies=[Depends(RequirePermission(Permission.SYSTEM_READ))],
)
async def queue_status(request: Request, _user: CurrentUser) -> list[QueueStatus]:
    return await get_operations_service(request).queue_status()


@router.get(
    "/backups",
    response_model=BackupsResponse,
    dependencies=[Depends(RequirePermission(Permission.SYSTEM_READ))],
)
async def list_backups(request: Request, _user: CurrentUser) -> BackupsResponse:
    return await get_operations_service(request).list_backups()


@router.post(
    "/backups",
    response_model=OperationResult,
    dependencies=[Depends(RequirePermission(Permission.SYSTEM_ADMIN))],
)
async def create_backup(
    request: Request,
    _user: CurrentUser,
    name: str | None = Query(default=None),
) -> OperationResult:
    return await get_operations_service(request).create_backup(name)


@router.get(
    "/cron",
    response_model=CronResponse,
    dependencies=[Depends(RequirePermission(Permission.SYSTEM_READ))],
)
async def list_cron(request: Request, _user: CurrentUser) -> CronResponse:
    return await get_operations_service(request).list_cron()


@router.get(
    "/files",
    response_model=FileListResponse,
    dependencies=[Depends(RequirePermission(Permission.SYSTEM_READ))],
)
async def list_files(
    request: Request,
    _user: CurrentUser,
    path: str = Query(default="."),
    app_id: str | None = Query(default=None),
) -> FileListResponse:
    return await get_operations_service(request).list_files(path, app_id=app_id)


@router.get(
    "/storage",
    response_model=StorageResponse,
    dependencies=[Depends(RequirePermission(Permission.SYSTEM_READ))],
)
async def storage_check(request: Request, _user: CurrentUser) -> StorageResponse:
    return await get_operations_service(request).storage_check()


@router.get(
    "/ssl",
    dependencies=[Depends(RequirePermission(Permission.SYSTEM_READ))],
)
async def ssl_status(request: Request, _user: CurrentUser) -> list[dict]:
    return await get_operations_service(request).ssl_status()


@router.get(
    "/database",
    response_model=DatabaseResponse,
    dependencies=[Depends(RequirePermission(Permission.SYSTEM_READ))],
)
async def database_status(request: Request, _user: CurrentUser) -> DatabaseResponse:
    return await get_operations_service(request).database_status()


@router.post(
    "/database/{action}",
    response_model=OperationResult,
    dependencies=[Depends(RequirePermission(Permission.SYSTEM_ADMIN))],
)
async def database_action(
    action: str,
    request: Request,
    _user: CurrentUser,
) -> OperationResult:
    return await get_operations_service(request).database_action(action)


@router.get(
    "/logs/host",
    dependencies=[Depends(RequirePermission(Permission.MONITORING_READ))],
)
async def host_logs(
    request: Request,
    _user: CurrentUser,
    lines: int = Query(default=100, ge=1, le=500),
):
    from app.api.monitoring import get_monitoring_service

    return await get_monitoring_service(request).get_logs(lines=lines)
