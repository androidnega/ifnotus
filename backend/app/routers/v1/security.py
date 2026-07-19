"""Security administration — IP blacklist and access traces."""

from uuid import UUID

from fastapi import APIRouter, Depends, Query

from app.api.deps import AccessControlDep, CurrentUser, RequirePermission
from app.core.permissions import Permission
from app.schemas.common import MessageResponse
from app.schemas.security import (
    AccessAttemptEntry,
    AccessAttemptListResponse,
    IpBlacklistEntry,
    IpBlacklistListResponse,
    UnlockIpRequest,
)

router = APIRouter()


@router.get(
    "/blacklist",
    response_model=IpBlacklistListResponse,
    dependencies=[Depends(RequirePermission(Permission.SYSTEM_ADMIN))],
)
async def list_blacklist(
    access: AccessControlDep,
    _user: CurrentUser,
    active_only: bool = Query(default=True),
) -> IpBlacklistListResponse:
    entries = await access.list_blacklist(active_only=active_only)
    return IpBlacklistListResponse(
        total=len(entries),
        entries=[IpBlacklistEntry.model_validate(e) for e in entries],
    )


@router.post(
    "/blacklist/{entry_id}/unlock",
    response_model=MessageResponse,
    dependencies=[Depends(RequirePermission(Permission.SYSTEM_ADMIN))],
)
async def unlock_ip(
    entry_id: UUID,
    body: UnlockIpRequest,
    access: AccessControlDep,
    user: CurrentUser,
) -> MessageResponse:
    entry = await access.unlock_ip(entry_id, unlocked_by=user.id, note=body.note)
    return MessageResponse(message=f"IP {entry.ip_address} unlocked.")


@router.get(
    "/attempts",
    response_model=AccessAttemptListResponse,
    dependencies=[Depends(RequirePermission(Permission.SYSTEM_ADMIN))],
)
async def list_attempts(
    access: AccessControlDep,
    _user: CurrentUser,
    limit: int = Query(default=100, ge=1, le=500),
) -> AccessAttemptListResponse:
    attempts = await access.list_attempts(limit=limit)
    return AccessAttemptListResponse(
        total=len(attempts),
        attempts=[AccessAttemptEntry.model_validate(a) for a in attempts],
    )
