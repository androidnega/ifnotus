"""Support ticket service."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.exceptions import AppException, NotFoundError
from app.models.platform import Customer, SupportTicket, SupportTicketMessage
from app.services.platform.notifications import NotificationService
from app.services.platform.tenant import TenantService


class SupportTicketService:
    def __init__(self, settings: Settings, session: AsyncSession) -> None:
        self._settings = settings
        self._session = session

    async def create_ticket(
        self,
        *,
        customer_id: UUID,
        author_user_id: UUID | None,
        subject: str,
        body: str,
        priority: str = "normal",
        department: str | None = None,
        environment_id: UUID | None = None,
    ) -> SupportTicket:
        subject = subject.strip()
        body = body.strip()
        if len(subject) < 3:
            raise AppException("Subject is too short.")
        if len(body) < 3:
            raise AppException("Message is too short.")
        priority = (priority or "normal").lower()
        if priority not in {"low", "normal", "high"}:
            raise AppException("priority must be low, normal, or high.")

        # Enforce single active ticket per customer
        active_res = await self._session.execute(
            select(SupportTicket).where(
                SupportTicket.customer_id == customer_id,
                SupportTicket.status.in_(["open", "pending", "in_progress"]),
            ).order_by(SupportTicket.updated_at.desc())
        )
        active_ticket = active_res.scalars().first()
        if active_ticket is not None:
            raise AppException(
                f"You already have an active support ticket (#{str(active_ticket.id)[:8]} - '{active_ticket.subject}'). "
                "Please reply in your open ticket or wait for it to be resolved before opening a new one.",
                code="active_ticket_exists",
            )

        if environment_id:
            await TenantService(self._session).get_owned_environment(customer_id, environment_id)

        # Include department in subject tag if provided
        final_subject = subject
        if department and department.strip() and not subject.startswith("["):
            final_subject = f"[{department.strip()}] {subject}"

        now = datetime.now(UTC)
        ticket = SupportTicket(
            customer_id=customer_id,
            environment_id=environment_id,
            subject=final_subject[:255],
            status="open",
            priority=priority,
            created_at=now,
            updated_at=now,
        )
        self._session.add(ticket)
        await self._session.flush()
        self._session.add(
            SupportTicketMessage(
                ticket_id=ticket.id,
                author_user_id=author_user_id,
                author_role="customer",
                body=body[:20000],
                created_at=now,
                updated_at=now,
            )
        )
        await self._session.flush()
        await self._session.refresh(ticket)
        return ticket

    async def count_awaiting_customer(self, customer_id: UUID) -> int:
        """Tickets where staff replied last (status pending) — accurate support badge."""
        from sqlalchemy import func

        result = await self._session.execute(
            select(func.count())
            .select_from(SupportTicket)
            .where(
                SupportTicket.customer_id == customer_id,
                SupportTicket.status == "pending",
            )
        )
        return int(result.scalar_one() or 0)

    async def list_customer(self, customer_id: UUID) -> list[SupportTicket]:
        result = await self._session.execute(
            select(SupportTicket)
            .where(SupportTicket.customer_id == customer_id)
            .order_by(SupportTicket.updated_at.desc())
            .limit(100)
        )
        return list(result.scalars().all())

    async def get_customer(self, customer_id: UUID, ticket_id: UUID) -> SupportTicket:
        ticket = await self._get(ticket_id)
        if ticket.customer_id != customer_id:
            raise NotFoundError("Ticket not found.")
        return ticket

    async def list_staff(
        self,
        *,
        status: str | None = None,
        priority: str | None = None,
        limit: int = 100,
    ) -> list[SupportTicket]:
        stmt = select(SupportTicket).order_by(SupportTicket.updated_at.desc()).limit(min(limit, 200))
        if status:
            stmt = stmt.where(SupportTicket.status == status)
        if priority:
            stmt = stmt.where(SupportTicket.priority == priority)
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def get_staff(self, ticket_id: UUID) -> SupportTicket:
        return await self._get(ticket_id)

    async def add_message(
        self,
        *,
        ticket_id: UUID,
        author_user_id: UUID | None,
        author_role: str,
        body: str,
        customer_id: UUID | None = None,
    ) -> SupportTicketMessage:
        body = body.strip()
        if len(body) < 1:
            raise AppException("Message is empty.")
        ticket = await self._get(ticket_id)
        if author_role == "customer":
            if customer_id is None or ticket.customer_id != customer_id:
                raise NotFoundError("Ticket not found.")
            if ticket.status == "closed":
                raise AppException("This ticket is closed. Open a new ticket if you need help.")
            ticket.status = "open"
            ticket.updated_at = datetime.now(UTC)
        elif author_role == "staff":
            if ticket.status == "closed":
                ticket.status = "open"
            else:
                ticket.status = "pending"
            ticket.updated_at = datetime.now(UTC)
        else:
            raise AppException("Invalid author role.")

        msg = SupportTicketMessage(
            ticket_id=ticket.id,
            author_user_id=author_user_id,
            author_role=author_role,
            body=body[:20000],
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        self._session.add(msg)
        await self._session.flush()

        if author_role == "staff":
            try:
                await NotificationService(self._session, self._settings).notify(
                    ticket.customer_id,
                    title=f"Support reply: {ticket.subject}",
                    body=body[:500],
                    kind="support",
                )
            except Exception:
                pass
        return msg

    async def close(self, ticket_id: UUID) -> SupportTicket:
        ticket = await self._get(ticket_id)
        ticket.status = "closed"
        ticket.updated_at = datetime.now(UTC)
        await self._session.flush()
        try:
            await NotificationService(self._session, self._settings).notify(
                ticket.customer_id,
                title=f"Ticket closed: {ticket.subject}",
                body="Your support ticket was marked closed. Reply is disabled; open a new ticket if needed.",
                kind="support",
                deliver=False,
            )
        except Exception:
            pass
        return ticket

    async def reopen(self, ticket_id: UUID) -> SupportTicket:
        ticket = await self._get(ticket_id)
        if ticket.status != "closed":
            return ticket
        ticket.status = "open"
        ticket.updated_at = datetime.now(UTC)
        await self._session.flush()
        return ticket

    async def set_priority(self, ticket_id: UUID, priority: str) -> SupportTicket:
        priority = (priority or "normal").lower()
        if priority not in {"low", "normal", "high"}:
            raise AppException("priority must be low, normal, or high.")
        ticket = await self._get(ticket_id)
        ticket.priority = priority
        ticket.updated_at = datetime.now(UTC)
        await self._session.flush()
        return ticket

    async def list_messages(self, ticket_id: UUID) -> list[SupportTicketMessage]:
        result = await self._session.execute(
            select(SupportTicketMessage)
            .where(SupportTicketMessage.ticket_id == ticket_id)
            .order_by(SupportTicketMessage.created_at.asc())
        )
        return list(result.scalars().all())

    async def customer_email(self, customer_id: UUID) -> tuple[str | None, str | None]:
        customer = await self._session.get(Customer, customer_id)
        if customer is None:
            return None, None
        return customer.email, customer.full_name

    async def _get(self, ticket_id: UUID) -> SupportTicket:
        ticket = await self._session.get(SupportTicket, ticket_id)
        if ticket is None:
            raise NotFoundError("Ticket not found.")
        return ticket
