"""Staff support ticket APIs."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Query

from app.api.deps import CurrentUser, DbSession, RequirePermission, SettingsDep
from app.core.permissions import Permission
from app.schemas.support import (
    SupportTicketMessageCreateRequest,
    SupportTicketMessageResponse,
    SupportTicketResponse,
)
from app.services.platform.tickets import SupportTicketService

router = APIRouter()


def _ticket_response(
    ticket,
    *,
    messages: list | None = None,
    customer_email: str | None = None,
    customer_name: str | None = None,
) -> SupportTicketResponse:
    return SupportTicketResponse(
        id=ticket.id,
        customer_id=ticket.customer_id,
        environment_id=ticket.environment_id,
        subject=ticket.subject,
        status=ticket.status,
        priority=ticket.priority,
        created_at=ticket.created_at,
        updated_at=ticket.updated_at,
        customer_email=customer_email,
        customer_name=customer_name,
        messages=[SupportTicketMessageResponse.model_validate(m) for m in (messages or [])],
    )


@router.get(
    "/tickets",
    response_model=list[SupportTicketResponse],
    dependencies=[Depends(RequirePermission(Permission.SUPPORT_READ))],
)
async def list_tickets(
    session: DbSession,
    settings: SettingsDep,
    status: str | None = Query(default=None),
    priority: str | None = Query(default=None),
) -> list[SupportTicketResponse]:
    svc = SupportTicketService(settings, session)
    rows = await svc.list_staff(status=status, priority=priority)
    out: list[SupportTicketResponse] = []
    for t in rows:
        email, name = await svc.customer_email(t.customer_id)
        out.append(_ticket_response(t, customer_email=email, customer_name=name))
    return out


@router.get(
    "/tickets/{ticket_id}",
    response_model=SupportTicketResponse,
    dependencies=[Depends(RequirePermission(Permission.SUPPORT_READ))],
)
async def get_ticket(
    ticket_id: UUID,
    session: DbSession,
    settings: SettingsDep,
) -> SupportTicketResponse:
    svc = SupportTicketService(settings, session)
    ticket = await svc.get_staff(ticket_id)
    messages = await svc.list_messages(ticket.id)
    email, name = await svc.customer_email(ticket.customer_id)
    return _ticket_response(
        ticket, messages=messages, customer_email=email, customer_name=name
    )


@router.post(
    "/tickets/{ticket_id}/messages",
    response_model=SupportTicketMessageResponse,
    dependencies=[Depends(RequirePermission(Permission.SUPPORT_WRITE))],
)
async def reply_ticket(
    ticket_id: UUID,
    body: SupportTicketMessageCreateRequest,
    user: CurrentUser,
    session: DbSession,
    settings: SettingsDep,
) -> SupportTicketMessageResponse:
    msg = await SupportTicketService(settings, session).add_message(
        ticket_id=ticket_id,
        author_user_id=user.id,
        author_role="staff",
        body=body.body,
        send_direct_message=body.send_direct_message,
    )
    return SupportTicketMessageResponse.model_validate(msg)


@router.post(
    "/tickets/{ticket_id}/close",
    response_model=SupportTicketResponse,
    dependencies=[Depends(RequirePermission(Permission.SUPPORT_WRITE))],
)
async def close_ticket(
    ticket_id: UUID,
    session: DbSession,
    settings: SettingsDep,
) -> SupportTicketResponse:
    svc = SupportTicketService(settings, session)
    ticket = await svc.close(ticket_id)
    email, name = await svc.customer_email(ticket.customer_id)
    return _ticket_response(ticket, customer_email=email, customer_name=name)


@router.post(
    "/tickets/{ticket_id}/reopen",
    response_model=SupportTicketResponse,
    dependencies=[Depends(RequirePermission(Permission.SUPPORT_WRITE))],
)
async def reopen_ticket(
    ticket_id: UUID,
    session: DbSession,
    settings: SettingsDep,
) -> SupportTicketResponse:
    svc = SupportTicketService(settings, session)
    ticket = await svc.reopen(ticket_id)
    email, name = await svc.customer_email(ticket.customer_id)
    return _ticket_response(ticket, customer_email=email, customer_name=name)


@router.patch(
    "/tickets/{ticket_id}/priority",
    response_model=SupportTicketResponse,
    dependencies=[Depends(RequirePermission(Permission.SUPPORT_WRITE))],
)
async def set_ticket_priority(
    ticket_id: UUID,
    session: DbSession,
    settings: SettingsDep,
    priority: str = Query(...),
) -> SupportTicketResponse:
    svc = SupportTicketService(settings, session)
    ticket = await svc.set_priority(ticket_id, priority)
    email, name = await svc.customer_email(ticket.customer_id)
    return _ticket_response(ticket, customer_email=email, customer_name=name)
