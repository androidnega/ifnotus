"""Log monitoring endpoints."""

from fastapi import APIRouter, Depends, Query, Request

from app.api.deps import CurrentUser, RequirePermission
from app.core.permissions import Permission
from app.schemas.monitoring import LogsResponse
from app.api.monitoring import get_monitoring_service

router = APIRouter()


@router.get(
    "",
    response_model=LogsResponse,
    summary="Recent log entries",
    dependencies=[Depends(RequirePermission(Permission.MONITORING_READ))],
)
async def get_logs(
    request: Request,
    _user: CurrentUser,
    lines: int = Query(default=100, ge=1, le=500),
) -> LogsResponse:
    return await get_monitoring_service(request).get_logs(lines=lines)
