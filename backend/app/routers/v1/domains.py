"""Domain management endpoints — cPanel-style domains, subdomains, redirects, DNS."""

from uuid import UUID

from fastapi import APIRouter, Depends, Request

from app.api.deps import CurrentUser, DbSession, RequirePermission
from app.core.permissions import Permission
from app.schemas.hosting import (
    DnsCheckResponse,
    DomainCreate,
    DomainDnsRecordCreate,
    DomainDnsRecordSchema,
    DomainImportRequest,
    DomainListResponse,
    DomainRedirectCreate,
    DomainRedirectSchema,
    DomainSchema,
    DomainUpdate,
)
from app.schemas.operations import OperationResult
from app.services.hosting.domains import DomainService

router = APIRouter()


def _domain_service(request: Request, session: DbSession) -> DomainService:
    settings = request.app.state.container.config()
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


@router.post(
    "/import",
    response_model=DomainSchema,
    dependencies=[Depends(RequirePermission(Permission.DOMAINS_WRITE))],
)
async def import_discovered(
    body: DomainImportRequest,
    request: Request,
    session: DbSession,
    _user: CurrentUser,
) -> DomainSchema:
    return await _domain_service(request, session).import_discovered(body)


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
    "/reprovision-all",
    response_model=list[OperationResult],
    dependencies=[Depends(RequirePermission(Permission.DOMAINS_WRITE))],
)
async def reprovision_all_domains(
    request: Request,
    session: DbSession,
    _user: CurrentUser,
) -> list[OperationResult]:
    """Rewrite nginx for all enabled domains (ensures /mail webmail locations)."""
    return await _domain_service(request, session).reprovision_all()


@router.post(
    "/{domain_id}/provision",
    response_model=OperationResult,
    dependencies=[Depends(RequirePermission(Permission.DOMAINS_WRITE))],
)
async def provision_domain(
    domain_id: UUID,
    request: Request,
    session: DbSession,
    _user: CurrentUser,
) -> OperationResult:
    return await _domain_service(request, session).provision_domain(domain_id)


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


@router.get(
    "/{domain_id}/redirects",
    response_model=list[DomainRedirectSchema],
    dependencies=[Depends(RequirePermission(Permission.DOMAINS_READ))],
)
async def list_redirects(
    domain_id: UUID,
    request: Request,
    session: DbSession,
    _user: CurrentUser,
) -> list[DomainRedirectSchema]:
    return await _domain_service(request, session).list_redirects(domain_id)


@router.post(
    "/{domain_id}/redirects",
    response_model=DomainRedirectSchema,
    dependencies=[Depends(RequirePermission(Permission.DOMAINS_WRITE))],
)
async def create_redirect(
    domain_id: UUID,
    body: DomainRedirectCreate,
    request: Request,
    session: DbSession,
    _user: CurrentUser,
) -> DomainRedirectSchema:
    return await _domain_service(request, session).create_redirect(domain_id, body)


@router.delete(
    "/{domain_id}/redirects/{redirect_id}",
    response_model=OperationResult,
    dependencies=[Depends(RequirePermission(Permission.DOMAINS_WRITE))],
)
async def delete_redirect(
    domain_id: UUID,
    redirect_id: UUID,
    request: Request,
    session: DbSession,
    _user: CurrentUser,
) -> OperationResult:
    return await _domain_service(request, session).delete_redirect(domain_id, redirect_id)


@router.get(
    "/{domain_id}/dns-records",
    response_model=list[DomainDnsRecordSchema],
    dependencies=[Depends(RequirePermission(Permission.DOMAINS_READ))],
)
async def list_dns_records(
    domain_id: UUID,
    request: Request,
    session: DbSession,
    _user: CurrentUser,
) -> list[DomainDnsRecordSchema]:
    return await _domain_service(request, session).list_dns_records(domain_id)


@router.post(
    "/{domain_id}/dns-records",
    response_model=DomainDnsRecordSchema,
    dependencies=[Depends(RequirePermission(Permission.DOMAINS_WRITE))],
)
async def create_dns_record(
    domain_id: UUID,
    body: DomainDnsRecordCreate,
    request: Request,
    session: DbSession,
    _user: CurrentUser,
) -> DomainDnsRecordSchema:
    return await _domain_service(request, session).create_dns_record(domain_id, body)


@router.delete(
    "/{domain_id}/dns-records/{record_id}",
    response_model=OperationResult,
    dependencies=[Depends(RequirePermission(Permission.DOMAINS_WRITE))],
)
async def delete_dns_record(
    domain_id: UUID,
    record_id: UUID,
    request: Request,
    session: DbSession,
    _user: CurrentUser,
) -> OperationResult:
    return await _domain_service(request, session).delete_dns_record(domain_id, record_id)
