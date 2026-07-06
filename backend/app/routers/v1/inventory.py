"""VPS inventory and reconciliation endpoints."""

from fastapi import APIRouter, Depends, Request

from app.api.deps import CurrentUser, DbSession, RequirePermission
from app.core.permissions import Permission
from app.schemas.inventory import VpsInventoryResponse
from app.services.inventory import InventoryService

router = APIRouter()


def _inventory(request: Request, session: DbSession) -> InventoryService:
    settings = request.app.state.container.config()
    return InventoryService(settings, session)


@router.get(
    "",
    response_model=VpsInventoryResponse,
    summary="VPS inventory and reconciliation summary",
    dependencies=[Depends(RequirePermission(Permission.MONITORING_READ))],
)
async def get_inventory(
    request: Request,
    session: DbSession,
    _user: CurrentUser,
) -> VpsInventoryResponse:
    return await _inventory(request, session).get_inventory()
