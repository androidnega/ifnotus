"""Monitoring endpoints."""

from fastapi import APIRouter, Depends, Request

from app.api.deps import CurrentUser, RequirePermission
from app.core.permissions import Permission
from app.schemas.monitoring import SystemMetrics
from app.api.monitoring import get_monitoring_service

router = APIRouter()


@router.get(
    "/metrics",
    response_model=SystemMetrics,
    summary="System metrics",
    dependencies=[Depends(RequirePermission(Permission.MONITORING_READ))],
)
async def system_metrics(
    request: Request,
    _user: CurrentUser,
) -> SystemMetrics:
    """Return live host-level system metrics."""
    return await get_monitoring_service(request).get_system_metrics()


@router.get(
    "/integrations",
    summary="Integration status",
    dependencies=[Depends(RequirePermission(Permission.MONITORING_READ))],
)
async def integration_status(
    request: Request,
    _user: CurrentUser,
) -> dict:
    """Return live integration status from collectors."""
    return await get_monitoring_service(request).get_integration_status()
