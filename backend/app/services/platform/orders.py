"""Orders + subscription creation after verified payment."""

from __future__ import annotations

import secrets
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.exceptions import AppException, ConflictError, NotFoundError, ValidationError
from app.core.logging import get_logger
from app.models.platform import (
    AiCreditAccount,
    Customer,
    CustomerDomain,
    HostingPlan,
    Order,
    PlatformAuditLog,
    PlatformJob,
    Subscription,
)
from app.schemas.platform import CreateOrderRequest, InvoiceViewResponse, OrderResponse
from app.services.platform import email_templates
from app.services.platform.integrations_store import IntegrationsSettingsStore
from app.services.platform.notifications import NotificationService
from app.services.platform.paystack import PaystackService
from app.services.platform.resources import ResourceManager


logger = get_logger(__name__)

DOMAIN_PRICES = {
    ".online": Decimal("50"),
    ".com": Decimal("250"),
    ".org": Decimal("180"),
    ".net": Decimal("200"),
}


class OrderService:
    def __init__(self, settings: Settings, session: AsyncSession) -> None:
        self._settings = settings
        self._session = session
        self._paystack = PaystackService(settings)
        self._resources = ResourceManager(session)

    async def create_order(self, customer: Customer, body: CreateOrderRequest, *, notify: bool = True) -> dict:
        plan = await self._get_plan(body.plan_id)
        # Capacity check before accepting payment
        await self._resources.pick_node_for_plan(plan)

        domain_name = (body.domain_name or "").lower().strip() or None
        extension = (body.domain_extension or "").lower().strip() or None
        if domain_name and not extension and "." in domain_name:
            _host, ext = domain_name.split(".", 1)
            extension = f".{ext}" if not ext.startswith(".") else ext

        from app.services.platform.student_hostname import (
            StudentHostnameService,
            is_student_hostname,
            normalize_surname,
            student_zone_extension,
        )

        kind = (body.domain_kind or "register").strip().lower()
        include_domain = bool(body.include_domain)
        meta: dict = {"domain_kind": kind, "include_domain": include_domain}

        if is_student_hostname(domain_name or "", settings=self._settings):
            kind = "student"

        if kind == "student":
            include_domain = False
            meta["domain_kind"] = "student"
            meta["include_domain"] = False
            svc = StudentHostnameService(self._session, self._settings)
            surname = (body.student_surname or "").strip()
            if not surname:
                from app.services.platform.customers import CustomerService

                surname = CustomerService.resolved_last_name(customer) or ""
            if surname:
                domain_name = await svc.allocate(surname)
                meta["student_surname"] = normalize_surname(surname)
            elif is_student_hostname(domain_name or "", settings=self._settings):
                domain_name = await svc.claim(domain_name or "")
                meta["student_surname"] = normalize_surname((domain_name or "").split(".", 1)[0])
            else:
                raise ValidationError(
                    "Enter your family name for the student address.",
                    code="student_surname_required",
                )
            extension = student_zone_extension(self._settings)
            meta["student_zone"] = extension.lstrip(".")
        elif kind in {"own", "transfer"}:
            include_domain = False
            meta["include_domain"] = False
            if not domain_name:
                raise ValidationError("Enter the domain you already have.", code="domain_required")
        elif include_domain:
            from app.services.platform.registrar import DomainRegistrar

            if not DomainRegistrar(self._settings).enabled:
                raise ValidationError(
                    "We are not registering new domains yet. Choose Student or a domain you already own.",
                    code="registrar_unavailable",
                )
            if not domain_name:
                raise ValidationError("Enter a domain name to register.", code="domain_required")

        domain_price = Decimal("0")
        if include_domain and extension:
            domain_price = DOMAIN_PRICES.get(extension, Decimal("0"))

        plan_price = plan.price_monthly
        total = plan_price + domain_price
        order = Order(
            customer_id=customer.id,
            plan_id=plan.id,
            domain_name=domain_name,
            domain_extension=extension,
            plan_price=plan_price,
            domain_price=domain_price,
            total_price=total,
            currency=plan.currency or "GHS",
            payment_status="pending",
            provisioning_status="pending",
            payment_method="momo",
            invoice_number=await self._new_invoice(),
            expires_at=datetime.now(UTC) + timedelta(days=30),
            meta_json=meta,
        )
        self._session.add(order)
        await self._session.flush()

        reference = self._paystack.new_reference()
        order.paystack_reference = reference
        if notify:
            await self._notify_invoice(customer, order, plan.name)
        self._session.add(
            PlatformAuditLog(
                customer_id=customer.id,
                action="order.create",
                target_type="order",
                target_id=str(order.id),
                result="success",
                metadata_json={"total": str(total), "reference": reference, "invoice": order.invoice_number},
            )
        )
        await self._session.flush()
        return {
            "order": OrderResponse.model_validate(order),
            "authorization_url": None,
            "reference": reference,
            "demo": False,
            "paystack_public_key": None,
            "payment_method": "momo",
            "invoice_number": order.invoice_number,
            "momo": self._momo_details(),
        }

    async def verify_and_activate(self, reference: str) -> OrderResponse:
        order = await self._get_by_reference(reference)
        if order.payment_status == "paid":
            return OrderResponse.model_validate(order)
        if (order.payment_method or "momo") == "momo":
            raise AppException(
                "This invoice is paid by Mobile Money. Enter your transaction ID, then wait for confirmation.",
                code="momo_awaiting_confirmation",
            )
        await self._paystack.verify_transaction(reference)
        return await self._fulfill_paid_order(order)

    async def submit_momo_transaction(
        self, customer_id: UUID, order_id: UUID, transaction_id: str
    ) -> OrderResponse:
        order = await self.get_order(customer_id, order_id)
        if order.payment_status == "paid":
            return OrderResponse.model_validate(order)
        txn = (transaction_id or "").strip()
        if len(txn) < 6:
            raise ValidationError("Enter the Mobile Money transaction ID from your payment receipt.")
        taken = await self._session.execute(
            select(Order.id).where(
                Order.momo_transaction_id == txn[:80],
                Order.id != order.id,
            )
        )
        if taken.scalar_one_or_none() is not None:
            raise ConflictError(
                "That Mobile Money transaction ID is already on another invoice.",
                code="momo_id_reused",
            )
        order.momo_transaction_id = txn[:80]
        order.payment_status = "submitted"
        order.payment_method = "momo"
        customer = await self._session.get(Customer, order.customer_id)
        if customer:
            title, text, html = email_templates.payment_received(
                name=customer.full_name, invoice=order.invoice_number or txn
            )
            await NotificationService(self._session, self._settings).notify(
                customer.id,
                title=title,
                body=text,
                kind="payment",
                html_body=html,
                email_subject=f"IFNOTUS — {title}",
                sms_body=(
                    f"We have your MoMo ID for invoice {order.invoice_number or txn}. "
                    "We'll confirm and activate hosting."
                ),
            )
        await self._session.flush()
        return OrderResponse.model_validate(order)

    async def confirm_payment(
        self,
        order_id: UUID,
        *,
        actor_id: UUID | None = None,
        amount_received: Decimal | None = None,
        notes: str | None = None,
    ) -> OrderResponse:
        order = await self._session.get(Order, order_id)
        if order is None:
            raise NotFoundError("Order not found.")
        if amount_received is not None:
            expected = Decimal(str(order.total_price))
            got = Decimal(str(amount_received))
            if abs(expected - got) > Decimal("0.01"):
                raise ValidationError(
                    f"Amount received ({got}) does not match invoice {expected}. Do not activate.",
                    code="momo_amount_mismatch",
                )
            order.payment_amount_received = got
        if notes:
            order.payment_notes = notes[:2000]
        order.payment_confirmed_at = datetime.now(UTC)
        order.payment_confirmed_by = actor_id
        if order.payment_status == "paid":
            if order.provisioning_status in {"pending", "queued", "failed"} and (
                order.order_kind or "hosting"
            ) == "hosting":
                if order.provisioning_status == "failed":
                    return await self.retry_provision(order_id)
                order.provisioning_status = "queued"
                await self._activate_hosting(order)
                await self._session.flush()
            return OrderResponse.model_validate(order)
        return await self._fulfill_paid_order(order)

    async def reject_payment(
        self,
        order_id: UUID,
        *,
        actor_id: UUID | None = None,
        notes: str | None = None,
    ) -> OrderResponse:
        order = await self._session.get(Order, order_id)
        if order is None:
            raise NotFoundError("Order not found.")
        if order.payment_status == "paid":
            raise ValidationError("Paid orders cannot be rejected. Suspend the environment instead.")
        order.payment_status = "failed"
        if notes:
            order.payment_notes = (notes or "")[:2000]
        order.payment_confirmed_at = datetime.now(UTC)
        order.payment_confirmed_by = actor_id
        self._session.add(
            PlatformAuditLog(
                customer_id=order.customer_id,
                actor_id=actor_id,
                action="order.payment_rejected",
                target_type="order",
                target_id=str(order.id),
                result="success",
                metadata_json={"notes": notes or ""},
            )
        )
        await self._session.flush()
        return OrderResponse.model_validate(order)

    async def retry_provision(self, order_id: UUID) -> OrderResponse:
        order = await self._session.get(Order, order_id)
        if order is None:
            raise NotFoundError("Order not found.")
        if order.payment_status != "paid":
            raise ValidationError("Confirm payment before retrying hosting setup.")
        if order.provisioning_status == "active":
            return OrderResponse.model_validate(order)
        existing = await self._session.execute(
            select(Subscription).where(Subscription.order_id == order.id)
        )
        sub = existing.scalar_one_or_none()
        if sub is None:
            await self._activate_hosting(order)
            await self._session.flush()
            return OrderResponse.model_validate(order)

        # PHASE 22 — reuse an in-flight provision job instead of stacking duplicates.
        inflight = await self._session.execute(
            select(PlatformJob).where(
                PlatformJob.job_type == "provision_environment",
                PlatformJob.customer_id == order.customer_id,
                PlatformJob.status.in_(("pending", "running", "queued")),
            )
        )
        for candidate in inflight.scalars().all():
            payload = candidate.payload or {}
            if str(payload.get("order_id")) == str(order.id):
                order.provisioning_status = "queued"
                await self._enqueue_or_run(candidate)
                await self._session.flush()
                return OrderResponse.model_validate(order)

        job = PlatformJob(
            job_type="provision_environment",
            customer_id=order.customer_id,
            status="pending",
            payload={
                "order_id": str(order.id),
                "subscription_id": str(sub.id),
                "plan_id": str(order.plan_id),
                "domain_name": order.domain_name,
                "retry": True,
            },
        )
        self._session.add(job)
        await self._session.flush()
        order.provisioning_status = "queued"
        await self._enqueue_or_run(job)
        await self._session.flush()
        return OrderResponse.model_validate(order)

    async def provision_for_customer(
        self,
        *,
        customer: Customer,
        plan_id: UUID,
        domain_name: str | None = None,
        domain_extension: str | None = None,
    ) -> OrderResponse:
        """Super-admin: create a paid order and activate hosting immediately."""
        body = CreateOrderRequest(
            plan_id=plan_id,
            domain_name=domain_name,
            domain_extension=domain_extension,
            include_domain=bool(domain_name),
        )
        created = await self.create_order(customer, body, notify=False)
        order = await self.get_order(customer.id, created["order"].id)
        order.payment_method = "staff"
        order.payment_status = "paid"
        order.paid_at = datetime.now(UTC)
        return await self._fulfill_paid_order(order)

    async def _fulfill_paid_order(self, order: Order) -> OrderResponse:
        order.payment_status = "paid"
        order.paid_at = order.paid_at or datetime.now(UTC)
        kind = (order.order_kind or "hosting").lower()
        if kind == "renewal":
            await self._activate_renewal(order)
        elif kind == "upgrade":
            await self._activate_upgrade(order)
        elif kind == "credits":
            await self._activate_credits(order)
        else:
            order.provisioning_status = "queued"
            await self._activate_hosting(order)
            if (order.payment_method or "momo") != "staff":
                customer = await self._session.get(Customer, order.customer_id)
                if customer:
                    title, text, html = email_templates.payment_confirmed(
                        name=customer.full_name, invoice=order.invoice_number or str(order.id)[:8]
                    )
                    await NotificationService(self._session, self._settings).notify(
                        customer.id,
                        title=title,
                        body=text,
                        kind="payment",
                        html_body=html,
                        email_subject=f"IFNOTUS — {title}",
                        sms_body=(
                            f"Payment confirmed for invoice {order.invoice_number or str(order.id)[:8]}. "
                            "We're activating your hosting."
                        ),
                    )
        await self._session.flush()
        return OrderResponse.model_validate(order)

    async def create_renewal_payment(self, customer: Customer, subscription_id: UUID) -> dict:
        from app.services.platform.billing import SubscriptionBillingService

        billing = SubscriptionBillingService(self._settings, self._session)
        sub = await billing.get_owned(customer.id, subscription_id)
        plan = await self._get_plan(sub.plan_id)
        amount = plan.price_monthly
        order = Order(
            customer_id=customer.id,
            plan_id=plan.id,
            domain_name=None,
            domain_extension=None,
            plan_price=amount,
            domain_price=Decimal("0"),
            total_price=amount,
            currency=plan.currency or "GHS",
            payment_status="pending",
            provisioning_status="n/a",
            order_kind="renewal",
            meta_json={"subscription_id": str(sub.id), "days": 30},
            expires_at=datetime.now(UTC) + timedelta(days=7),
        )
        self._session.add(order)
        await self._session.flush()
        return await self._init_payment(customer, order, amount, purpose="renewal")

    async def create_upgrade_payment(self, customer: Customer, subscription_id: UUID, plan_id: UUID) -> dict:
        from app.services.platform.billing import SubscriptionBillingService

        billing = SubscriptionBillingService(self._settings, self._session)
        sub = await billing.get_owned(customer.id, subscription_id)
        old_plan = await self._get_plan(sub.plan_id)
        new_plan = await self._get_plan(plan_id)
        if new_plan.id == old_plan.id:
            raise AppException("Already on this plan.")
        # Charge full new monthly for upgrades; free path for downgrades handled by caller
        amount = new_plan.price_monthly
        if new_plan.price_monthly <= old_plan.price_monthly:
            # Downgrade — apply immediately without payment
            await billing.change_plan(customer.id, subscription_id, plan_id)
            return {
                "order": None,
                "authorization_url": None,
                "reference": "downgrade-applied",
                "demo": True,
                "paystack_public_key": self._paystack.public_key,
                "applied": True,
                "amount": Decimal("0"),
            }
        await self._resources.pick_node_for_plan(new_plan)
        order = Order(
            customer_id=customer.id,
            plan_id=new_plan.id,
            plan_price=amount,
            domain_price=Decimal("0"),
            total_price=amount,
            currency=new_plan.currency or "GHS",
            payment_status="pending",
            provisioning_status="n/a",
            order_kind="upgrade",
            meta_json={"subscription_id": str(sub.id), "from_plan_id": str(old_plan.id)},
            expires_at=datetime.now(UTC) + timedelta(days=7),
        )
        self._session.add(order)
        await self._session.flush()
        return await self._init_payment(customer, order, amount, purpose="upgrade")

    async def create_credit_topup(self, customer: Customer, credits: int) -> dict:
        # GHS 1 per credit
        amount = Decimal(credits)
        # Need a plan_id FK — use any active plan as placeholder
        result = await self._session.execute(
            select(HostingPlan).where(HostingPlan.is_active.is_(True)).order_by(HostingPlan.sort_order).limit(1)
        )
        plan = result.scalar_one_or_none()
        if plan is None:
            raise AppException("No hosting plans configured.")
        order = Order(
            customer_id=customer.id,
            plan_id=plan.id,
            plan_price=amount,
            domain_price=Decimal("0"),
            total_price=amount,
            currency="GHS",
            payment_status="pending",
            provisioning_status="n/a",
            order_kind="credits",
            meta_json={"credits": credits},
            expires_at=datetime.now(UTC) + timedelta(days=7),
        )
        self._session.add(order)
        await self._session.flush()
        return await self._init_payment(customer, order, amount, purpose="credits")

    async def _init_payment(self, customer: Customer, order: Order, amount: Decimal, *, purpose: str) -> dict:
        reference = self._paystack.new_reference(prefix=f"IFN{purpose[:3].upper()}")
        order.paystack_reference = reference
        order.payment_method = "momo"
        if not order.invoice_number:
            order.invoice_number = await self._new_invoice()
        plan = await self._get_plan(order.plan_id)
        await self._notify_invoice(customer, order, plan.name)
        await self._session.flush()
        return {
            "order": OrderResponse.model_validate(order),
            "authorization_url": None,
            "reference": reference,
            "demo": False,
            "paystack_public_key": None,
            "amount": amount,
            "applied": False,
            "payment_method": "momo",
            "invoice_number": order.invoice_number,
            "momo": self._momo_details(),
        }

    async def _activate_renewal(self, order: Order) -> None:
        from app.services.platform.billing import SubscriptionBillingService
        from uuid import UUID as _UUID

        meta = order.meta_json or {}
        sub_id = _UUID(str(meta["subscription_id"]))
        days = int(meta.get("days") or 30)
        await SubscriptionBillingService(self._settings, self._session).renew(
            order.customer_id, sub_id, days=days
        )
        order.provisioning_status = "active"

    async def _activate_upgrade(self, order: Order) -> None:
        from app.services.platform.billing import SubscriptionBillingService
        from uuid import UUID as _UUID

        meta = order.meta_json or {}
        sub_id = _UUID(str(meta["subscription_id"]))
        await SubscriptionBillingService(self._settings, self._session).change_plan(
            order.customer_id, sub_id, order.plan_id
        )
        order.provisioning_status = "active"
        await NotificationService(self._session, self._settings).notify(
            order.customer_id,
            title="Upgrade payment confirmed",
            body="Your plan was upgraded after payment.",
            kind="payment",
        )

    async def _activate_credits(self, order: Order) -> None:
        meta = order.meta_json or {}
        credits = int(meta.get("credits") or 0)
        result = await self._session.execute(
            select(AiCreditAccount).where(AiCreditAccount.customer_id == order.customer_id)
        )
        account = result.scalar_one_or_none()
        if account is None:
            account = AiCreditAccount(customer_id=order.customer_id)
            self._session.add(account)
            await self._session.flush()
        account.credits_remaining += credits
        account.total_allocated += credits
        order.provisioning_status = "active"
        await NotificationService(self._session, self._settings).notify(
            order.customer_id,
            title="AI credits added",
            body=f"{credits} AI Engineer credits were added to your account.",
            kind="credits",
            deliver=False,
        )

    async def _activate_hosting(self, order: Order) -> None:
        plan = await self._get_plan(order.plan_id)
        sub = Subscription(
            customer_id=order.customer_id,
            order_id=order.id,
            plan_id=plan.id,
            status="active",
            cpu_allocated=plan.cpu_cores,
            ram_allocated=plan.ram_gb,
            storage_allocated=plan.storage_gb,
            started_at=datetime.now(UTC),
            expires_at=datetime.now(UTC) + timedelta(days=30),
            auto_renew=True,
        )
        self._session.add(sub)
        await self._session.flush()

        from app.services.platform.entitlements import snapshot_for_subscription

        await snapshot_for_subscription(self._session, sub, plan)

        credits = await self._session.execute(
            select(AiCreditAccount).where(AiCreditAccount.customer_id == order.customer_id)
        )
        account = credits.scalar_one_or_none()
        if account is None:
            account = AiCreditAccount(customer_id=order.customer_id)
            self._session.add(account)
            await self._session.flush()
        account.credits_remaining += plan.ai_credits
        account.total_allocated += plan.ai_credits

        if order.domain_name:
            from app.services.platform.student_hostname import is_student_hostname

            sld = order.domain_name
            ext = order.domain_extension or ""
            if "." in sld:
                host, rest = sld.split(".", 1)
                sld = host
                if not ext:
                    ext = f".{rest}"
            full_name = (
                order.domain_name
                if "." in (order.domain_name or "")
                else f"{sld}{(ext or '.online')}"
            )
            meta = order.meta_json or {}
            kind = str(meta.get("domain_kind") or "register")
            should_register = kind == "register" and bool(meta.get("include_domain", True)) and not is_student_hostname(
                full_name
            )
            domain_row = CustomerDomain(
                customer_id=order.customer_id,
                domain_name=full_name,
                registrar="ifnotus" if is_student_hostname(full_name) else ("queued" if should_register else "customer"),
                registration_date=datetime.now(UTC),
                expiry_date=datetime.now(UTC) + timedelta(days=365),
                auto_renew=True,
                dns_records=[],
                status="pending_verification",
                ssl_status="pending",
            )
            self._session.add(domain_row)
            await self._session.flush()
            if should_register:
                await self._queue_domain_register(
                    customer_domain_id=domain_row.id,
                    customer_id=order.customer_id,
                    sld=sld,
                    extension=ext or ".online",
                    order_id=order.id,
                )

        job = PlatformJob(
            job_type="provision_environment",
            customer_id=order.customer_id,
            status="pending",
            payload={
                "order_id": str(order.id),
                "subscription_id": str(sub.id),
                "plan_id": str(plan.id),
                "domain_name": order.domain_name,
            },
        )
        self._session.add(job)
        self._session.add(
            PlatformAuditLog(
                customer_id=order.customer_id,
                action="order.paid",
                target_type="order",
                target_id=str(order.id),
                result="success",
                metadata_json={"reference": order.paystack_reference},
            )
        )
        await self._session.flush()
        await self._enqueue_or_run(job)

    async def _queue_domain_register(
        self,
        *,
        customer_domain_id,
        customer_id,
        sld: str,
        extension: str,
        order_id,
    ) -> None:
        from app.services.platform.enqueue import enqueue_task

        job = PlatformJob(
            job_type="register_domain",
            customer_id=customer_id,
            status="pending",
            payload={
                "customer_domain_id": str(customer_domain_id),
                "sld": sld,
                "extension": extension,
                "order_id": str(order_id),
            },
        )
        self._session.add(job)
        await self._session.flush()
        task_id = await enqueue_task(
            self._settings,
            "register_domain",
            {
                "job_id": str(job.id),
                "customer_domain_id": str(customer_domain_id),
                "sld": sld,
                "extension": extension,
                "order_id": str(order_id),
            },
        )
        if task_id is None:
            # Inline fallback when Redis/worker unavailable
            from app.services.platform.registrar import DomainRegistrar

            try:
                domain = await self._session.get(CustomerDomain, customer_domain_id)
                contact = None
                if domain is not None:
                    customer = await self._session.get(Customer, domain.customer_id)
                    if customer:
                        parts = (customer.full_name or "IFNOTUS Hostmaster").strip().split(None, 1)
                        contact = {
                            "first_name": parts[0],
                            "last_name": parts[1] if len(parts) > 1 else "Hostmaster",
                            "email": customer.email,
                            "phone": customer.phone or "",
                        }
                result = await DomainRegistrar(self._settings).register(sld, extension, contact=contact)
                if domain is not None:
                    if result.get("registered"):
                        domain.registrar = str(result.get("provider") or "namecheap")
                    else:
                        domain.registrar = str(result.get("provider") or "pending")
                    if result.get("nameservers"):
                        domain.dns_records = [{"ns": result.get("nameservers")}]
                if result.get("registered") and result.get("domain"):
                    try:
                        from app.services.platform.authoritative_dns import AuthoritativeDnsService

                        AuthoritativeDnsService(self._settings).ensure_zone(str(result["domain"]))
                    except Exception as exc:  # noqa: BLE001
                        logger.warning("zone_after_register_failed", error=str(exc))
                job.status = "success" if result.get("registered") else "failed"
                job.result = result
                job.completed_at = datetime.now(UTC)
                if not result.get("registered"):
                    job.error_info = str(result.get("message") or "Domain not registered")
            except Exception as exc:  # noqa: BLE001
                job.status = "failed"
                job.error_info = str(exc)[:2000]
                job.completed_at = datetime.now(UTC)

    async def list_orders(self, customer_id: UUID) -> list[Order]:
        """Customer-facing invoices — hide cancelled / disputed provisioning noise."""
        result = await self._session.execute(
            select(Order)
            .where(Order.customer_id == customer_id)
            .order_by(Order.created_at.desc())
        )
        rows = list(result.scalars().all())
        visible: list[Order] = []
        for order in rows:
            status = (order.provisioning_status or "").lower()
            if status in {"cancelled", "canceled"}:
                continue
            meta = order.meta_json if isinstance(order.meta_json, dict) else {}
            if meta.get("hidden_from_customer") or meta.get("cancelled_reason"):
                continue
            visible.append(order)
        return visible

    async def get_order(self, customer_id: UUID, order_id: UUID) -> Order:
        result = await self._session.execute(
            select(Order).where(Order.id == order_id, Order.customer_id == customer_id)
        )
        order = result.scalar_one_or_none()
        if order is None:
            raise NotFoundError("Order not found.")
        return order

    async def _enqueue_or_run(self, job: PlatformJob) -> None:
        from app.services.platform.enqueue import enqueue_task
        from app.services.platform.provisioning import ProvisioningEngine

        task_id = await enqueue_task(
            self._settings,
            "provision_environment",
            {"job_id": str(job.id), **(job.payload or {})},
        )
        if task_id is not None:
            return
        # Fallback: run inline when Redis/worker is unavailable
        engine = ProvisioningEngine(self._settings, self._session)
        try:
            await engine.run_job(job)
        except Exception as exc:  # noqa: BLE001
            job.status = "failed"
            job.error_info = str(exc)
            await self._session.flush()
            raise AppException(f"Provisioning failed: {exc}") from exc

    async def _get_plan(self, plan_id: UUID) -> HostingPlan:
        result = await self._session.execute(select(HostingPlan).where(HostingPlan.id == plan_id))
        plan = result.scalar_one_or_none()
        if plan is None or not plan.is_active:
            raise NotFoundError("Hosting plan not found.")
        from app.services.platform.plan_matrix import sellable_on_shared_node

        if not sellable_on_shared_node(plan):
            raise AppException(
                "Cloud VPS/VDS is coming soon and cannot be purchased on this shared "
                "hosting node. Choose a managed hosting pack instead.",
                code="plan_not_sellable",
            )
        return plan

    async def _get_by_reference(self, reference: str) -> Order:
        result = await self._session.execute(select(Order).where(Order.paystack_reference == reference))
        order = result.scalar_one_or_none()
        if order is None:
            raise NotFoundError("Order not found for this payment reference.")
        return order

    async def invoice_view(self, customer_id: UUID, order_id: UUID) -> InvoiceViewResponse:
        order = await self.get_order(customer_id, order_id)
        plan = await self._session.get(HostingPlan, order.plan_id)
        momo = self._momo_details()
        return InvoiceViewResponse(
            order=OrderResponse.model_validate(order),
            plan_name=plan.name if plan else None,
            momo=momo,
            payment_methods=[
                {
                    "id": "momo",
                    "title": "Mobile Money (Direct Transfer)",
                    "description": "Pay the IFNOTUS merchant number, then share the transaction ID.",
                }
            ],
            support_hours=self._settings.support_hours,
            support_whatsapp=self._settings.support_whatsapp,
            support_email=self._settings.support_email,
        )

    def _momo_details(self) -> dict:
        resolved = IntegrationsSettingsStore(self._settings).resolved()
        return {
            "network": (getattr(resolved, "momo_network", None) or "MTN").strip() or "MTN",
            "number": (getattr(resolved, "momo_number", None) or "0257940791").strip(),
            "account_name": (getattr(resolved, "momo_account_name", None) or "Emmanuel Kwofie").strip(),
            "merchant": True,
        }

    async def _new_invoice(self) -> str:
        """Short MoMo-friendly reference (e.g. IF7K2A)."""
        for _ in range(24):
            code = f"IF{secrets.token_hex(2).upper()}"
            row = await self._session.execute(select(Order.id).where(Order.invoice_number == code).limit(1))
            if row.scalar_one_or_none() is None:
                return code
        return f"IF{secrets.token_hex(3).upper()}"

    async def _notify_invoice(self, customer: Customer, order: Order, plan_name: str) -> None:
        momo = self._momo_details()
        title, text, html = email_templates.invoice_placed(
            name=customer.full_name,
            invoice=order.invoice_number or str(order.id)[:8],
            amount=f"{order.total_price:.2f}",
            currency=order.currency,
            plan=plan_name,
            momo_network=momo["network"],
            momo_number=momo["number"],
            momo_name=momo["account_name"],
            invoice_url=f"https://ifnotus.space/account/invoice/{order.id}",
        )
        await NotificationService(self._session, self._settings).notify(
            customer.id,
            title=title,
            body=text,
            kind="payment",
            html_body=html,
            email_subject=f"IFNOTUS — {title}",
            sms_body=(
                f"Invoice {order.invoice_number}: {order.currency} {order.total_price:.2f}. "
                f"Pay merchant {momo['network']} {momo['number']} ({momo['account_name']}). "
                "Use the invoice number as reference, then share the transaction ID."
            ),
        )
