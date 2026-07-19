"""Terminal command execution endpoints."""

from fastapi import APIRouter, Depends, Query, Request

from app.api.deps import CurrentUser, DbSession, RequirePermission
from app.core.permissions import Permission
from app.schemas.hosting import TerminalAuditSchema, TerminalExecuteRequest, TerminalExecuteResponse
from app.schemas.operations import OperationResult
from app.services.hosting.terminal import TerminalService

router = APIRouter()


def _terminal(request: Request, session: DbSession) -> TerminalService:
    settings = request.app.state.container.config()
    return TerminalService(settings, session)


@router.post(
    "/execute",
    response_model=TerminalExecuteResponse,
    dependencies=[Depends(RequirePermission(Permission.TERMINAL_EXECUTE))],
)
async def execute_command(
    body: TerminalExecuteRequest,
    request: Request,
    session: DbSession,
    user: CurrentUser,
) -> TerminalExecuteResponse:
    return await _terminal(request, session).execute(
        user,
        body.command,
        body.cwd,
        scope=body.scope,
        app_id=body.app_id,
        root_id=body.root_id,
    )


@router.get(
    "/audit",
    response_model=list[TerminalAuditSchema],
    dependencies=[Depends(RequirePermission(Permission.TERMINAL_EXECUTE))],
)
async def audit_log(
    request: Request,
    session: DbSession,
    _user: CurrentUser,
    limit: int = Query(default=50, ge=1, le=200),
) -> list[TerminalAuditSchema]:
    return await _terminal(request, session).list_audit(limit)


@router.delete(
    "/audit",
    response_model=OperationResult,
    summary="Clear terminal audit logs",
    dependencies=[Depends(RequirePermission(Permission.TERMINAL_EXECUTE))],
)
async def clear_audit_log(
    request: Request,
    session: DbSession,
    _user: CurrentUser,
) -> OperationResult:
    deleted = await _terminal(request, session).clear_audit()
    return OperationResult(
        success=True,
        message=f"Cleared {deleted} terminal audit log{'s' if deleted != 1 else ''}.",
        details={"deleted": deleted},
    )
