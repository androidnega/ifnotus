"""SSL management endpoints."""

from fastapi import APIRouter, Depends, Request

from app.api.deps import CurrentUser, DbSession, RequirePermission
from app.core.permissions import Permission
from app.schemas.hosting import (
    SslActionRequest,
    SslListResponse,
    SslReadinessResponse,
)
from app.schemas.operations import OperationResult
from app.services.hosting.ssl import SslService

router = APIRouter()


def _ssl_service(request: Request, session: DbSession) -> SslService:
    settings = request.app.state.container.config()
    return SslService(settings, session)


@router.get(
    "",
    response_model=SslListResponse,
    dependencies=[Depends(RequirePermission(Permission.SSL_READ))],
)
async def list_ssl(request: Request, session: DbSession, _user: CurrentUser) -> SslListResponse:
    return await _ssl_service(request, session).list_certificates()


@router.get(
    "/readiness/{domain}",
    response_model=SslReadinessResponse,
    dependencies=[Depends(RequirePermission(Permission.SSL_READ))],
)
async def ssl_readiness(
    domain: str,
    request: Request,
    session: DbSession,
    _user: CurrentUser,
) -> SslReadinessResponse:
    return await _ssl_service(request, session).validate_readiness(domain)


@router.post(
    "/issue",
    response_model=OperationResult,
    dependencies=[Depends(RequirePermission(Permission.SSL_WRITE))],
)
async def issue_ssl(
    body: SslActionRequest,
    request: Request,
    session: DbSession,
    _user: CurrentUser,
) -> OperationResult:
    return await _ssl_service(request, session).issue(body)


@router.post(
    "/renew",
    response_model=OperationResult,
    dependencies=[Depends(RequirePermission(Permission.SSL_WRITE))],
)
async def renew_ssl(
    body: SslActionRequest,
    request: Request,
    session: DbSession,
    _user: CurrentUser,
) -> OperationResult:
    return await _ssl_service(request, session).renew(body)


@router.post(
    "/reissue",
    response_model=OperationResult,
    dependencies=[Depends(RequirePermission(Permission.SSL_WRITE))],
)
async def reissue_ssl(
    body: SslActionRequest,
    request: Request,
    session: DbSession,
    _user: CurrentUser,
) -> OperationResult:
    return await _ssl_service(request, session).reissue(body)
