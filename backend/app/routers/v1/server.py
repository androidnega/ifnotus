"""Server monitoring endpoints."""

from fastapi import APIRouter, Depends, Request

from app.api.deps import CurrentUser, RequirePermission
from app.core.permissions import Permission
from app.schemas.monitoring import (
    PortsResponse,
    ServerNetworkResponse,
    ServerOverviewResponse,
    ServerResourcesResponse,
)
from app.api.monitoring import get_monitoring_service

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
