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
        # Keep inventory cards visible with zeros rather than hiding the whole strip.
        from datetime import UTC, datetime

        from app.schemas.inventory import VpsInventorySummarySchema

        empty = VpsInventorySummarySchema(
            timestamp=datetime.now(UTC),
            registered_apps=0,
            discovered_apps=0,
            unregistered_discovered_apps=0,
            managed_domains=0,
            discovered_domains=0,
            domains_with_drift=0,
            certificates_healthy=0,
            certificates_expiring=0,
            certificates_missing=0,
            runtime_issues=0,
        )
        return dashboard.model_copy(update={"inventory": empty})
