"""Server monitoring endpoints."""

from fastapi import APIRouter, Depends, Query, Request

from app.api.deps import CurrentUser, RequirePermission
from app.api.monitoring import get_monitoring_service
from app.core.permissions import Permission
from app.schemas.monitoring import (
    PortsResponse,
    ServerNetworkResponse,
    ServerOverviewResponse,
    ServerResourcesResponse,
)
from app.schemas.operations import OperationResult
from app.services.hosting.nginx_sites import NginxSiteManager

router = APIRouter()


@router.get(
    "/overview",
    response_model=ServerOverviewResponse,
    summary="Server overview",
    dependencies=[Depends(RequirePermission(Permission.MONITORING_READ))],
)
async def server_overview(request: Request, _user: CurrentUser) -> ServerOverviewResponse:
    return await get_monitoring_service(request).get_server_overview()


@router.get(
    "/resources",
    response_model=ServerResourcesResponse,
    summary="Server resources",
    dependencies=[Depends(RequirePermission(Permission.MONITORING_READ))],
)
async def server_resources(request: Request, _user: CurrentUser) -> ServerResourcesResponse:
    return await get_monitoring_service(request).get_server_resources()


@router.get(
    "/network",
    response_model=ServerNetworkResponse,
    summary="Server network",
    dependencies=[Depends(RequirePermission(Permission.MONITORING_READ))],
)
async def server_network(request: Request, _user: CurrentUser) -> ServerNetworkResponse:
    return await get_monitoring_service(request).get_server_network()


@router.get(
    "/ports",
    response_model=PortsResponse,
    summary="Listening ports",
    dependencies=[Depends(RequirePermission(Permission.MONITORING_READ))],
)
async def server_ports(request: Request, _user: CurrentUser) -> PortsResponse:
    return await get_monitoring_service(request).get_server_ports()


@router.post(
    "/cache/clear",
    response_model=OperationResult,
    summary="Clear server monitoring cache and reload app registry",
    dependencies=[Depends(RequirePermission(Permission.SERVERS_WRITE))],
)
async def clear_server_cache(
    request: Request,
    _user: CurrentUser,
    reload_nginx: bool = Query(default=False),
) -> OperationResult:
    monitoring = get_monitoring_service(request)
    cleared = monitoring.clear_cache()

    from app.api.applications import get_application_engine

    apps = get_application_engine(request).reload()
    details: dict = {
        "monitoring_cache": cleared,
        "applications_reloaded": len(apps),
    }

    if reload_nginx:
        settings = request.app.state.container.config()
        nginx_result = await NginxSiteManager(settings).reload()
        details["nginx"] = {"success": nginx_result.success, "message": nginx_result.message}
        if not nginx_result.success:
            return OperationResult(
                success=False,
                message=f"Cache cleared but nginx reload failed: {nginx_result.message}",
                details=details,
            )

    return OperationResult(
        success=True,
        message="Server cache cleared and application registry reloaded.",
        details=details,
    )
