"""Subscription lifecycle — reminders, grace, suspend, renew, upgrade."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.exceptions import AppException, NotFoundError
from app.core.logging import get_logger
from app.models.platform import (
    Customer,
    CustomerEnvironment,
    HostingPlan,
    Notification,
    PlatformAuditLog,
    Subscription,
)
from app.services.platform import email_templates
from app.services.platform.isolation import IsolationService
from app.services.platform.notifications import NotificationService
from app.services.platform.resources import ResourceManager

logger = get_logger(__name__)

REMINDER_DAYS = (30, 14, 7, 1)
# Occasional upsell: at most once per this many days per customer.
UPGRADE_NUDGE_COOLDOWN_DAYS = 45
# Mid-cycle window so nudges do not collide with expiry reminders.
UPGRADE_NUDGE_MIN_DAYS_LEFT = 10
UPGRADE_NUDGE_MAX_DAYS_LEFT = 22


class SubscriptionBillingService:
    def __init__(self, settings: Settings, session: AsyncSession) -> None:
        self._settings = settings
        self._session = session
        self._resources = ResourceManager(session)
        self._isolation = IsolationService(settings)
        self._notify = NotificationService(session, settings)

    async def list_for_customer(self, customer_id: UUID) -> list[Subscription]:
        result = await self._session.execute(
            select(Subscription)
            .where(Subscription.customer_id == customer_id)
            .order_by(Subscription.created_at.desc())
        )
        return list(result.scalars().all())

    async def get_owned(self, customer_id: UUID, subscription_id: UUID) -> Subscription:
        result = await self._session.execute(
            select(Subscription).where(
                Subscription.id == subscription_id,
                Subscription.customer_id == customer_id,
            )
        )
        sub = result.scalar_one_or_none()
        if sub is None:
            raise NotFoundError("Subscription not found.")
        return sub

    async def set_auto_renew(self, customer_id: UUID, subscription_id: UUID, enabled: bool) -> Subscription:
        sub = await self.get_owned(customer_id, subscription_id)
        sub.auto_renew = enabled
        await self._session.flush()
        customer = await self._session.get(Customer, customer_id)
        plan = await self._session.get(HostingPlan, sub.plan_id)
        name = (customer.full_name if customer else None) or "there"
        plan_name = plan.name if plan else "hosting"
        title, text, html, sms = email_templates.auto_renew_changed(
            name=name, enabled=enabled, plan=plan_name
        )
        await self._notify.notify(
            customer_id,
            title=title,
            body=text,
            kind="auto_renew",
            html_body=html,
            email_subject=title,
            sms_body=sms,
        )
        self._session.add(
            PlatformAuditLog(
                customer_id=customer_id,
                action="subscription.auto_renew",
                target_type="subscription",
                target_id=str(sub.id),
                result="success",
                metadata_json={"enabled": enabled},
            )
        )
        await self._session.flush()
        return sub

    async def renew(
        self,
        customer_id: UUID,
        subscription_id: UUID,
        *,
        days: int = 30,
        auto: bool = False,
    ) -> Subscription:
        sub = await self.get_owned(customer_id, subscription_id)
        now = datetime.now(UTC)
        base = sub.expires_at if sub.expires_at and sub.expires_at > now else now
        sub.expires_at = base + timedelta(days=days)
        sub.renewed_at = now
        sub.grace_until = None
        sub.last_reminder_days = None
        if sub.status in {"expired", "suspended", "grace"}:
            sub.status = "active"
            await self._restore_environments(sub)

        customer = await self._session.get(Customer, customer_id)
        plan = await self._session.get(HostingPlan, sub.plan_id)
        name = (customer.full_name if customer else None) or "there"
        plan_name = plan.name if plan else "hosting"
        expires_on = sub.expires_at.date().isoformat()

        if auto:
            title, text, html, sms = email_templates.auto_renewed(
                name=name, plan=plan_name, expires_on=expires_on
            )
            kind = "renewal_auto"
        else:
            title, text, html, sms = email_templates.subscription_renewed(
                name=name, plan=plan_name, expires_on=expires_on
            )
            kind = "renewal"

        await self._notify.notify(
            customer_id,
            title=title,
            body=text,
            kind=kind,
            html_body=html,
            email_subject=title,
            sms_body=sms,
        )
        self._session.add(
            PlatformAuditLog(
                customer_id=customer_id,
                action="subscription.renewed",
                target_type="subscription",
                target_id=str(sub.id),
                result="success",
                metadata_json={"auto": auto, "expires_at": expires_on},
            )
        )
        await self._session.flush()
        return sub

    async def change_plan(self, customer_id: UUID, subscription_id: UUID, plan_id: UUID) -> Subscription:
        sub = await self.get_owned(customer_id, subscription_id)
        if sub.status not in {"active", "grace"}:
            raise AppException("Only active subscriptions can be upgraded or downgraded.")
        plan = await self._session.get(HostingPlan, plan_id)
        if plan is None or not plan.is_active:
            raise NotFoundError("Hosting plan not found.")
        if plan.id == sub.plan_id:
            raise AppException("Already on this plan.")

        # Capacity only matters when increasing resources
        if plan.cpu_cores > sub.cpu_allocated or plan.ram_gb > sub.ram_allocated or plan.storage_gb > sub.storage_allocated:
            await self._resources.pick_node_for_plan(plan)

        sub.plan_id = plan.id
        sub.cpu_allocated = plan.cpu_cores
        sub.ram_allocated = plan.ram_gb
        sub.storage_allocated = plan.storage_gb

        envs = await self._envs(sub.id)
        for env in envs:
            env.cpu_limit = plan.cpu_cores
            env.ram_limit_gb = plan.ram_gb
            env.storage_limit_gb = plan.storage_gb
            if env.container_id:
                self._isolation.resize_container(
                    env.container_id, cpu=plan.cpu_cores, ram_gb=plan.ram_gb
                )

        await self._notify.notify(
            customer_id,
            title="Plan changed",
            body=f"Your plan is now {plan.name} ({plan.cpu_cores} vCPU / {plan.ram_gb} GB RAM).",
            kind="billing",
            deliver=False,
        )
        self._session.add(
            PlatformAuditLog(
                customer_id=customer_id,
                action="subscription.plan_changed",
                target_type="subscription",
                target_id=str(sub.id),
                result="success",
                metadata_json={"plan": plan.slug},
            )
        )
        await self._session.flush()
        return sub

    async def tick(self) -> dict:
        """Hourly sweep: expiry reminders, auto-renew, grace, suspend, upgrade nudges."""
        now = datetime.now(UTC)
        result = await self._session.execute(
            select(Subscription).where(Subscription.status.in_(["active", "grace", "suspended", "expired"]))
        )
        subs = list(result.scalars().all())
        summary = {
            "reminded": 0,
            "grace": 0,
            "suspended": 0,
            "terminated": 0,
            "auto_renewed": 0,
            "upgrade_nudged": 0,
        }

        for sub in subs:
            if not sub.expires_at:
                continue
            days_left = (sub.expires_at.date() - now.date()).days

            if sub.status == "active" and days_left in REMINDER_DAYS and sub.last_reminder_days != days_left:
                await self._remind(sub, days_left)
                sub.last_reminder_days = days_left
                summary["reminded"] += 1

            if sub.status == "active" and days_left < 0:
                if sub.auto_renew:
                    if self._settings.paystack_secret_key:
                        customer = await self._session.get(Customer, sub.customer_id)
                        plan = await self._session.get(HostingPlan, sub.plan_id)
                        name = (customer.full_name if customer else None) or "there"
                        plan_name = plan.name if plan else "hosting"
                        title, text, html, sms = email_templates.renewal_payment_needed(
                            name=name,
                            plan=plan_name,
                            expires_on=sub.expires_at.date().isoformat(),
                            grace_days=self._settings.subscription_grace_days,
                        )
                        await self._notify.notify(
                            sub.customer_id,
                            title=title,
                            body=text,
                            kind="renewal",
                            html_body=html,
                            email_subject=title,
                            sms_body=sms,
                        )
                        grace = timedelta(days=self._settings.subscription_grace_days)
                        sub.status = "grace"
                        sub.grace_until = now + grace
                        summary["grace"] += 1
                    else:
                        await self.renew(sub.customer_id, sub.id, auto=True)
                        summary["auto_renewed"] += 1
                    continue
                customer = await self._session.get(Customer, sub.customer_id)
                plan = await self._session.get(HostingPlan, sub.plan_id)
                name = (customer.full_name if customer else None) or "there"
                plan_name = plan.name if plan else "hosting"
                title, text, html, sms = email_templates.grace_started(
                    name=name,
                    plan=plan_name,
                    grace_days=self._settings.subscription_grace_days,
                )
                grace = timedelta(days=self._settings.subscription_grace_days)
                sub.status = "grace"
                sub.grace_until = now + grace
                await self._notify.notify(
                    sub.customer_id,
                    title=title,
                    body=text,
                    kind="grace",
                    html_body=html,
                    email_subject=title,
                    sms_body=sms,
                )
                summary["grace"] += 1

            if sub.status == "grace" and sub.grace_until and now >= sub.grace_until:
                sub.status = "suspended"
                await self._suspend_environments(sub, reason="Subscription grace period ended.")
                summary["suspended"] += 1

            if sub.status == "suspended" and sub.expires_at:
                terminate_after = timedelta(days=self._settings.subscription_terminate_after_days)
                if now >= sub.expires_at + terminate_after:
                    sub.status = "terminated"
                    await self._terminate_environments(sub)
                    summary["terminated"] += 1

            if (
                sub.status == "active"
                and UPGRADE_NUDGE_MIN_DAYS_LEFT <= days_left <= UPGRADE_NUDGE_MAX_DAYS_LEFT
            ):
                if await self._maybe_upgrade_nudge(sub):
                    summary["upgrade_nudged"] += 1

        await self._session.flush()
        logger.info("subscription_tick", **summary)
        return summary

    async def _remind(self, sub: Subscription, days_left: int) -> None:
        customer = await self._session.get(Customer, sub.customer_id)
        plan = await self._session.get(HostingPlan, sub.plan_id)
        name = (customer.full_name if customer else None) or "there"
        plan_name = plan.name if plan else "hosting"
        expires_on = sub.expires_at.date().isoformat() if sub.expires_at else "soon"
        title, text, html, sms = email_templates.renewal_reminder(
            name=name,
            days_left=days_left,
            expires_on=expires_on,
            plan=plan_name,
            auto_renew=bool(sub.auto_renew),
        )
        await self._notify.notify(
            sub.customer_id,
            title=title,
            body=text,
            kind=f"renewal_{days_left}",
            html_body=html,
            email_subject=title,
            sms_body=sms,
        )

    async def _maybe_upgrade_nudge(self, sub: Subscription) -> bool:
        """Occasional upgrade tip via panel + email + SMS (cooldown-deduped)."""
        plan = await self._session.get(HostingPlan, sub.plan_id)
        if plan is None or not plan.is_active:
            return False

        higher = await self._next_plan_up(plan)
        if higher is None:
            return False  # already on top package

        if await self._recent_kind(sub.customer_id, "upgrade_nudge", UPGRADE_NUDGE_COOLDOWN_DAYS):
            return False

        customer = await self._session.get(Customer, sub.customer_id)
        name = (customer.full_name if customer else None) or "there"
        title, text, html, sms = email_templates.upgrade_nudge(
            name=name,
            plan=plan.name,
            next_plan=higher.name,
        )
        await self._notify.notify(
            sub.customer_id,
            title=title,
            body=text,
            kind="upgrade_nudge",
            html_body=html,
            email_subject=title,
            sms_body=sms,
        )
        return True

    async def _next_plan_up(self, plan: HostingPlan) -> HostingPlan | None:
        result = await self._session.execute(
            select(HostingPlan)
            .where(HostingPlan.is_active.is_(True))
            .order_by(HostingPlan.price_monthly.asc(), HostingPlan.sort_order.asc())
        )
        plans = list(result.scalars().all())
        found = False
        for p in plans:
            if p.id == plan.id:
                found = True
                continue
            if found and p.price_monthly > plan.price_monthly:
                return p
        # Fallback: first plan strictly more expensive
        for p in plans:
            if p.price_monthly > plan.price_monthly:
                return p
        return None

    async def _recent_kind(self, customer_id: UUID, kind: str, within_days: int) -> bool:
        cutoff = datetime.now(UTC) - timedelta(days=within_days)
        result = await self._session.execute(
            select(Notification.id)
            .where(
                Notification.customer_id == customer_id,
                Notification.kind == kind,
                Notification.channel == "panel",
                Notification.created_at >= cutoff,
            )
            .limit(1)
        )
        return result.scalar_one_or_none() is not None

    async def _envs(self, subscription_id: UUID) -> list[CustomerEnvironment]:
        result = await self._session.execute(
            select(CustomerEnvironment).where(CustomerEnvironment.subscription_id == subscription_id)
        )
        return list(result.scalars().all())

    async def _suspend_environments(self, sub: Subscription, *, reason: str) -> None:
        for env in await self._envs(sub.id):
            if env.status == "terminated":
                continue
            env.status = "suspended"
            env.health_status = "warning"
        customer = await self._session.get(Customer, sub.customer_id)
        name = (customer.full_name if customer else None) or "there"
        title, text, html, sms = email_templates.hosting_suspended(name=name, reason=reason)
        await self._notify.notify(
            sub.customer_id,
            title=title,
            body=text,
            kind="suspend",
            html_body=html,
            email_subject=title,
            sms_body=sms,
        )

    async def _restore_environments(self, sub: Subscription) -> None:
        for env in await self._envs(sub.id):
            if env.status == "suspended":
                env.status = "active"
                env.health_status = "healthy"

    async def _terminate_environments(self, sub: Subscription) -> None:
        for env in await self._envs(sub.id):
            env.status = "terminated"
            env.health_status = "critical"
            self._isolation.stop_container(env.container_id, env_id=str(env.id))
        await self._notify.notify(
            sub.customer_id,
            title="Hosting terminated",
            body=(
                "The subscription was not renewed. Resources have been released. "
                "Open Plans if you want to start again."
            ),
            kind="terminate",
            sms_body="Hosting ended after non-renewal. Start again: ifnotus.space/account/plans",
        )
