"""Application management endpoints."""

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel

from app.api.applications import get_application_engine
from app.api.deps import CurrentUser, RequirePermission
from app.api.operations import get_application_actions
from app.core.permissions import Permission
from app.schemas.applications import (
    ApplicationDeploymentsResponse,
    ApplicationDetailSchema,
    ApplicationEnvironmentResponse,
    ApplicationHealthSchema,
    ApplicationListResponse,
    ApplicationLogsResponse,
    ApplicationMetricsSchema,
)
from app.schemas.operations import OperationResult

router = APIRouter()


class DeployRequest(BaseModel):
    version: str | None = None
    message: str | None = None
    pull: bool = True
    restart: bool = True


class ServiceActionRequest(BaseModel):
    action: str  # start | stop | restart | enable | disable


class AppEnableRequest(BaseModel):
    enabled: bool


@router.get(
    "",
    response_model=ApplicationListResponse,
    summary="List registered applications",
    dependencies=[Depends(RequirePermission(Permission.APPS_READ))],
)
async def list_applications(
    request: Request,
    _user: CurrentUser,
) -> ApplicationListResponse:
    return await get_application_engine(request).list_applications()


@router.get(
    "/{app_id}",
    response_model=ApplicationDetailSchema,
    summary="Get application details",
    dependencies=[Depends(RequirePermission(Permission.APPS_READ))],
)
async def get_application(
    app_id: str,
    request: Request,
    _user: CurrentUser,
) -> ApplicationDetailSchema:
    return await get_application_engine(request).get_application(app_id)


@router.get(
    "/{app_id}/health",
    response_model=ApplicationHealthSchema,
    summary="Get application health",
    dependencies=[Depends(RequirePermission(Permission.APPS_READ))],
)
async def get_application_health(
    app_id: str,
    request: Request,
    _user: CurrentUser,
) -> ApplicationHealthSchema:
    return await get_application_engine(request).get_health(app_id)


@router.get(
    "/{app_id}/metrics",
    response_model=ApplicationMetricsSchema,
    summary="Get application metrics",
    dependencies=[Depends(RequirePermission(Permission.APPS_READ))],
)
async def get_application_metrics(
    app_id: str,
    request: Request,
    _user: CurrentUser,
) -> ApplicationMetricsSchema:
    return await get_application_engine(request).get_metrics(app_id)


@router.get(
    "/{app_id}/logs",
    response_model=ApplicationLogsResponse,
    summary="Get application logs",
    dependencies=[Depends(RequirePermission(Permission.APPS_READ))],
)
async def get_application_logs(
    app_id: str,
    request: Request,
    _user: CurrentUser,
    lines: int = Query(default=100, ge=1, le=500),
) -> ApplicationLogsResponse:
    return await get_application_engine(request).get_logs(app_id, lines=lines)


@router.get(
    "/{app_id}/environment",
    response_model=ApplicationEnvironmentResponse,
    summary="Get application environment keys",
    dependencies=[Depends(RequirePermission(Permission.APPS_READ))],
)
async def get_application_environment(
    app_id: str,
    request: Request,
    _user: CurrentUser,
) -> ApplicationEnvironmentResponse:
    return await get_application_engine(request).get_environment(app_id)


@router.get(
    "/{app_id}/deployments",
    response_model=ApplicationDeploymentsResponse,
    summary="Get application deployment history",
    dependencies=[Depends(RequirePermission(Permission.DEPLOYMENTS_READ))],
)
async def get_application_deployments(
    app_id: str,
    request: Request,
    _user: CurrentUser,
) -> ApplicationDeploymentsResponse:
    return await get_application_engine(request).get_deployments(app_id)


@router.get(
    "/{app_id}/environment/reveal",
    dependencies=[Depends(RequirePermission(Permission.SYSTEM_ADMIN))],
)
async def reveal_application_environment(
    app_id: str,
    request: Request,
    _user: CurrentUser,
) -> dict[str, str]:
    return await get_application_actions(request).reveal_environment(app_id)


@router.post(
    "/{app_id}/git/pull",
    response_model=OperationResult,
    dependencies=[Depends(RequirePermission(Permission.DEPLOYMENTS_EXECUTE))],
)
async def git_pull(
    app_id: str,
    request: Request,
    user: CurrentUser,
) -> OperationResult:
    return await get_application_actions(request).git_pull(app_id, triggered_by=user.username)


@router.post(
    "/{app_id}/deploy",
    response_model=OperationResult,
    dependencies=[Depends(RequirePermission(Permission.DEPLOYMENTS_EXECUTE))],
)
async def deploy_application(
    app_id: str,
    body: DeployRequest,
    request: Request,
    user: CurrentUser,
) -> OperationResult:
    return await get_application_actions(request).deploy(
        app_id,
        version=body.version,
        message=body.message,
        triggered_by=user.username,
        pull=body.pull,
        restart=body.restart,
    )


@router.post(
    "/{app_id}/deployments/{deployment_id}/redeploy",
    response_model=OperationResult,
    dependencies=[Depends(RequirePermission(Permission.DEPLOYMENTS_EXECUTE))],
)
async def redeploy_application(
    app_id: str,
    deployment_id: str,
    request: Request,
    user: CurrentUser,
) -> OperationResult:
    return await get_application_actions(request).redeploy(
        app_id, deployment_id, triggered_by=user.username
    )


@router.post(
    "/{app_id}/restart",
    response_model=OperationResult,
    dependencies=[Depends(RequirePermission(Permission.SERVERS_WRITE))],
)
async def restart_application(
    app_id: str,
    request: Request,
    user: CurrentUser,
) -> OperationResult:
    return await get_application_actions(request).restart_app(app_id, triggered_by=user.username)


@router.post(
    "/{app_id}/services/action",
    response_model=OperationResult,
    dependencies=[Depends(RequirePermission(Permission.SERVERS_WRITE))],
)
async def application_service_action(
    app_id: str,
    body: ServiceActionRequest,
    request: Request,
    user: CurrentUser,
) -> OperationResult:
    return await get_application_actions(request).service_control(
        app_id, body.action, triggered_by=user.username
    )


@router.patch(
    "/{app_id}",
    response_model=OperationResult,
    dependencies=[Depends(RequirePermission(Permission.APPS_WRITE))],
)
async def set_application_enabled(
    app_id: str,
    body: AppEnableRequest,
    request: Request,
    _user: CurrentUser,
) -> OperationResult:
    return await get_application_actions(request).set_enabled(app_id, body.enabled)
