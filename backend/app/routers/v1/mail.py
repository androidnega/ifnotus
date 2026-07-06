"""Mail management endpoints."""

from uuid import UUID

from fastapi import APIRouter, Depends, Request

from app.api.deps import CurrentUser, DbSession, RequirePermission
from app.core.permissions import Permission
from app.schemas.hosting import (
    MailAliasCreate,
    MailAliasSchema,
    MailboxCreate,
    MailboxSchema,
    MailboxUpdate,
    MailDomainResponse,
)
from app.schemas.operations import OperationResult
from app.services.hosting.mail import MailService

router = APIRouter()


def _mail_service(request: Request, session: DbSession) -> MailService:
    settings = request.app.state.container.config()
    return MailService(settings, session)


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
