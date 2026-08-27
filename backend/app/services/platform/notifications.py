"""Customer notifications — panel inbox + optional email/SMS delivery."""

from __future__ import annotations

from typing import Iterable, Sequence
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.exceptions import NotFoundError
from app.core.logging import get_logger
from app.models.platform import Customer, Notification
from app.services.platform.delivery import MessageDelivery

logger = get_logger(__name__)

# Events that should also try email + SMS (when configured).
OUTBOUND_KINDS = frozenset(
    {
        "provision",
        "payment",
        "renewal",
        "renewal_auto",
        "renewal_30",
        "renewal_14",
        "renewal_7",
        "renewal_1",
        "auto_renew",
        "upgrade_nudge",
        "grace",
        "suspend",
        "terminate",
        "lifecycle",
        "backup",
        "support",
        "domain",
        "stack",
        "health",
    }
)

# Badge / “new notices” — only actionable items (not historical health spam).
BADGE_KINDS = frozenset(
    {
        "provision",
        "payment",
        "renewal",
        "renewal_auto",
        "renewal_30",
        "renewal_14",
        "renewal_7",
        "renewal_1",
        "auto_renew",
        "grace",
        "suspend",
        "terminate",
        "support",
        "domain",
        "upgrade_nudge",
    }
)


class NotificationService:
    def __init__(self, session: AsyncSession, settings: Settings | None = None) -> None:
        self._session = session
        self._settings = settings

    async def list_for_customer(
        self,
        customer_id: UUID,
        *,
        unread_only: bool = False,
        kinds: Sequence[str] | None = None,
        limit: int = 100,
    ) -> list[Notification]:
        stmt = select(Notification).where(
            Notification.customer_id == customer_id,
            Notification.channel == "panel",
        )
        if unread_only:
            stmt = stmt.where(Notification.is_read.is_(False))
        if kinds:
            stmt = stmt.where(Notification.kind.in_(list(kinds)))
        stmt = stmt.order_by(Notification.created_at.desc()).limit(limit)
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def unread_badge_count(self, customer_id: UUID) -> int:
        """Count actionable unread panel notices for the account badge."""
        from sqlalchemy import func

        result = await self._session.execute(
            select(func.count())
            .select_from(Notification)
            .where(
                Notification.customer_id == customer_id,
                Notification.channel == "panel",
                Notification.is_read.is_(False),
                Notification.kind.in_(list(BADGE_KINDS)),
            )
        )
        return int(result.scalar_one() or 0)

    async def mark_all_read(self, customer_id: UUID) -> int:
        result = await self._session.execute(
            select(Notification).where(
                Notification.customer_id == customer_id,
                Notification.channel == "panel",
                Notification.is_read.is_(False),
            )
        )
        rows = list(result.scalars().all())
        for row in rows:
            row.is_read = True
        await self._session.flush()
        return len(rows)

    async def mark_read(self, customer_id: UUID, notification_id: UUID) -> Notification:
        result = await self._session.execute(
            select(Notification).where(
                Notification.id == notification_id, Notification.customer_id == customer_id
            )
        )
        row = result.scalar_one_or_none()
        if row is None:
            raise NotFoundError("Notification not found.")
        row.is_read = True
        await self._session.flush()
        return row

    async def notify(
        self,
        customer_id: UUID,
        *,
        title: str,
        body: str,
        kind: str = "info",
        channel: str = "panel",
        channels: Sequence[str] | None = None,
        deliver: bool | None = None,
        html_body: str | None = None,
        email_subject: str | None = None,
        sms_body: str | None = None,
    ) -> Notification:
        """
        Always create a panel inbox row (unless channel is explicitly non-panel
        and channels is not provided). Optionally deliver email/SMS.
        """
        wanted: list[str]
        if channels is not None:
            wanted = list(channels)
        elif channel == "panel":
            wanted = ["panel"]
            if deliver is True or (deliver is None and kind in OUTBOUND_KINDS):
                wanted.extend(["email", "sms"])
        else:
            wanted = [channel]

        # De-dupe while preserving order
        seen: set[str] = set()
        ordered: list[str] = []
        for c in wanted:
            if c not in seen:
                seen.add(c)
                ordered.append(c)

        panel = Notification(
            customer_id=customer_id,
            title=title,
            body=body,
            kind=kind,
            channel="panel",
        )
        self._session.add(panel)
        await self._session.flush()

        if "email" in ordered or "sms" in ordered:
            await self._queue_or_deliver_outbound(
                customer_id,
                title=title,
                body=body,
                kind=kind,
                channels=ordered,
                html_body=html_body,
                email_subject=email_subject,
                sms_body=sms_body,
            )
        return panel

    async def _queue_or_deliver_outbound(
        self,
        customer_id: UUID,
        *,
        title: str,
        body: str,
        kind: str,
        channels: Iterable[str],
        html_body: str | None = None,
        email_subject: str | None = None,
        sms_body: str | None = None,
    ) -> None:
        """Prefer Redis worker for SMTP/SMS so API requests stay fast."""
        channel_list = [c for c in channels if c in {"email", "sms"}]
        if "sms" in channel_list and "email" not in channel_list:
            channel_list.append("email")
        if not channel_list or self._settings is None:
            return
        from app.services.platform.enqueue import enqueue_task

        task_id = await enqueue_task(
            self._settings,
            "deliver_notification",
            {
                "customer_id": str(customer_id),
                "title": title,
                "body": body,
                "kind": kind,
                "channels": channel_list,
                "html_body": html_body,
                "email_subject": email_subject,
                "sms_body": sms_body,
            },
        )
        if task_id is None:
            await self._deliver_outbound(
                customer_id,
                title=title,
                body=body,
                kind=kind,
                channels=channel_list,
                html_body=html_body,
                email_subject=email_subject,
                sms_body=sms_body,
            )

    async def deliver_outbound_now(
        self,
        customer_id: UUID,
        *,
        title: str,
        body: str,
        kind: str,
        channels: Iterable[str],
        html_body: str | None = None,
        email_subject: str | None = None,
        sms_body: str | None = None,
    ) -> dict:
        """Worker entry — send email/SMS and record channel rows."""
        await self._deliver_outbound(
            customer_id,
            title=title,
            body=body,
            kind=kind,
            channels=channels,
            html_body=html_body,
            email_subject=email_subject,
            sms_body=sms_body,
        )
        return {"ok": True, "customer_id": str(customer_id), "channels": list(channels)}

    async def _deliver_outbound(
        self,
        customer_id: UUID,
        *,
        title: str,
        body: str,
        kind: str,
        channels: Iterable[str],
        html_body: str | None = None,
        email_subject: str | None = None,
        sms_body: str | None = None,
    ) -> None:
        if self._settings is None:
            logger.warning("notification_delivery_skipped", reason="no_settings")
            return
        customer = await self._session.get(Customer, customer_id)
        if customer is None:
            return
        delivery = MessageDelivery(self._settings)
        channel_set = set(channels)

        # If SMS is requested, always attempt email with the same content when possible.
        if "sms" in channel_set and "email" not in channel_set:
            channel_set.add("email")

        if "email" in channel_set and customer.email:
            email = customer.email.lower()
            if email.endswith("@phone.pending.ifnotus"):
                logger.info(
                    "email_notify_skipped_pending_profile",
                    customer_id=str(customer_id),
                )
            else:
                html = html_body
                plain = body
                if not html:
                    from app.services.platform import email_templates

                    name = (customer.full_name or "there").strip() or "there"
                    paras = [p.strip() for p in (body or "").split("\n") if p.strip()]
                    if not paras:
                        paras = [title]
                    _t, plain, html = email_templates.simple_notice(
                        name=name,
                        title=title,
                        paragraphs=paras[:8],
                        tone="info",
                        cta_href="https://ifnotus.space/account",
                        cta_label="Open your account",
                        preheader=(sms_body or paras[0])[:140],
                    )
                result = delivery.send_email(
                    to=customer.email,
                    subject=email_subject or title,
                    body=plain if plain.endswith("IFNOTUS") or "ifnotus.space" in plain.lower() else (
                        f"{plain}\n\n— IFNOTUS\nhttps://ifnotus.space\n"
                    ),
                    html=html,
                )
                self._session.add(
                    Notification(
                        customer_id=customer_id,
                        title=title,
                        body=body,
                        kind=kind,
                        channel="email",
                        is_read=True,
                    )
                )
                if not result.get("ok") and not result.get("skipped"):
                    logger.warning("email_notify_failed", customer_id=str(customer_id), result=result)

        if "sms" in channel_set and customer.phone:
            text = (sms_body or title).strip()
            if len(text) > 300:
                text = text[:297] + "…"
            result = delivery.send_sms(to=customer.phone, body=text)
            self._session.add(
                Notification(
                    customer_id=customer_id,
                    title=title,
                    body=body,
                    kind=kind,
                    channel="sms",
                    is_read=True,
                )
            )
            if not result.get("ok") and not result.get("skipped"):
                logger.warning("sms_notify_failed", customer_id=str(customer_id), result=result)

        await self._session.flush()
