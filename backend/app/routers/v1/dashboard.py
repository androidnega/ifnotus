"""Unified dashboard endpoint."""

from fastapi import APIRouter, Depends, Request

from app.api.deps import CurrentUser, RequirePermission
from app.core.permissions import Permission
from app.schemas.monitoring import DashboardResponse
from app.api.monitoring import get_monitoring_service

router = APIRouter()


@router.get(
    "",
    response_model=DashboardResponse,
    summary="Control plane dashboard",
    dependencies=[Depends(RequirePermission(Permission.MONITORING_READ))],
)
async def get_dashboard(request: Request, _user: CurrentUser) -> DashboardResponse:
    return await get_monitoring_service(request).get_dashboard()
