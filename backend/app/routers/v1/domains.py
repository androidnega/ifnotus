"""Domain management endpoints."""

from uuid import UUID

from fastapi import APIRouter, Depends, Request

from app.api.deps import CurrentUser, DbSession, RequirePermission
from app.core.permissions import Permission
from app.schemas.hosting import (
    DnsCheckResponse,
    DomainCreate,
    DomainListResponse,
    DomainSchema,
    DomainUpdate,
)
from app.schemas.operations import OperationResult
from app.services.hosting.domains import DomainService

router = APIRouter()


def _domain_service(request: Request, session: DbSession) -> DomainService:
    from app.core.config import Settings

    settings: Settings = request.app.state.container.config()
    return DomainService(settings, session)


@router.get(
    "",
    response_model=DomainListResponse,
    dependencies=[Depends(RequirePermission(Permission.DOMAINS_READ))],
)
async def list_domains(request: Request, session: DbSession, _user: CurrentUser) -> DomainListResponse:
    return await _domain_service(request, session).list_domains()


@router.post(
    "",
    response_model=DomainSchema,
    dependencies=[Depends(RequirePermission(Permission.DOMAINS_WRITE))],
)
async def create_domain(
    body: DomainCreate,
    request: Request,
    session: DbSession,
    _user: CurrentUser,
) -> DomainSchema:
    return await _domain_service(request, session).create_domain(body)


@router.get(
    "/{domain_id}",
    response_model=DomainSchema,
    dependencies=[Depends(RequirePermission(Permission.DOMAINS_READ))],
)
async def get_domain(
    domain_id: UUID,
    request: Request,
    session: DbSession,
    _user: CurrentUser,
) -> DomainSchema:
    return await _domain_service(request, session).get_domain(domain_id)


@router.patch(
    "/{domain_id}",
    response_model=DomainSchema,
    dependencies=[Depends(RequirePermission(Permission.DOMAINS_WRITE))],
)
async def update_domain(
    domain_id: UUID,
    body: DomainUpdate,
    request: Request,
    session: DbSession,
    _user: CurrentUser,
) -> DomainSchema:
    return await _domain_service(request, session).update_domain(domain_id, body)


@router.delete(
    "/{domain_id}",
    response_model=OperationResult,
    dependencies=[Depends(RequirePermission(Permission.DOMAINS_WRITE))],
)
async def delete_domain(
    domain_id: UUID,
    request: Request,
    session: DbSession,
    _user: CurrentUser,
) -> OperationResult:
    await _domain_service(request, session).delete_domain(domain_id)
    return OperationResult(success=True, message="Domain deleted.")


@router.post(
    "/{domain_id}/dns-check",
    response_model=DnsCheckResponse,
    dependencies=[Depends(RequirePermission(Permission.DOMAINS_READ))],
)
async def dns_check(
    domain_id: UUID,
    request: Request,
    session: DbSession,
    _user: CurrentUser,
) -> DnsCheckResponse:
    svc = _domain_service(request, session)
    domain = await svc.get_domain(domain_id)
    return await svc.check_dns(domain.name)
