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
from app.services.operations.cache import CacheOperationsService

router = APIRouter()


def _cache_ops(request: Request) -> CacheOperationsService:
    settings = request.app.state.container.config()
    monitoring = get_monitoring_service(request)
    return CacheOperationsService(settings, monitoring)


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
    "/refresh",
    response_model=OperationResult,
    summary="Refresh server state (clear caches, reload registry, reload nginx)",
    dependencies=[Depends(RequirePermission(Permission.SERVERS_WRITE))],
)
async def refresh_server(
    request: Request,
    _user: CurrentUser,
    reload_nginx: bool = Query(default=True),
) -> OperationResult:
    return await _cache_ops(request).refresh_server(reload_nginx=reload_nginx)


@router.post(
    "/cache/clear",
    response_model=OperationResult,
    summary="Clear central server caches and reload app registry",
    dependencies=[Depends(RequirePermission(Permission.SERVERS_WRITE))],
)
async def clear_server_cache(
    request: Request,
    _user: CurrentUser,
    reload_nginx: bool = Query(default=False),
) -> OperationResult:
    return await _cache_ops(request).clear_central(reload_nginx=reload_nginx)
