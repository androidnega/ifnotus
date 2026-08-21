"""Security administration — firewall, blacklist, login traces, action audit."""

from datetime import UTC, datetime, timedelta
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request

from app.api.deps import AccessControlDep, CurrentUser, RequirePermission, get_auth_service
from app.core.exceptions import ValidationError
from app.core.permissions import Permission
from app.schemas.common import MessageResponse
from app.schemas.security import (
    AccessAttemptEntry,
    AccessAttemptListResponse,
    BlockedActionEntry,
    BlockedActionListResponse,
    BlockedActionUpsertRequest,
    BlockIpRequest,
    ClearSecurityLogsRequest,
    ClearSecurityLogsResponse,
    FirewallRuleCreateRequest,
    FirewallRuleEntry,
    FirewallRuleListResponse,
    IpBlacklistEntry,
    IpBlacklistListResponse,
    SystemActionLogEntry,
    SystemActionLogListResponse,
    UnlockIpRequest,
)
from app.services.auth import AuthService
from app.services.security_actions import client_ip

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
    "/blacklist",
    response_model=IpBlacklistEntry,
    dependencies=[Depends(RequirePermission(Permission.SYSTEM_ADMIN))],
)
async def block_ip(
    body: BlockIpRequest,
    access: AccessControlDep,
    user: CurrentUser,
) -> IpBlacklistEntry:
    until = None
    if body.hours:
        until = datetime.now(UTC) + timedelta(hours=body.hours)
    entry = await access.block_ip(
        ip=body.ip_address,
        reason=body.reason,
        blocked_until=until,
        blocked_by=user.id,
    )
    return IpBlacklistEntry.model_validate(entry)


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


@router.post(
    "/logs/clear",
    response_model=ClearSecurityLogsResponse,
    dependencies=[Depends(RequirePermission(Permission.SYSTEM_ADMIN))],
)
async def clear_security_logs(
    body: ClearSecurityLogsRequest,
    request: Request,
    access: AccessControlDep,
    user: CurrentUser,
    auth_service: Annotated[AuthService, Depends(get_auth_service)],
) -> ClearSecurityLogsResponse:
    """Clear persisted security logs after dashboard password confirmation.

    Requires acknowledge_downloaded=true so admins export a copy first. Host
    journal entries older than the clear are hidden rather than deleted, and a
    single audit row records that the clear happened.
    """
    if not body.acknowledge_downloaded:
        raise ValidationError(
            "Download a copy of the security logs before clearing.",
            code="DOWNLOAD_REQUIRED",
        )
    await auth_service.confirm_password(user, body.confirm_password)
    cleared = await access.clear_security_logs(
        clear_attempts=body.clear_attempts,
        clear_actions=body.clear_actions,
        clear_terminal=body.clear_terminal,
        actor_user_id=user.id,
        actor_username=user.username,
        ip_address=client_ip(request),
    )
    total = sum(cleared.values())
    return ClearSecurityLogsResponse(
        message=f"Cleared {total} security log row{'s' if total != 1 else ''}.",
        cleared=cleared,
    )


@router.get(
    "/firewall",
    response_model=FirewallRuleListResponse,
    dependencies=[Depends(RequirePermission(Permission.SYSTEM_ADMIN))],
)
async def list_firewall(
    access: AccessControlDep,
    _user: CurrentUser,
) -> FirewallRuleListResponse:
    rules = await access.list_firewall_rules()
    return FirewallRuleListResponse(
        total=len(rules),
        rules=[FirewallRuleEntry.model_validate(r) for r in rules],
    )


@router.post(
    "/firewall",
    response_model=FirewallRuleEntry,
    dependencies=[Depends(RequirePermission(Permission.SYSTEM_ADMIN))],
)
async def create_firewall_rule(
    body: FirewallRuleCreateRequest,
    access: AccessControlDep,
    user: CurrentUser,
) -> FirewallRuleEntry:
    rule = await access.create_firewall_rule(
        cidr=body.cidr,
        action=body.action,
        note=body.note,
        created_by=user.id,
    )
    return FirewallRuleEntry.model_validate(rule)


@router.delete(
    "/firewall/{rule_id}",
    response_model=MessageResponse,
    dependencies=[Depends(RequirePermission(Permission.SYSTEM_ADMIN))],
)
async def delete_firewall_rule(
    rule_id: UUID,
    access: AccessControlDep,
    _user: CurrentUser,
) -> MessageResponse:
    await access.delete_firewall_rule(rule_id)
    return MessageResponse(message="Firewall rule removed.")


@router.get(
    "/blocked-actions",
    response_model=BlockedActionListResponse,
    dependencies=[Depends(RequirePermission(Permission.SYSTEM_ADMIN))],
)
async def list_blocked_actions(
    access: AccessControlDep,
    _user: CurrentUser,
) -> BlockedActionListResponse:
    entries = await access.list_blocked_actions()
    return BlockedActionListResponse(
        total=len(entries),
        entries=[BlockedActionEntry.model_validate(e) for e in entries],
        available=access.known_blockable_actions(),
    )


@router.post(
    "/blocked-actions",
    response_model=BlockedActionEntry,
    dependencies=[Depends(RequirePermission(Permission.SYSTEM_ADMIN))],
)
async def upsert_blocked_action(
    body: BlockedActionUpsertRequest,
    access: AccessControlDep,
    user: CurrentUser,
) -> BlockedActionEntry:
    entry = await access.set_blocked_action(
        action_key=body.action_key,
        enabled=body.enabled,
        reason=body.reason,
        label=body.label,
        created_by=user.id,
    )
    return BlockedActionEntry.model_validate(entry)


@router.delete(
    "/blocked-actions/{action_key}",
    response_model=MessageResponse,
    dependencies=[Depends(RequirePermission(Permission.SYSTEM_ADMIN))],
)
async def delete_blocked_action(
    action_key: str,
    access: AccessControlDep,
    _user: CurrentUser,
) -> MessageResponse:
    await access.unblock_action(action_key)
    return MessageResponse(message=f"Action {action_key} unblocked.")


@router.get(
    "/actions",
    response_model=SystemActionLogListResponse,
    dependencies=[Depends(RequirePermission(Permission.SYSTEM_ADMIN))],
)
async def list_action_logs(
    access: AccessControlDep,
    _user: CurrentUser,
    limit: int = Query(default=200, ge=1, le=1000),
) -> SystemActionLogListResponse:
    logs = await access.list_action_logs(limit=limit)
    return SystemActionLogListResponse(
        total=len(logs),
        logs=[SystemActionLogEntry.model_validate(row) for row in logs],
    )
