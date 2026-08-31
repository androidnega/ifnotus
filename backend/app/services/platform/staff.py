"""Staff admin service for IFNOTUS product layer (customers, plans, orders)."""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.exceptions import ConflictError, NotFoundError, ValidationError
from app.models.platform import (
    AiCreditAccount,
    Customer,
    CustomerEnvironment,
    HostingPlan,
    Order,
    PlatformAuditLog,
    Subscription,
    SupportTicket,
)
from app.models.user import User
from app.services.platform.lifecycle import EnvironmentLifecycleService


def _slugify(name: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", name.strip().lower()).strip("-")
    return (s or "plan")[:64]


class StaffPlatformService:
    def __init__(self, settings: Settings, session: AsyncSession) -> None:
        self._settings = settings
        self._session = session

    async def list_customers(self, *, q: str | None = None, limit: int = 100) -> list[dict]:
        limit = max(1, min(limit, 500))
        stmt = select(Customer).order_by(Customer.created_at.desc()).limit(limit)
        if q:
            like = f"%{q.strip().lower()}%"
            stmt = (
                select(Customer)
                .where(
                    or_(
                        func.lower(Customer.email).like(like),
                        func.lower(Customer.full_name).like(like),
                        func.lower(func.coalesce(Customer.company, "")).like(like),
                        func.lower(func.coalesce(Customer.phone, "")).like(like),
                    )
                )
                .order_by(Customer.created_at.desc())
                .limit(limit)
            )
        result = await self._session.execute(stmt)
        customers = list(result.scalars().all())
        out: list[dict] = []
        for c in customers:
            envs = list(
                (
                    await self._session.execute(
                        select(CustomerEnvironment)
                        .where(CustomerEnvironment.customer_id == c.id)
                        .order_by(CustomerEnvironment.created_at.desc())
                    )
                )
                .scalars()
                .all()
            )
            env_count = len(envs)
            sub_count = await self._session.scalar(
                select(func.count())
                .select_from(Subscription)
                .where(Subscription.customer_id == c.id)
            )
            credits = await self._session.scalar(
                select(AiCreditAccount.credits_remaining).where(
                    AiCreditAccount.customer_id == c.id
                )
            )
            awaiting = await self._session.scalar(
                select(func.count())
                .select_from(Order)
                .where(
                    Order.customer_id == c.id,
                    Order.payment_status == "submitted",
                )
            )
            setting_up = await self._session.scalar(
                select(func.count())
                .select_from(Order)
                .where(
                    Order.customer_id == c.id,
                    Order.payment_status == "paid",
                    Order.provisioning_status.in_(("pending", "queued", "running")),
                )
            )
            live = [e for e in envs if (e.status or "").lower() == "active"]
            suspended = [e for e in envs if (e.status or "").lower() == "suspended"]
            if awaiting:
                hosting_status = "awaiting_payment"
            elif setting_up:
                hosting_status = "setting_up"
            elif live:
                hosting_status = "live"
            elif suspended:
                hosting_status = "suspended"
            elif env_count:
                hosting_status = "inactive"
            else:
                hosting_status = "none"
            primary = None
            for e in live or suspended or envs:
                if e.domain:
                    primary = e.domain
                    break
            out.append(
                {
                    "id": c.id,
                    "email": c.email,
                    "full_name": c.full_name,
                    "phone": c.phone,
                    "company": c.company,
                    "email_verified": c.email_verified,
                    "created_at": c.created_at,
                    "environment_count": env_count,
                    "subscription_count": int(sub_count or 0),
                    "credits_remaining": int(credits or 0),
                    "hosting_status": hosting_status,
                    "primary_domain": primary,
                    "awaiting_payment_count": int(awaiting or 0),
                }
            )
        return out

    async def delete_customer(
        self,
        customer_id: UUID,
        *,
        confirm_email: str,
        actor_id: UUID | None = None,
    ) -> dict:
        """Super-admin: tear down environments and remove customer + login."""
        customer = await self._session.get(Customer, customer_id)
        if customer is None:
            raise NotFoundError("Customer not found.")
        typed = (confirm_email or "").strip().lower()
        if typed != (customer.email or "").strip().lower():
            raise ValidationError(
                "Type the customer email exactly to confirm deletion.",
                code="confirm_email_mismatch",
            )

        user = await self._session.get(User, customer.user_id)
        if user is not None:
            roles = {str(r).lower() for r in (user.roles or [])}
            if user.is_superuser or roles & {"superadmin", "admin", "hosting", "support"}:
                raise ValidationError(
                    "This account has staff roles. Remove staff access first, then delete.",
                    code="staff_account_protected",
                )

        lifecycle = EnvironmentLifecycleService(self._settings, self._session)
        from sqlalchemy import text

        env_rows = (
            await self._session.execute(
                text(
                    "SELECT id FROM customer_environments WHERE customer_id = :cid"
                ),
                {"cid": str(customer_id)},
            )
        ).all()
        env_ids = [UUID(str(row[0])) for row in env_rows]
        envs = []
        for env_id in env_ids:
            env = await self._session.get(CustomerEnvironment, env_id)
            if env is not None:
                envs.append(env)
        terminated = 0
        for env in envs:
            if (env.status or "").lower() != "terminated":
                await lifecycle.terminate(customer_id, env.id, notify_customer=False)
                terminated += 1

        for sub in (
            await self._session.execute(
                select(Subscription).where(Subscription.customer_id == customer_id)
            )
        ).scalars().all():
            if (sub.status or "").lower() not in {"terminated", "cancelled"}:
                sub.status = "terminated"
                sub.auto_renew = False

        email = customer.email
        name = customer.full_name
        user_id = customer.user_id
        storage_slug = getattr(customer, "storage_slug", None)

        from app.services.platform.customer_storage import purge_customer_storage

        disk = purge_customer_storage(self._settings, customer, envs=envs)

        self._session.add(
            PlatformAuditLog(
                customer_id=None,
                actor_id=actor_id,
                action="customer.deleted",
                target_type="customer",
                target_id=str(customer_id),
                result="success",
                metadata_json={
                    "email": email,
                    "full_name": name,
                    "phone": customer.phone,
                    "environments_terminated": terminated,
                    "storage_removed": disk.get("removed_paths") or [],
                    "storage_errors": disk.get("errors") or [],
                },
            )
        )
        await self._session.flush()

        # ORM would try SET NULL on orders.customer_id (NOT NULL). Detach money +
        # related rows first, then remove the customer so DB CASCADE can finish.
        from sqlalchemy import delete, update

        await self._session.execute(
            update(Subscription)
            .where(Subscription.customer_id == customer_id)
            .values(order_id=None)
        )
        await self._session.execute(delete(Order).where(Order.customer_id == customer_id))
        await self._session.execute(delete(Customer).where(Customer.id == customer_id))
        await self._session.flush()

        if user is not None:
            await self._session.execute(delete(User).where(User.id == user_id))
            await self._session.flush()

        removed_note = ""
        if disk.get("removed_paths"):
            removed_note = f" Removed {len(disk['removed_paths'])} storage folder(s)."
        elif storage_slug:
            removed_note = " No on-disk storage folder found."

        return {
            "message": (
                f"Deleted {name} ({email}). {terminated} environment(s) terminated."
                f"{removed_note}"
            ),
            "customer_id": str(customer_id),
            "environments_terminated": terminated,
            "storage_removed": disk.get("removed_paths") or [],
        }

    async def get_customer(self, customer_id: UUID) -> dict:
        customer = await self._session.get(Customer, customer_id)
        if customer is None:
            raise NotFoundError("Customer not found.")

        subs = list(
            (
                await self._session.execute(
                    select(Subscription)
                    .where(Subscription.customer_id == customer_id)
                    .order_by(Subscription.created_at.desc())
                )
            )
            .scalars()
            .all()
        )
        envs = list(
            (
                await self._session.execute(
                    select(CustomerEnvironment)
                    .where(CustomerEnvironment.customer_id == customer_id)
                    .order_by(CustomerEnvironment.created_at.desc())
                )
            )
            .scalars()
            .all()
        )
        orders = list(
            (
                await self._session.execute(
                    select(Order)
                    .where(Order.customer_id == customer_id)
                    .order_by(Order.created_at.desc())
                    .limit(50)
                )
            )
            .scalars()
            .all()
        )
        credits_row = (
            await self._session.execute(
                select(AiCreditAccount).where(AiCreditAccount.customer_id == customer_id)
            )
        ).scalar_one_or_none()

        plan_ids = {s.plan_id for s in subs} | {o.plan_id for o in orders}
        plans: dict[UUID, HostingPlan] = {}
        if plan_ids:
            rows = (
                await self._session.execute(select(HostingPlan).where(HostingPlan.id.in_(plan_ids)))
            ).scalars()
            plans = {p.id: p for p in rows}

        return {
            "customer": customer,
            "credits_remaining": credits_row.credits_remaining if credits_row else 0,
            "subscriptions": [
                {
                    "id": s.id,
                    "plan_id": s.plan_id,
                    "plan_name": plans.get(s.plan_id).name if plans.get(s.plan_id) else None,
                    "status": s.status,
                    "cpu_allocated": s.cpu_allocated,
                    "ram_allocated": s.ram_allocated,
                    "storage_allocated": s.storage_allocated,
                    "expires_at": s.expires_at,
                    "auto_renew": s.auto_renew,
                    "grace_until": s.grace_until,
                }
                for s in subs
            ],
            "environments": [self._env_detail_row(e) for e in envs],
            "audit": await self.list_customer_audit(customer_id, limit=40),
            "orders": [
                {
                    "id": o.id,
                    "plan_id": o.plan_id,
                    "plan_name": plans.get(o.plan_id).name if plans.get(o.plan_id) else None,
                    "domain_name": o.domain_name,
                    "total_price": o.total_price,
                    "currency": o.currency,
                    "payment_status": o.payment_status,
                    "provisioning_status": o.provisioning_status,
                    "order_kind": o.order_kind,
                    "paystack_reference": o.paystack_reference,
                    "invoice_number": o.invoice_number,
                    "payment_method": o.payment_method,
                    "momo_transaction_id": o.momo_transaction_id,
                    "paid_at": o.paid_at,
                    "created_at": o.created_at,
                    "customer_id": o.customer_id,
                }
                for o in orders
            ],
        }

    async def update_customer(
        self,
        customer_id: UUID,
        body,
        *,
        actor_id: UUID,
    ) -> Customer:
        """Staff: update tenant phone, email, and profile fields."""
        from app.schemas.platform import CustomerProfileUpdateRequest
        from app.services.platform.customers import CustomerService

        customer = await self._session.get(Customer, customer_id)
        if customer is None:
            raise NotFoundError("Customer not found.")

        patch_fields = {}
        for key in ("email", "phone", "first_name", "last_name", "full_name", "company"):
            val = getattr(body, key, None)
            if val is not None:
                patch_fields[key] = val

        if patch_fields.get("phone"):
            normalized = CustomerService.normalize_phone(patch_fields["phone"])
            clash = (
                await self._session.execute(
                    select(Customer).where(Customer.phone == normalized, Customer.id != customer_id)
                )
            ).scalar_one_or_none()
            if clash is not None:
                raise ConflictError("Another account already uses this phone number.")
            patch_fields["phone"] = normalized

        if patch_fields:
            patch = CustomerProfileUpdateRequest(**patch_fields)
            user = await self._session.get(User, customer.user_id)
            await CustomerService(self._settings, self._session).update_profile(
                customer, patch, user=user
            )

        if getattr(body, "phone_verified", None) is not None:
            customer.phone_verified = bool(body.phone_verified)
        elif patch_fields.get("phone"):
            customer.phone_verified = True

        if getattr(body, "email_verified", None) is not None:
            customer.email_verified = bool(body.email_verified)
        elif patch_fields.get("email"):
            pass  # update_profile clears email_verified until re-verified

        self._session.add(
            PlatformAuditLog(
                customer_id=customer.id,
                action="staff.customer.update",
                target_type="customer",
                target_id=str(customer.id),
                result="success",
                metadata_json={
                    "actor_id": str(actor_id),
                    "fields": sorted(patch_fields.keys())
                    + [
                        k
                        for k, v in (
                            ("phone_verified", getattr(body, "phone_verified", None)),
                            ("email_verified", getattr(body, "email_verified", None)),
                        )
                        if v is not None
                    ],
                },
            )
        )
        await self._session.flush()
        return customer

    async def list_orders(
        self,
        *,
        payment_status: str | None = None,
        limit: int = 100,
        mask_financials: bool = False,
    ) -> list[dict]:
        from app.models.user import User

        limit = max(1, min(limit, 500))
        stmt = (
            select(Order, Customer, HostingPlan, User)
            .outerjoin(Customer, Customer.id == Order.customer_id)
            .outerjoin(HostingPlan, HostingPlan.id == Order.plan_id)
            .outerjoin(User, User.id == Order.payment_confirmed_by)
            .order_by(Order.created_at.desc())
            .limit(limit)
        )
        if payment_status:
            stmt = stmt.where(Order.payment_status == payment_status)
        rows = (await self._session.execute(stmt)).all()
        return [
            {
                "id": order.id,
                "customer_id": order.customer_id,
                "customer_email": customer.email if customer else "unknown@ifnotus.space",
                "customer_name": customer.full_name if customer else "Customer",
                "customer_phone": customer.phone if customer else None,
                "plan_id": order.plan_id,
                "plan_name": plan.name if plan else (order.order_kind.title() if order.order_kind else "Hosting Plan"),
                "domain_name": order.domain_name,
                "domain_extension": order.domain_extension,
                "plan_price": Decimal("0.00") if mask_financials else order.plan_price,
                "domain_price": Decimal("0.00") if mask_financials else order.domain_price,
                "total_price": Decimal("0.00") if mask_financials else order.total_price,
                "currency": "" if mask_financials else order.currency,
                "payment_status": order.payment_status,
                "provisioning_status": order.provisioning_status,
                "order_kind": order.order_kind,
                "paystack_reference": order.paystack_reference,
                "invoice_number": order.invoice_number,
                "payment_method": order.payment_method,
                "momo_transaction_id": order.momo_transaction_id,
                "payment_amount_received": None if mask_financials else order.payment_amount_received,
                "payment_notes": order.payment_notes,
                "payment_confirmed_at": order.payment_confirmed_at,
                "payment_confirmed_by": order.payment_confirmed_by,
                "payment_confirmed_by_name": staff_user.full_name or staff_user.username if staff_user else None,
                "payment_confirmed_by_email": staff_user.email if staff_user else None,
                "paid_at": order.paid_at,
                "created_at": order.created_at,
            }
            for order, customer, plan, staff_user in rows
        ]

    async def ops_inbox(self, *, paid_within_hours: int = 48, mask_financials: bool = False) -> dict:
        """Staff cPanel inbox: MoMo awaiting confirm + recently paid invoices."""
        submitted = await self.list_orders(payment_status="submitted", limit=50, mask_financials=mask_financials)
        since = datetime.now(UTC) - timedelta(hours=max(1, min(paid_within_hours, 168)))
        paid_stmt = (
            select(Order, Customer, HostingPlan)
            .join(Customer, Customer.id == Order.customer_id)
            .join(HostingPlan, HostingPlan.id == Order.plan_id)
            .where(
                Order.payment_status == "paid",
                Order.paid_at.is_not(None),
                Order.paid_at >= since,
            )
            .order_by(Order.paid_at.desc())
            .limit(30)
        )
        paid_rows = (await self._session.execute(paid_stmt)).all()

        items: list[dict] = []
        for row in submitted:
            inv = row.get("invoice_number") or str(row["id"])[:8]
            who = row.get("customer_name") or row.get("customer_email") or "Customer"
            domain = row.get("domain_name") or "hosting"
            amount_text = f" · {row.get('currency') or 'GHS'} {row.get('total_price')}" if not mask_financials else ""
            txn = row.get("momo_transaction_id") or "—"
            items.append(
                {
                    "id": f"momo-submitted-{row['id']}",
                    "kind": "momo_submitted",
                    "title": "New payment to confirm",
                    "message": (
                        f"{inv}{amount_text} · {who} · {domain}. "
                        f"MoMo ID {txn}."
                    ),
                    "severity": "warning",
                    "timestamp": row.get("created_at") or datetime.now(UTC),
                    "href": "/platform/orders",
                    "order_id": row["id"],
                    "invoice_number": row.get("invoice_number"),
                }
            )

        for order, customer, plan in paid_rows:
            inv = order.invoice_number or str(order.id)[:8]
            who = customer.full_name or customer.email or "Customer"
            domain = order.domain_name or plan.name or "hosting"
            amount_text = f" · {order.currency} {order.total_price}" if not mask_financials else ""
            items.append(
                {
                    "id": f"invoice-paid-{order.id}",
                    "kind": "invoice_paid",
                    "title": "Hosting invoice paid",
                    "message": (
                        f"{inv}{amount_text} · {who} · {domain} "
                        f"({order.provisioning_status})."
                    ),
                    "severity": "info",
                    "timestamp": order.paid_at or order.created_at or datetime.now(UTC),
                    "href": "/platform/orders",
                    "order_id": order.id,
                    "invoice_number": order.invoice_number,
                }
            )

        items.sort(
            key=lambda x: x["timestamp"] or datetime.min.replace(tzinfo=UTC),
            reverse=True,
        )
        open_support = int(
            (
                await self._session.execute(
                    select(func.count())
                    .select_from(SupportTicket)
                    .where(SupportTicket.status == "open")
                )
            ).scalar_one()
            or 0
        )
        return {
            "awaiting_payment_confirm": len(submitted),
            "recently_paid": len(paid_rows),
            "open_support_tickets": open_support,
            "items": items,
        }

    async def list_plans(self, *, include_inactive: bool = True) -> list[HostingPlan]:
        stmt = select(HostingPlan).order_by(HostingPlan.sort_order, HostingPlan.name)
        if not include_inactive:
            stmt = stmt.where(HostingPlan.is_active.is_(True))
        return list((await self._session.execute(stmt)).scalars().all())

    async def rebalance_plans_from_price(self) -> list[HostingPlan]:
        """Recalculate cpu/ram/storage/bandwidth/ai from each plan's monthly price."""
        from app.services.platform.plan_sizing import resources_from_price

        plans = await self.list_plans(include_inactive=True)
        for plan in plans:
            sized = resources_from_price(plan.price_monthly)
            plan.cpu_cores = Decimal(str(sized["cpu_cores"]))
            plan.ram_gb = Decimal(str(sized["ram_gb"]))
            plan.storage_gb = int(sized["storage_gb"])
            plan.bandwidth_tb = Decimal(str(sized["bandwidth_tb"]))
            plan.ai_credits = int(sized["ai_credits"])
        await self._session.flush()
        return plans

    async def create_plan(self, data: dict) -> HostingPlan:
        from app.services.platform.plan_sizing import resources_from_price

        slug = (data.get("slug") or _slugify(data["name"])).strip().lower()
        existing = (
            await self._session.execute(select(HostingPlan).where(HostingPlan.slug == slug))
        ).scalar_one_or_none()
        if existing:
            raise ConflictError(f"Plan slug '{slug}' already exists.")

        price = Decimal(str(data["price_monthly"]))
        sized = resources_from_price(price)
        # Default: derive from price. Opt out with size_from_price=false + explicit fields.
        if data.get("size_from_price", True):
            cpu, ram, storage, bandwidth, ai_credits = (
                sized["cpu_cores"],
                sized["ram_gb"],
                sized["storage_gb"],
                sized["bandwidth_tb"],
                sized["ai_credits"],
            )
        else:
            cpu = data.get("cpu_cores") or sized["cpu_cores"]
            ram = data.get("ram_gb") or sized["ram_gb"]
            storage = data.get("storage_gb") or sized["storage_gb"]
            bandwidth = data.get("bandwidth_tb") or sized["bandwidth_tb"]
            ai_credits = data.get("ai_credits") if data.get("ai_credits") is not None else sized["ai_credits"]

        plan = HostingPlan(
            slug=slug,
            name=data["name"].strip(),
            cpu_cores=Decimal(str(cpu)),
            ram_gb=Decimal(str(ram)),
            storage_gb=int(storage),
            bandwidth_tb=Decimal(str(bandwidth)),
            ai_credits=int(ai_credits or 0),
            price_monthly=price,
            price_yearly=(
                Decimal(str(data["price_yearly"])) if data.get("price_yearly") is not None else None
            ),
            currency=(data.get("currency") or "GHS").upper()[:8],
            features=data.get("features") or {},
            sort_order=int(data.get("sort_order") or 0),
            is_active=bool(data.get("is_active", True)),
        )
        self._session.add(plan)
        await self._session.flush()
        return plan

    async def update_plan(self, plan_id: UUID, data: dict) -> HostingPlan:
        from app.services.platform.plan_sizing import resources_from_price

        plan = await self._session.get(HostingPlan, plan_id)
        if plan is None:
            raise NotFoundError("Plan not found.")
        if "slug" in data and data["slug"]:
            slug = str(data["slug"]).strip().lower()
            clash = (
                await self._session.execute(
                    select(HostingPlan).where(HostingPlan.slug == slug, HostingPlan.id != plan_id)
                )
            ).scalar_one_or_none()
            if clash:
                raise ConflictError(f"Plan slug '{slug}' already exists.")
            plan.slug = slug
        for field in (
            "name",
            "storage_gb",
            "ai_credits",
            "sort_order",
            "is_active",
            "currency",
            "features",
        ):
            if field in data and data[field] is not None:
                setattr(plan, field, data[field])
        if "cpu_cores" in data and data["cpu_cores"] is not None:
            plan.cpu_cores = Decimal(str(data["cpu_cores"]))
        if "ram_gb" in data and data["ram_gb"] is not None:
            plan.ram_gb = Decimal(str(data["ram_gb"]))
        if "bandwidth_tb" in data and data["bandwidth_tb"] is not None:
            plan.bandwidth_tb = Decimal(str(data["bandwidth_tb"]))
        if "price_monthly" in data and data["price_monthly"] is not None:
            plan.price_monthly = Decimal(str(data["price_monthly"]))
        if "price_yearly" in data:
            plan.price_yearly = (
                Decimal(str(data["price_yearly"])) if data["price_yearly"] is not None else None
            )
        # Re-derive resources from price when asked, or when price changes without cpu/ram.
        should_size = bool(data.get("size_from_price")) or (
            "price_monthly" in data
            and "cpu_cores" not in data
            and "ram_gb" not in data
        )
        if should_size:
            sized = resources_from_price(plan.price_monthly)
            plan.cpu_cores = Decimal(str(sized["cpu_cores"]))
            plan.ram_gb = Decimal(str(sized["ram_gb"]))
            if "storage_gb" not in data or data.get("size_from_price"):
                plan.storage_gb = int(sized["storage_gb"])
            if "bandwidth_tb" not in data or data.get("size_from_price"):
                plan.bandwidth_tb = Decimal(str(sized["bandwidth_tb"]))
            if "ai_credits" not in data or data.get("size_from_price"):
                plan.ai_credits = int(sized["ai_credits"])
        await self._session.flush()
        return plan

    async def set_plan_active(self, plan_id: UUID, active: bool) -> HostingPlan:
        return await self.update_plan(plan_id, {"is_active": active})

    def _env_detail_row(self, e: CustomerEnvironment) -> dict:
        from app.services.platform.stacks import EnvironmentStackService

        current = EnvironmentStackService(self._settings, self._session).current_stack(e)
        progress = EnvironmentStackService(self._settings, self._session).read_progress(e)
        return {
            "id": e.id,
            "subscription_id": e.subscription_id,
            "domain": e.domain,
            "status": e.status,
            "health_status": e.health_status,
            "isolation_type": e.isolation_type,
            "cpu_limit": e.cpu_limit,
            "ram_limit_gb": e.ram_limit_gb,
            "storage_limit_gb": e.storage_limit_gb,
            "document_root": e.document_root,
            "db_engine": e.db_engine,
            "db_name": e.db_name,
            "created_at": e.created_at,
            "container_id": e.container_id,
            "ftp_username": e.ftp_username,
            "stack": current,
            "stack_progress": progress,
        }

    async def list_customer_audit(self, customer_id: UUID, *, limit: int = 50) -> list[dict]:
        from app.models.platform import PlatformAuditLog

        limit = max(1, min(limit, 200))
        rows = list(
            (
                await self._session.execute(
                    select(PlatformAuditLog)
                    .where(PlatformAuditLog.customer_id == customer_id)
                    .order_by(PlatformAuditLog.occurred_at.desc())
                    .limit(limit)
                )
            )
            .scalars()
            .all()
        )
        return [
            {
                "id": r.id,
                "occurred_at": r.occurred_at,
                "action": r.action,
                "target_type": r.target_type,
                "target_id": r.target_id,
                "result": r.result,
                "metadata": r.metadata_json or {},
            }
            for r in rows
        ]

    async def get_environment(self, environment_id: UUID) -> CustomerEnvironment:
        env = await self._session.get(CustomerEnvironment, environment_id)
        if env is None:
            raise NotFoundError("Environment not found.")
        return env

    async def suspend_environment(self, environment_id: UUID) -> CustomerEnvironment:
        env = await self.get_environment(environment_id)
        return await EnvironmentLifecycleService(self._settings, self._session).suspend(
            env.customer_id, environment_id
        )

    async def restore_environment(self, environment_id: UUID) -> CustomerEnvironment:
        env = await self.get_environment(environment_id)
        return await EnvironmentLifecycleService(self._settings, self._session).restore(
            env.customer_id, environment_id
        )

    async def terminate_environment(self, environment_id: UUID) -> CustomerEnvironment:
        env = await self.get_environment(environment_id)
        return await EnvironmentLifecycleService(self._settings, self._session).terminate(
            env.customer_id, environment_id
        )

    async def update_environment_subdomain(
        self,
        environment_id: UUID,
        new_domain: str,
        *,
        actor_id: UUID | None = None,
    ) -> CustomerEnvironment:
        env = await self.get_environment(environment_id)
        raw_name = (new_domain or "").strip().lower()
        if not raw_name:
            raise ValidationError("Domain or subdomain is required.")
        if "." not in raw_name:
            raw_name = f"{raw_name}.ifnotus.space"
        if not re.match(r"^[a-z0-9]([a-z0-9\-]{0,61}[a-z0-9])?(\.[a-z0-9]([a-z0-9\-]{0,61}[a-z0-9])?)+$", raw_name):
            raise ValidationError("Invalid subdomain or domain format (e.g. username.ifnotus.space or domain.com).")

        old_domain = env.domain
        if old_domain == raw_name:
            return env

        clash_stmt = select(CustomerEnvironment).where(
            CustomerEnvironment.domain == raw_name,
            CustomerEnvironment.id != environment_id,
        )
        existing = (await self._session.execute(clash_stmt)).scalar_one_or_none()
        if existing:
            raise ConflictError(f"Domain/subdomain '{raw_name}' is already assigned to another environment.")

        env.domain = raw_name

        # Update CustomerDomain if present
        from app.models.platform import CustomerDomain
        cd_stmt = select(CustomerDomain).where(CustomerDomain.customer_id == env.customer_id)
        cd = (await self._session.execute(cd_stmt)).scalar_one_or_none()
        if cd:
            cd.domain_name = raw_name
        else:
            self._session.add(
                CustomerDomain(
                    customer_id=env.customer_id,
                    domain_name=raw_name,
                    environment_id=env.id,
                    status="active",
                    ssl_status="active",
                )
            )

        if env.document_root:
            from app.services.hosting.nginx_provisioner import DomainNginxProvisioner
            from app.models.hosting import Domain
            from app.repositories.domain import DomainRepository

            provisioner = DomainNginxProvisioner(self._settings)
            dom_repo = DomainRepository(self._session)
            if old_domain and old_domain != raw_name:
                old_dom = await dom_repo.get_by_name(old_domain)
                if old_dom:
                    old_dom.name = raw_name
                    old_dom.document_root = env.document_root
                    old_dom.nginx_site = provisioner.site_name(raw_name)
                    old_dom.force_https = True
                    await dom_repo.update(old_dom)
                try:
                    await provisioner.remove(old_domain, remove_files=False)
                except Exception:
                    pass
            else:
                existing_dom = await dom_repo.get_by_name(raw_name)
                if not existing_dom:
                    await dom_repo.create(
                        Domain(
                            name=raw_name,
                            domain_type="primary" if "." not in raw_name.replace(".ifnotus.space", "") else "subdomain",
                            document_root=env.document_root,
                            proxy_port=env.container_port,
                            enabled=True,
                            nginx_enabled=True,
                            nginx_site=provisioner.site_name(raw_name),
                            force_https=True,
                        )
                    )
            try:
                await provisioner.provision(
                    hostname=raw_name,
                    document_root=env.document_root,
                    proxy_port=None,
                    force_https=True,
                )
            except Exception as e:
                logger.warning("update_env_nginx_provision_failed", error=str(e), domain=raw_name)

        if not raw_name.endswith(".ifnotus.space") and not raw_name.endswith(".serverlabsttu.space"):
            from app.services.platform.authoritative_dns import AuthoritativeDnsService
            try:
                AuthoritativeDnsService(self._settings).ensure_zone(raw_name)
            except Exception as e:
                logger.warning("update_env_dns_zone_failed", error=str(e), domain=raw_name)
        elif raw_name.endswith(".customers.ifnotus.space"):
            from app.services.platform.authoritative_dns import AuthoritativeDnsService
            try:
                AuthoritativeDnsService(self._settings).ensure_generated_environment_dns(raw_name)
            except Exception as e:
                logger.warning("update_env_dns_zone_failed", error=str(e), domain=raw_name)

        # Update any active or recent orders for this customer to reflect the updated domain/subdomain
        from app.models.platform import Order
        ord_stmt = select(Order).where(Order.customer_id == env.customer_id)
        orders = (await self._session.execute(ord_stmt)).scalars().all()
        for ord_row in orders:
            if not ord_row.domain_name or ord_row.domain_name == old_domain:
                ord_row.domain_name = raw_name

        self._session.add(
            PlatformAuditLog(
                customer_id=env.customer_id,
                actor_id=actor_id,
                action="environment.subdomain_updated",
                target_type="environment",
                target_id=str(environment_id),
                result="success",
                metadata_json={"old_domain": old_domain, "new_domain": raw_name},
            )
        )
        await self._session.flush()
        return env

    def env_item_payload(self, env: CustomerEnvironment) -> dict:
        return self._env_detail_row(env)

    async def create_staff_user(self, *, email: str, password: str, full_name: str, role: str) -> dict:
        from app.core.permissions import CREATABLE_STAFF_ROLES
        from app.core.security import hash_password
        from app.models.user import User

        role_key = (role or "operator").strip().lower()
        if role_key not in CREATABLE_STAFF_ROLES:
            raise ConflictError("That staff role is not allowed.")
        email_n = email.lower().strip()
        existing = await self._session.execute(select(User).where(User.email == email_n))
        if existing.scalar_one_or_none():
            raise ConflictError("An account with this email already exists.")
        username = re.sub(r"[^a-z0-9]+", "", email_n.split("@")[0])[:24] or "staff"
        clash = await self._session.execute(select(User).where(User.username == username))
        if clash.scalar_one_or_none():
            username = f"{username}{secrets_token()}"
        user = User(
            email=email_n,
            username=username[:64],
            hashed_password=hash_password(password),
            full_name=full_name.strip(),
            is_active=True,
            is_superuser=False,
            roles=[role_key],
        )
        self._session.add(user)
        await self._session.flush()
        return {
            "id": str(user.id),
            "email": user.email,
            "username": user.username,
            "full_name": user.full_name,
            "roles": user.roles,
            "is_active": user.is_active,
        }

    async def list_staff_users(self) -> list[dict]:
        from app.core.permissions import STAFF_ROLE_VALUES
        from app.models.user import User

        rows = list(
            (await self._session.execute(select(User).order_by(User.created_at.desc())))
            .scalars()
            .all()
        )
        out: list[dict] = []
        for user in rows:
            roles = {str(r).lower() for r in (user.roles or [])}
            if user.is_superuser or roles.intersection(STAFF_ROLE_VALUES):
                # Never list pure customer portal accounts here.
                if roles == {"customer"} and not user.is_superuser:
                    continue
                out.append(
                    {
                        "id": user.id,
                        "email": user.email,
                        "username": user.username,
                        "full_name": user.full_name,
                        "roles": list(user.roles or []),
                        "is_active": bool(user.is_active),
                        "is_superuser": bool(user.is_superuser),
                        "created_at": user.created_at,
                        "last_login_at": user.last_login_at,
                        "last_login_ip": user.last_login_ip,
                    }
                )
        return out

    async def update_staff_user(
        self,
        user_id: UUID,
        *,
        is_active: bool | None = None,
        role: str | None = None,
        full_name: str | None = None,
        password: str | None = None,
    ) -> dict:
        from app.core.exceptions import NotFoundError, ValidationError
        from app.core.permissions import CREATABLE_STAFF_ROLES, Role
        from app.core.security import hash_password
        from app.models.user import User

        user = await self._session.get(User, user_id)
        if user is None:
            raise NotFoundError("Staff user not found.")
        roles = {str(r).lower() for r in (user.roles or [])}
        if roles == {"customer"} and not user.is_superuser:
            raise ValidationError("Client portal accounts are managed under Customers.")
        if user.is_superuser or Role.SUPERADMIN.value in roles:
            raise ValidationError("The super admin account cannot be edited here.")

        if is_active is not None:
            user.is_active = bool(is_active)
        if full_name is not None:
            user.full_name = full_name.strip()
        if password:
            user.hashed_password = hash_password(password)
        if role is not None:
            role_key = role.strip().lower()
            if role_key not in CREATABLE_STAFF_ROLES:
                raise ConflictError("That staff role is not allowed.")
            user.roles = [role_key]
            user.is_superuser = False
        await self._session.flush()
        return {
            "id": user.id,
            "email": user.email,
            "username": user.username,
            "full_name": user.full_name,
            "roles": list(user.roles or []),
            "is_active": bool(user.is_active),
            "is_superuser": bool(user.is_superuser),
            "created_at": user.created_at,
            "last_login_at": user.last_login_at,
            "last_login_ip": user.last_login_ip,
        }


def secrets_token() -> str:
    import secrets

    return secrets.token_hex(3)
