"""Mail management endpoints."""

from uuid import UUID

from fastapi import APIRouter, Depends, Request

from app.api.deps import CurrentUser, DbSession, RequirePermission
from app.core.permissions import Permission
from app.schemas.hosting import (
    MailAliasCreate,
    MailAliasSchema,
    MailAliasUpdate,
    MailboxCreate,
    MailboxSchema,
    MailboxUpdate,
    MailDomainResponse,
    MailProbeRequest,
)
from app.schemas.operations import OperationResult
from app.schemas.webmail_settings import WebmailSettingsResponse, WebmailSettingsUpdateRequest
from app.services.hosting.mail import MailService
from app.services.hosting.webmail_settings import WebmailSettingsStore

router = APIRouter()


def _mail_service(request: Request, session: DbSession) -> MailService:
    settings = request.app.state.container.config()
    return MailService(settings, session)


def _webmail_store(request: Request) -> WebmailSettingsStore:
    return WebmailSettingsStore(request.app.state.container.config())


@router.get(
    "/settings",
    response_model=WebmailSettingsResponse,
    dependencies=[Depends(RequirePermission(Permission.SYSTEM_ADMIN))],
)
async def get_webmail_settings(request: Request, _user: CurrentUser) -> WebmailSettingsResponse:
    return _webmail_store(request).status()


@router.put(
    "/settings",
    response_model=WebmailSettingsResponse,
    dependencies=[Depends(RequirePermission(Permission.SYSTEM_ADMIN))],
)
async def update_webmail_settings(
    body: WebmailSettingsUpdateRequest,
    request: Request,
    _user: CurrentUser,
) -> WebmailSettingsResponse:
    return _webmail_store(request).update(body)


@router.post(
    "/sync-domains",
    response_model=OperationResult,
    dependencies=[Depends(RequirePermission(Permission.SYSTEM_ADMIN))],
)
async def sync_webmail_domains(request: Request, _user: CurrentUser) -> OperationResult:
    """Ensure every nginx site exposes /mail (same auto-detect as inventory)."""
    return await _webmail_store(request).ensure_webmail_for_domains(force=True)


@router.get(
    "/domains/{domain_id}",
    response_model=MailDomainResponse,
    dependencies=[Depends(RequirePermission(Permission.MAIL_READ))],
)
async def get_domain_mail(
    domain_id: UUID,
    request: Request,
    session: DbSession,
    _user: CurrentUser,
) -> MailDomainResponse:
    return await _mail_service(request, session).get_domain_mail(domain_id)


@router.post(
    "/domains/{domain_id}/mailboxes",
    response_model=MailboxSchema,
    dependencies=[Depends(RequirePermission(Permission.MAIL_WRITE))],
)
async def create_mailbox(
    domain_id: UUID,
    body: MailboxCreate,
    request: Request,
    session: DbSession,
    _user: CurrentUser,
) -> MailboxSchema:
    return await _mail_service(request, session).create_mailbox(domain_id, body)


@router.patch(
    "/domains/{domain_id}/mailboxes/{mailbox_id}",
    response_model=MailboxSchema,
    dependencies=[Depends(RequirePermission(Permission.MAIL_WRITE))],
)
async def update_mailbox(
    domain_id: UUID,
    mailbox_id: UUID,
    body: MailboxUpdate,
    request: Request,
    session: DbSession,
    _user: CurrentUser,
) -> MailboxSchema:
    return await _mail_service(request, session).update_mailbox(domain_id, mailbox_id, body)


@router.delete(
    "/domains/{domain_id}/mailboxes/{mailbox_id}",
    response_model=OperationResult,
    dependencies=[Depends(RequirePermission(Permission.MAIL_WRITE))],
)
async def delete_mailbox(
    domain_id: UUID,
    mailbox_id: UUID,
    request: Request,
    session: DbSession,
    _user: CurrentUser,
) -> OperationResult:
    await _mail_service(request, session).delete_mailbox(domain_id, mailbox_id)
    return OperationResult(success=True, message="Mailbox deleted.")


@router.post(
    "/domains/{domain_id}/aliases",
    response_model=MailAliasSchema,
    dependencies=[Depends(RequirePermission(Permission.MAIL_WRITE))],
)
async def create_alias(
    domain_id: UUID,
    body: MailAliasCreate,
    request: Request,
    session: DbSession,
    _user: CurrentUser,
) -> MailAliasSchema:
    return await _mail_service(request, session).create_alias(domain_id, body)


@router.patch(
    "/domains/{domain_id}/aliases/{alias_id}",
    response_model=MailAliasSchema,
    dependencies=[Depends(RequirePermission(Permission.MAIL_WRITE))],
)
async def update_alias(
    domain_id: UUID,
    alias_id: UUID,
    body: MailAliasUpdate,
    request: Request,
    session: DbSession,
    _user: CurrentUser,
) -> MailAliasSchema:
    return await _mail_service(request, session).update_alias(domain_id, alias_id, body)


@router.post(
    "/domains/{domain_id}/probe",
    response_model=OperationResult,
    summary="Send a local delivery probe to a mailbox on this domain",
    dependencies=[Depends(RequirePermission(Permission.MAIL_WRITE))],
)
async def send_mail_probe(
    domain_id: UUID,
    body: MailProbeRequest,
    request: Request,
    session: DbSession,
    _user: CurrentUser,
) -> OperationResult:
    details = await _mail_service(request, session).send_probe(domain_id, body.to)
    return OperationResult(
        success=True,
        message=f"Probe queued to {details.get('to')}. Check that inbox (and spam).",
        details=details,
    )


@router.post(
    "/auth/sync",
    response_model=OperationResult,
    summary="Sync outbound DKIM/SPF tunnel for every mailbox domain",
    dependencies=[Depends(RequirePermission(Permission.MAIL_WRITE))],
)
async def sync_all_mail_auth(
    request: Request,
    session: DbSession,
    _user: CurrentUser,
) -> OperationResult:
    details = await _mail_service(request, session).sync_all_mail_auth()
    return OperationResult(
        success=True,
        message=(
            f"Mail auth tunnel synced for {details.get('total', 0)} domain(s); "
            f"{details.get('ready_count', 0)} ready in live DNS."
        ),
        details=details,
    )


@router.post(
    "/domains/{domain_id}/auth",
    response_model=OperationResult,
    summary="Ensure SPF/DKIM/DMARC DNS hints + OpenDKIM signing for this domain",
    dependencies=[Depends(RequirePermission(Permission.MAIL_WRITE))],
)
async def ensure_mail_auth(
    domain_id: UUID,
    request: Request,
    session: DbSession,
    _user: CurrentUser,
) -> OperationResult:
    details = await _mail_service(request, session).mail_auth_status(domain_id)
    ready = bool(details.get("ready"))
    return OperationResult(
        success=True,
        message=(
            "Outbound tunnel ready — DNS authentication passes."
            if ready
            else "DKIM signing is enabled on this server. Publish the DNS records "
            "at your registrar (replace Namecheap email-forwarding SPF/MX)."
        ),
        details=details,
    )


@router.delete(
    "/domains/{domain_id}/aliases/{alias_id}",
    response_model=OperationResult,
    dependencies=[Depends(RequirePermission(Permission.MAIL_WRITE))],
)
async def delete_alias(
    domain_id: UUID,
    alias_id: UUID,
    request: Request,
    session: DbSession,
    _user: CurrentUser,
) -> OperationResult:
    await _mail_service(request, session).delete_alias(domain_id, alias_id)
    return OperationResult(success=True, message="Alias deleted.")
