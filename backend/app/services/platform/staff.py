"""Staff admin service for IFNOTUS product layer (customers, plans, orders)."""

from __future__ import annotations

import re
from decimal import Decimal
from uuid import UUID

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.exceptions import ConflictError, NotFoundError
from app.models.platform import (
    AiCreditAccount,
    Customer,
    CustomerEnvironment,
    HostingPlan,
    Order,
    Subscription,
)
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
                    )
                )
                .order_by(Customer.created_at.desc())
                .limit(limit)
            )
        result = await self._session.execute(stmt)
        customers = list(result.scalars().all())
        out: list[dict] = []
        for c in customers:
            env_count = await self._session.scalar(
                select(func.count())
                .select_from(CustomerEnvironment)
                .where(CustomerEnvironment.customer_id == c.id)
            )
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
            out.append(
                {
                    "id": c.id,
                    "email": c.email,
                    "full_name": c.full_name,
                    "phone": c.phone,
                    "company": c.company,
                    "email_verified": c.email_verified,
                    "created_at": c.created_at,
                    "environment_count": int(env_count or 0),
                    "subscription_count": int(sub_count or 0),
                    "credits_remaining": int(credits or 0),
                }
            )
        return out

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

    async def list_orders(
        self,
        *,
        payment_status: str | None = None,
        limit: int = 100,
    ) -> list[dict]:
        limit = max(1, min(limit, 500))
        stmt = (
            select(Order, Customer, HostingPlan)
            .join(Customer, Customer.id == Order.customer_id)
            .join(HostingPlan, HostingPlan.id == Order.plan_id)
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
                "customer_email": customer.email,
                "customer_name": customer.full_name,
                "customer_phone": customer.phone,
                "plan_id": order.plan_id,
                "plan_name": plan.name,
                "domain_name": order.domain_name,
                "domain_extension": order.domain_extension,
                "plan_price": order.plan_price,
                "domain_price": order.domain_price,
                "total_price": order.total_price,
                "currency": order.currency,
                "payment_status": order.payment_status,
                "provisioning_status": order.provisioning_status,
                "order_kind": order.order_kind,
                "paystack_reference": order.paystack_reference,
                "invoice_number": order.invoice_number,
                "payment_method": order.payment_method,
                "momo_transaction_id": order.momo_transaction_id,
                "paid_at": order.paid_at,
                "created_at": order.created_at,
            }
            for order, customer, plan in rows
        ]

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
