"""Process monitoring endpoints."""

from fastapi import APIRouter, Depends, Query, Request

from app.api.deps import CurrentUser, RequirePermission
from app.core.permissions import Permission
from app.schemas.monitoring import ProcessesResponse
from app.api.monitoring import get_monitoring_service

router = APIRouter()


@router.get(
    "",
    response_model=ProcessesResponse,
    summary="Running processes",
    dependencies=[Depends(RequirePermission(Permission.MONITORING_READ))],
)
async def list_processes(
    request: Request,
    _user: CurrentUser,
    limit: int = Query(default=50, ge=1, le=200),
) -> ProcessesResponse:
    return await get_monitoring_service(request).get_processes(limit=limit)
