"""Unified dashboard endpoint."""

from fastapi import APIRouter, Depends, Request

from app.api.deps import CurrentUser, DbSession, RequirePermission
from app.core.permissions import Permission
from app.schemas.monitoring import DashboardResponse
from app.api.monitoring import get_monitoring_service
from app.services.inventory import InventoryService

router = APIRouter()


@router.get(
    "",
    response_model=DashboardResponse,
    summary="Control plane dashboard",
    dependencies=[Depends(RequirePermission(Permission.MONITORING_READ))],
)
async def get_dashboard(
    request: Request,
    session: DbSession,
    _user: CurrentUser,
) -> DashboardResponse:
    dashboard = await get_monitoring_service(request).get_dashboard()
    try:
        settings = request.app.state.container.config()
        inventory = await InventoryService(settings, session).get_inventory()
        return dashboard.model_copy(update={"inventory": inventory.summary})
    except Exception:
        return dashboard
