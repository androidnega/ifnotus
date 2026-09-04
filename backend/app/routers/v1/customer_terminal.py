"""Tenant portal terminal endpoints (controlled command execution)."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Query

from app.api.deps import CurrentUser, DbSession, SettingsDep, get_auth_service
from app.core.exceptions import AppException, AuthorizationError
from app.core.permissions import Role
from app.models.platform import CustomerEnvironment
from app.repositories.terminal_audit import TerminalAuditRepository
from app.schemas.hosting import TerminalAuditSchema, TerminalExecuteRequest, TerminalExecuteResponse
from app.schemas.operations import OperationResult
from app.services.auth import AuthService
from app.services.hosting.terminal import TerminalService
from app.services.platform.customers import CustomerService
from app.services.platform.tenant import TenantService

router = APIRouter()


def _require_customer_user(user) -> None:
    """Allow tenant access, but keep viewer/read-only out."""
    roles = set(user.roles or [])
    if (
        user.is_superuser
        or Role.CUSTOMER.value in roles
        or Role.PLATFORM_OWNER.value in roles
        or Role.PLATFORM_ADMIN.value in roles
        or Role.ADMIN.value in roles
        or Role.SUPERADMIN.value in roles
        or Role.HOSTING_OPERATOR.value in roles
        or Role.OPERATOR.value in roles
        or Role.BILLING_AGENT.value in roles
        or Role.SUPPORT_AGENT.value in roles
        or Role.AUDITOR.value in roles
    ):
        return
    raise AuthorizationError("Customer account required.")


@router.post(
    "/environments/{environment_id}/terminal/execute",
    response_model=TerminalExecuteResponse,
)
async def tenant_terminal_execute(
    environment_id: UUID,
    body: TerminalExecuteRequest,
    user: CurrentUser,
    session: DbSession,
    settings: SettingsDep,
    auth_service: AuthService = Depends(get_auth_service),
) -> TerminalExecuteResponse:
    _require_customer_user(user)
    customer = await CustomerService(settings, session).require_for_user(user.id)
    tenant = TenantService(session)
    env: CustomerEnvironment = await tenant.get_owned_environment(
        customer.id, environment_id, allow_suspended=False
    )

    # Terminal is allowed when the customer's pack includes SSH-capable terminal access.
    await tenant.require_capability(env, "ssh", label="Terminal")
    roots = await tenant.roots_for_environment(customer.id, environment_id)

    unix = (getattr(env, "unix_username", None) or "").strip()
    if not unix:
        raise AppException(
            "Terminal is not ready for this site yet. Try again in a moment.",
            code="terminal_unavailable",
        )

    svc = TerminalService(settings, session, only_roots=roots)
    if body.confirm_password:
        await auth_service.confirm_password(user, body.confirm_password)

    # Always run as the site account — never the API process. Timeout allows pip/npm installs.
    hosting_timeout = float(getattr(settings, "terminal_hosting_timeout", None) or 180)
    return await svc.execute(
        user,
        body.command,
        body.cwd,
        scope=body.scope,
        app_id=body.app_id,
        root_id=body.root_id,
        run_as_user=unix,
        timeout=hosting_timeout,
    )


@router.get(
    "/environments/{environment_id}/terminal/audit",
    response_model=list[TerminalAuditSchema],
)
async def tenant_terminal_audit(
    environment_id: UUID,
    user: CurrentUser,
    session: DbSession,
    settings: SettingsDep,
    limit: int = Query(default=50, ge=1, le=200),
) -> list[TerminalAuditSchema]:
    _require_customer_user(user)
    customer = await CustomerService(settings, session).require_for_user(user.id)
    tenant = TenantService(session)
    env: CustomerEnvironment = await tenant.get_owned_environment(
        customer.id, environment_id, allow_suspended=False
    )

    await tenant.require_capability(env, "ssh", label="Terminal")

    logs = await TerminalAuditRepository(session).list_for_user(user.id, limit=limit)
    return [
        TerminalAuditSchema(
            id=log.id,
            username=log.username,
            command=log.command,
            exit_code=log.exit_code,
            success=log.success,
            output_preview=log.output_preview,
            executed_at=log.executed_at,
        )
        for log in logs
    ]


@router.delete(
    "/environments/{environment_id}/terminal/audit",
    response_model=OperationResult,
    summary="Clear tenant terminal audit logs",
)
async def tenant_terminal_clear_audit(
    environment_id: UUID,
    user: CurrentUser,
    session: DbSession,
    settings: SettingsDep,
) -> OperationResult:
    _require_customer_user(user)
    customer = await CustomerService(settings, session).require_for_user(user.id)
    tenant = TenantService(session)
    env: CustomerEnvironment = await tenant.get_owned_environment(
        customer.id, environment_id, allow_suspended=False
    )
    await tenant.require_capability(env, "ssh", label="Terminal")

    deleted = await TerminalAuditRepository(session).clear_for_user(user.id)
    return OperationResult(
        success=True,
        message=f"Cleared {deleted} terminal audit log{'s' if deleted != 1 else ''}.",
        details={"deleted": deleted},
    )

