"""Managed services monitoring endpoints."""

from fastapi import APIRouter, Depends, Request

from app.api.deps import CurrentUser, RequirePermission
from app.core.permissions import Permission
from app.schemas.monitoring import ServicesResponse
from app.api.monitoring import get_monitoring_service

router = APIRouter()


@router.get(
    "",
    response_model=ServicesResponse,
    summary="Managed services",
    dependencies=[Depends(RequirePermission(Permission.MONITORING_READ))],
)
async def list_services(request: Request, _user: CurrentUser) -> ServicesResponse:
    return await get_monitoring_service(request).get_services()
