"""DeepSeek AI agent endpoints."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse

from app.api.deps import CurrentUser, DbSession, RequirePermission, get_auth_service
from app.core.config import Settings
from app.core.exceptions import AppException, AuthorizationError, NotFoundError
from app.core.permissions import Permission
from jose import JWTError, jwt
from app.schemas.ai import (
    AiApplyActionRequest,
    AiChatRequest,
    AiChatResponse,
    AiSessionCreateRequest,
    AiSessionDetail,
    AiSessionListResponse,
    AiSessionSummary,
    AiSettingsResponse,
    AiSettingsUpdateRequest,
)
from app.schemas.operations import OperationResult
from app.services.ai.agent import DeepSeekAgentService
from app.services.ai.memory import AiMemoryStore
from app.services.ai.settings_store import AiSettingsStore
from app.services.auth import AuthService
from app.services.hosting.files import FileManagerService
from app.services.hosting.terminal import TerminalService

router = APIRouter()


def _settings_store(request: Request) -> AiSettingsStore:
    return AiSettingsStore(request.app.state.container.config())


def _memory(request: Request) -> AiMemoryStore:
    return AiMemoryStore(request.app.state.container.config())


def _agent(request: Request, session: DbSession) -> DeepSeekAgentService:
    settings = request.app.state.container.config()
    files = FileManagerService(settings)
    terminal = TerminalService(settings, session)
    monitoring = request.app.state.container.monitoring_service()
    return DeepSeekAgentService(settings, files, terminal, monitoring)


async def _require_drop_password(
    body: AiApplyActionRequest,
    user: CurrentUser,
    auth_service: AuthService,
    settings: Settings,
) -> None:
    try:
        payload = jwt.decode(
            body.token,
            settings.secret_key,
            algorithms=[settings.jwt_algorithm],
        )
    except JWTError as exc:
        raise AppException("Invalid or expired action token.", code="ai_action_invalid") from exc
    action = payload.get("action") or {}
    if action.get("type") != "drop_database":
        return
    if not body.confirm_password:
        raise AppException(
            "Dashboard password is required to drop a database.",
            code="db_password_required",
        )
    await auth_service.confirm_password(user, body.confirm_password)


def _sse(events: AsyncIterator[dict]) -> StreamingResponse:
    async def gen() -> AsyncIterator[str]:
        try:
            async for event in events:
                yield f"data: {json.dumps(event, default=str)}\n\n"
            yield "data: [DONE]\n\n"
        except Exception as exc:  # noqa: BLE001
            yield f"data: {json.dumps({'type': 'error', 'message': str(exc)})}\n\n"
            yield "data: [DONE]\n\n"

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get(
    "/settings",
    response_model=AiSettingsResponse,
    dependencies=[Depends(RequirePermission(Permission.SYSTEM_ADMIN))],
)
async def get_ai_settings(request: Request, _user: CurrentUser) -> AiSettingsResponse:
    return _settings_store(request).status()


@router.put(
    "/settings",
    response_model=AiSettingsResponse,
    dependencies=[Depends(RequirePermission(Permission.SYSTEM_ADMIN))],
)
async def update_ai_settings(
    body: AiSettingsUpdateRequest,
    request: Request,
    _user: CurrentUser,
) -> AiSettingsResponse:
    return _settings_store(request).update(body)


@router.get(
    "/status",
    response_model=AiSettingsResponse,
    dependencies=[Depends(RequirePermission(Permission.FILES_READ))],
)
async def ai_status(request: Request, _user: CurrentUser) -> AiSettingsResponse:
    """Lightweight status for agent panels (no secret material beyond mask)."""
    return _settings_store(request).status()


@router.post(
    "/chat",
    response_model=AiChatResponse,
    dependencies=[Depends(RequirePermission(Permission.FILES_READ))],
)
async def ai_chat(
    body: AiChatRequest,
    request: Request,
    user: CurrentUser,
    session: DbSession,
) -> AiChatResponse:
    return await _agent(request, session).chat(user, body)


@router.post(
    "/chat/stream",
    dependencies=[Depends(RequirePermission(Permission.FILES_READ))],
)
async def ai_chat_stream(
    body: AiChatRequest,
    request: Request,
    user: CurrentUser,
    session: DbSession,
) -> StreamingResponse:
    agent = _agent(request, session)
    return _sse(agent.chat_stream(user, body))


@router.post(
    "/actions/apply",
    response_model=OperationResult,
)
async def apply_ai_action(
    body: AiApplyActionRequest,
    request: Request,
    user: CurrentUser,
    session: DbSession,
    auth_service: AuthService = Depends(get_auth_service),
) -> OperationResult:
    can_write = auth_service.user_has_permission(user, Permission.FILES_WRITE.value)
    can_term = auth_service.user_has_permission(user, Permission.TERMINAL_EXECUTE.value)
    can_db = auth_service.user_has_permission(user, Permission.DATABASES_WRITE.value)
    if not can_write and not can_term and not can_db:
        raise AuthorizationError("Permission to apply AI actions is required.")
    await _require_drop_password(body, user, auth_service, request.app.state.container.config())
    return await _agent(request, session).apply_action(
        user,
        body,
        can_write_files=can_write,
        can_execute_terminal=can_term,
        can_manage_databases=can_db,
    )


@router.post(
    "/actions/apply/stream",
)
async def apply_ai_action_stream(
    body: AiApplyActionRequest,
    request: Request,
    user: CurrentUser,
    session: DbSession,
    auth_service: AuthService = Depends(get_auth_service),
) -> StreamingResponse:
    can_write = auth_service.user_has_permission(user, Permission.FILES_WRITE.value)
    can_term = auth_service.user_has_permission(user, Permission.TERMINAL_EXECUTE.value)
    can_db = auth_service.user_has_permission(user, Permission.DATABASES_WRITE.value)
    if not can_write and not can_term and not can_db:
        raise AuthorizationError("Permission to apply AI actions is required.")
    await _require_drop_password(body, user, auth_service, request.app.state.container.config())
    agent = _agent(request, session)
    return _sse(
        agent.apply_action_stream(
            user,
            body,
            can_write_files=can_write,
            can_execute_terminal=can_term,
            can_manage_databases=can_db,
        )
    )


@router.post(
    "/actions/undo",
    response_model=OperationResult,
)
async def undo_ai_action(
    request: Request,
    user: CurrentUser,
    session: DbSession,
    auth_service: AuthService = Depends(get_auth_service),
) -> OperationResult:
    can_write = auth_service.user_has_permission(user, Permission.FILES_WRITE.value)
    if not can_write:
        raise AuthorizationError("files:write permission required to undo AI edits.")
    return await _agent(request, session).undo_last(can_write_files=can_write)


@router.get(
    "/sessions",
    response_model=AiSessionListResponse,
    dependencies=[Depends(RequirePermission(Permission.FILES_READ))],
)
async def list_ai_sessions(
    request: Request,
    _user: CurrentUser,
    surface: str | None = None,
    path: str | None = None,
) -> AiSessionListResponse:
    rows = _memory(request).list_sessions(surface=surface, path=path)
    return AiSessionListResponse(sessions=[AiSessionSummary(**r) for r in rows])


@router.post(
    "/sessions",
    response_model=AiSessionDetail,
    dependencies=[Depends(RequirePermission(Permission.FILES_READ))],
)
async def create_ai_session(
    body: AiSessionCreateRequest,
    request: Request,
    _user: CurrentUser,
) -> AiSessionDetail:
    session = _memory(request).create_session(
        surface=body.surface,
        title=body.title,
        path=body.path,
        app_id=body.app_id,
        root_id=body.root_id,
    )
    return AiSessionDetail(**session)


@router.get(
    "/sessions/{session_id}",
    response_model=AiSessionDetail,
    dependencies=[Depends(RequirePermission(Permission.FILES_READ))],
)
async def get_ai_session(
    session_id: str,
    request: Request,
    _user: CurrentUser,
) -> AiSessionDetail:
    session = _memory(request).get_session(session_id)
    if not session:
        raise NotFoundError("Conversation not found.")
    return AiSessionDetail(**session)


@router.delete(
    "/sessions/{session_id}",
    response_model=OperationResult,
    dependencies=[Depends(RequirePermission(Permission.FILES_READ))],
)
async def delete_ai_session(
    session_id: str,
    request: Request,
    _user: CurrentUser,
) -> OperationResult:
    ok = _memory(request).delete_session(session_id)
    return OperationResult(
        success=ok,
        message="Conversation deleted." if ok else "Conversation not found.",
    )


@router.delete(
    "/sessions",
    response_model=OperationResult,
    dependencies=[Depends(RequirePermission(Permission.FILES_READ))],
)
async def clear_ai_sessions(
    request: Request,
    _user: CurrentUser,
    surface: str | None = None,
) -> OperationResult:
    removed = _memory(request).clear_sessions(surface=surface)
    return OperationResult(
        success=True,
        message=f"Cleared {removed} conversation(s).",
        details={"removed": removed},
    )
