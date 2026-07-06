"""Alert monitoring endpoints."""

from fastapi import APIRouter, Depends, Request

from app.api.deps import CurrentUser, RequirePermission
from app.core.permissions import Permission
from app.schemas.monitoring import AlertsResponse
from app.api.monitoring import get_monitoring_service

router = APIRouter()


@router.get(
    "",
    response_model=AlertsResponse,
    summary="Active alerts",
    dependencies=[Depends(RequirePermission(Permission.MONITORING_READ))],
)
async def list_alerts(request: Request, _user: CurrentUser) -> AlertsResponse:
    return await get_monitoring_service(request).get_alerts()
