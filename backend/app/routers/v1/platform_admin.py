"""Staff product console APIs — customers, plans, orders, env lifecycle."""

from __future__ import annotations

from uuid import UUID

from datetime import date

from fastapi import APIRouter, Depends, Query

from app.api.deps import CurrentUser, DbSession, RequirePermission, SettingsDep
from app.core.permissions import Permission
from app.models.platform import Customer
from app.schemas.common import MessageResponse
from app.schemas.integrations import IntegrationsStatusResponse, IntegrationsUpdateRequest
from app.schemas.platform import (
    CapacityNodeResponse,
    CustomerResponse,
    HostingPlanSchema,
    InvoiceViewResponse,
    OrderResponse,
    StaffCapacityDashboardResponse,
    BillingTermsAdminResponse,
    BillingTermsAdminUpdateRequest,
)
from app.schemas.platform_admin import (
    HostingPlanPatchRequest,
    HostingPlanUpsertRequest,
    SiteThemeStatusResponse,
    SiteThemeUpdateRequest,
    StaffAccountingSummaryResponse,
    StaffAccountingLedgerItem,
    StaffConfirmPaymentRequest,
    StaffUpdatePaymentStatusRequest,
    StaffSendCustomMessageRequest,
    StaffCustomerDetailResponse,
    StaffCustomerListItem,
    StaffCustomerUpdateRequest,
    StaffCustomerCreateRequest,
    StaffDeleteCustomerRequest,
    StaffEnvironmentItem,
    StaffGrantCreditsRequest,
    StaffGrantCreditsResponse,
    StaffOpsInboxResponse,
    StaffOrderItem,
    StaffProvisionHostingRequest,
    StaffUpdateSubdomainRequest,
    StaffActivateOrderHostingRequest,
    StaffUserCreateRequest,
    StaffUserItem,
    StaffUserUpdateRequest,
)
from app.services.platform.integrations_store import IntegrationsSettingsStore
from app.services.platform.site_theme_store import SiteThemeStore
from app.services.platform.staff import StaffPlatformService

router = APIRouter()


@router.get(
    "/customers",
    response_model=list[StaffCustomerListItem],
    dependencies=[Depends(RequirePermission(Permission.PLATFORM_READ))],
)
async def list_customers(
    session: DbSession,
    settings: SettingsDep,
    q: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
) -> list[StaffCustomerListItem]:
    rows = await StaffPlatformService(settings, session).list_customers(q=q, limit=limit)
    return [StaffCustomerListItem.model_validate(r) for r in rows]


@router.post(
    "/customers",
    response_model=CustomerResponse,
    dependencies=[Depends(RequirePermission(Permission.PLATFORM_OPS))],
)
async def create_customer(
    body: StaffCustomerCreateRequest,
    session: DbSession,
    settings: SettingsDep,
    user: CurrentUser,
) -> CustomerResponse:
    """Create customer account directly by staff and optionally provision hosting."""
    from sqlalchemy import func, select
    from app.core.exceptions import ConflictError
    from app.services.platform.customers import CustomerService
    from app.services.platform.orders import OrderService
    from app.schemas.platform_admin import StaffProvisionHostingRequest

    email = body.email.strip().lower()
    existing = (
        await session.execute(
            select(Customer).where(func.lower(Customer.email) == email)
        )
    ).scalar_one_or_none()
    if existing is not None:
        raise ConflictError("A customer with this email already exists.")

    svc = CustomerService(settings, session)
    customer = await svc.register_email(
        email=email,
        password=body.password or "WelcomePass2026!",
        full_name=body.full_name,
        company=body.company,
        phone=body.phone,
    )
    if body.phone:
        customer.phone = body.phone
        customer.phone_verified = True
    customer.email_verified = True
    await session.commit()
    await session.refresh(customer)

    if body.plan_id:
        try:
            plan_uuid = UUID(body.plan_id) if isinstance(body.plan_id, str) else body.plan_id
            await OrderService(settings, session).provision_for_customer(
                customer.id,
                StaffProvisionHostingRequest(
                    plan_id=plan_uuid,
                    domain=body.domain or None,
                ),
                actor_id=user.id,
            )
            await session.commit()
        except Exception:  # noqa: BLE001
            pass

    return CustomerService.to_response(customer)


@router.get(
    "/customers/{customer_id}",
    response_model=StaffCustomerDetailResponse,
    dependencies=[Depends(RequirePermission(Permission.PLATFORM_READ))],
)
async def get_customer(
    customer_id: UUID,
    session: DbSession,
    settings: SettingsDep,
) -> StaffCustomerDetailResponse:
    data = await StaffPlatformService(settings, session).get_customer(customer_id)
    return StaffCustomerDetailResponse(
        customer=CustomerResponse.model_validate(data["customer"]),
        credits_remaining=data["credits_remaining"],
        subscriptions=data["subscriptions"],
        environments=data["environments"],
        orders=data["orders"],
        audit=data.get("audit") or [],
    )


@router.patch(
    "/customers/{customer_id}",
    response_model=CustomerResponse,
    dependencies=[Depends(RequirePermission(Permission.PLATFORM_OPS))],
)
async def update_customer(
    customer_id: UUID,
    body: StaffCustomerUpdateRequest,
    session: DbSession,
    settings: SettingsDep,
    user: CurrentUser,
) -> CustomerResponse:
    """Update tenant phone, email, and profile from the staff console."""
    customer = await StaffPlatformService(settings, session).update_customer(
        customer_id,
        body,
        actor_id=user.id,
    )
    await session.commit()
    from app.services.platform.customers import CustomerService

    return CustomerService.to_response(customer)


@router.post(
    "/customers/{customer_id}/delete",
    response_model=MessageResponse,
    dependencies=[Depends(RequirePermission(Permission.PLATFORM_OPS))],
)
async def delete_customer(
    customer_id: UUID,
    body: StaffDeleteCustomerRequest,
    session: DbSession,
    settings: SettingsDep,
    user: CurrentUser,
) -> MessageResponse:
    """Super admin: terminate hosting and permanently remove the customer account."""
    result = await StaffPlatformService(settings, session).delete_customer(
        customer_id,
        confirm_email=body.confirm_email,
        actor_id=user.id,
    )
    return MessageResponse(message=result["message"])


@router.post(
    "/customers/{customer_id}/credits/grant",
    response_model=StaffGrantCreditsResponse,
    dependencies=[Depends(RequirePermission(Permission.PLATFORM_OPS))],
)
async def grant_customer_credits(
    customer_id: UUID,
    body: StaffGrantCreditsRequest,
    session: DbSession,
    settings: SettingsDep,
    user: CurrentUser,
) -> StaffGrantCreditsResponse:
    """Super admin / hosting operator: manually add AI credits for a client."""
    customer = await session.get(Customer, customer_id)
    if customer is None:
        from app.core.exceptions import NotFoundError

        raise NotFoundError("Customer not found.")
    from app.services.platform.credits import AiCreditService, tokens_from_credits

    account = await AiCreditService(session).grant_credits(
        customer_id,
        body.credits,
        actor_user_id=user.id,
        note=body.note,
    )
    return StaffGrantCreditsResponse(
        customer_id=customer_id,
        credits_granted=body.credits,
        credits_remaining=account.credits_remaining,
        total_allocated=account.total_allocated,
        tokens_remaining=tokens_from_credits(account.credits_remaining),
        message=f"Added {body.credits} AI credit(s). Balance is now {account.credits_remaining}.",
    )


def _can_view_billing(user: CurrentUser) -> bool:
    if getattr(user, "is_superuser", False):
        return True
    roles = set(getattr(user, "roles", []) or [])
    priv = getattr(user, "privilege_viewing_as", None)
    if priv:
        roles.add(priv)
    perms = set(getattr(user, "permissions", []) or [])
    if Permission.BILLING_VIEW in perms or Permission.BILLING_MANAGE in perms:
        return True
    return bool(roles & {"platform_owner", "platform_admin", "billing_agent", "superadmin", "admin"})


@router.get(
    "/orders",
    response_model=list[StaffOrderItem],
    dependencies=[Depends(RequirePermission(Permission.PLATFORM_READ))],
)
async def list_orders(
    session: DbSession,
    settings: SettingsDep,
    user: CurrentUser,
    payment_status: str | None = Query(default=None),
    provisioning_status: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
) -> list[StaffOrderItem]:
    can_view = _can_view_billing(user)
    rows = await StaffPlatformService(settings, session).list_orders(
        payment_status=payment_status,
        provisioning_status=provisioning_status,
        limit=limit,
        mask_financials=not can_view,
    )
    return [StaffOrderItem.model_validate(r) for r in rows]


@router.get(
    "/ops-inbox",
    response_model=StaffOpsInboxResponse,
    dependencies=[Depends(RequirePermission(Permission.PLATFORM_READ))],
)
async def ops_inbox(
    session: DbSession,
    settings: SettingsDep,
    user: CurrentUser,
) -> StaffOpsInboxResponse:
    """Bell + Orders badge: new MoMo submissions and recently paid hosting invoices."""
    can_view = _can_view_billing(user)
    data = await StaffPlatformService(settings, session).ops_inbox(mask_financials=not can_view)
    return StaffOpsInboxResponse.model_validate(data)


@router.get(
    "/accounting/summary",
    response_model=StaffAccountingSummaryResponse,
    dependencies=[Depends(RequirePermission(Permission.BILLING_VIEW))],
)
async def accounting_summary(
    session: DbSession,
    settings: SettingsDep,
    date_from: date | None = Query(default=None),
    date_to: date | None = Query(default=None),
) -> StaffAccountingSummaryResponse:
    from app.services.platform.accounting import AccountingService

    data = await AccountingService(settings, session).summary(
        date_from=date_from, date_to=date_to
    )
    return StaffAccountingSummaryResponse.model_validate(data)


@router.get(
    "/accounting/ledger",
    response_model=list[StaffAccountingLedgerItem],
    dependencies=[Depends(RequirePermission(Permission.BILLING_VIEW))],
)
async def accounting_ledger(
    session: DbSession,
    settings: SettingsDep,
    date_from: date | None = Query(default=None),
    date_to: date | None = Query(default=None),
    payment_status: str | None = Query(default=None),
    cash_only: bool = Query(default=False),
    limit: int = Query(default=100, ge=1, le=500),
) -> list[StaffAccountingLedgerItem]:
    from app.services.platform.accounting import AccountingService

    rows = await AccountingService(settings, session).ledger(
        date_from=date_from,
        date_to=date_to,
        payment_status=payment_status,
        cash_only=cash_only,
        limit=limit,
    )
    return [StaffAccountingLedgerItem.model_validate(r) for r in rows]


@router.get(
    "/orders/{order_id}/invoice",
    response_model=InvoiceViewResponse,
    dependencies=[Depends(RequirePermission(Permission.BILLING_VIEW))],
)
async def get_order_invoice(
    order_id: UUID,
    session: DbSession,
    settings: SettingsDep,
) -> InvoiceViewResponse:
    """Staff receipt / proforma for paid or pending orders."""
    from app.services.platform.orders import OrderService

    return await OrderService(settings, session).staff_invoice_view(order_id)


@router.post(
    "/orders/{order_id}/confirm-payment",
    response_model=OrderResponse,
    dependencies=[Depends(RequirePermission(Permission.BILLING_MANAGE))],
)
async def confirm_order_payment(
    order_id: UUID,
    session: DbSession,
    settings: SettingsDep,
    user: CurrentUser,
    body: StaffConfirmPaymentRequest | None = None,
) -> OrderResponse:
    from app.services.platform.orders import OrderService

    payload = body or StaffConfirmPaymentRequest()
    return await OrderService(settings, session).confirm_payment(
        order_id,
        actor_id=user.id,
        amount_received=payload.amount_received,
        notes=payload.notes,
        domain_name=payload.domain_name,
        payment_method=payload.payment_method,
    )



@router.post(
    "/orders/{order_id}/activate-hosting",
    response_model=OrderResponse,
    dependencies=[Depends(RequirePermission(Permission.PLATFORM_OPS))],
)
async def activate_order_hosting(
    order_id: UUID,
    session: DbSession,
    settings: SettingsDep,
    user: CurrentUser,
    body: StaffActivateOrderHostingRequest | None = None,
) -> OrderResponse:
    """Hosting operator: activate and provision server infrastructure for paid order."""
    from app.services.platform.orders import OrderService

    custom_domain = body.domain if body else None
    return await OrderService(settings, session).activate_hosting_by_operator(
        order_id, actor_id=user.id, domain=custom_domain
    )


@router.patch(
    "/orders/{order_id}/domain",
    response_model=OrderResponse,
    dependencies=[Depends(RequirePermission(Permission.PLATFORM_OPS))],
)
async def update_order_domain(
    order_id: UUID,
    body: StaffUpdateSubdomainRequest,
    session: DbSession,
    settings: SettingsDep,
    user: CurrentUser,
) -> OrderResponse:
    """Hosting operator: assign or customize subdomain / domain for an order."""
    from app.services.platform.orders import OrderService

    return await OrderService(settings, session).update_order_domain(
        order_id, body.domain, actor_id=user.id
    )


@router.post(
    "/orders/{order_id}/retry-provision",
    response_model=OrderResponse,
    dependencies=[Depends(RequirePermission(Permission.PLATFORM_OPS))],
)
async def retry_order_provision(
    order_id: UUID,
    session: DbSession,
    settings: SettingsDep,
) -> OrderResponse:
    from app.services.platform.orders import OrderService

    return await OrderService(settings, session).retry_provision(order_id)


@router.post(
    "/orders/{order_id}/reject-payment",
    response_model=OrderResponse,
    dependencies=[Depends(RequirePermission(Permission.BILLING_MANAGE))],
)
async def reject_order_payment(
    order_id: UUID,
    session: DbSession,
    settings: SettingsDep,
    user: CurrentUser,
    body: StaffConfirmPaymentRequest | None = None,
) -> OrderResponse:
    from app.services.platform.orders import OrderService

    payload = body or StaffConfirmPaymentRequest()
    return await OrderService(settings, session).reject_payment(
        order_id,
        actor_id=user.id,
        notes=payload.notes,
    )


@router.patch(
    "/orders/{order_id}/payment-status",
    response_model=OrderResponse,
    dependencies=[Depends(RequirePermission(Permission.BILLING_MANAGE))],
)
async def update_order_payment_status(
    order_id: UUID,
    body: StaffUpdatePaymentStatusRequest,
    session: DbSession,
    settings: SettingsDep,
    user: CurrentUser,
) -> OrderResponse:
    """Allow billing agents to change payment method (e.g. complimentary vs cash) and payment status."""
    from datetime import datetime, UTC
    from decimal import Decimal
    from app.core.exceptions import NotFoundError
    from app.models.platform import Order, PlatformAuditLog
    from app.services.platform.orders import OrderService

    order = await session.get(Order, order_id)
    if order is None:
        raise NotFoundError("Order not found.")

    old_method = order.payment_method
    old_status = order.payment_status

    if body.payment_method is not None:
        new_m = body.payment_method.strip().lower()
        order.payment_method = new_m
        if new_m in {"complimentary", "free", "staff", "comp"}:
            order.payment_amount_received = Decimal("0")
            order.payment_status = "paid"
            order.paid_at = order.paid_at or datetime.now(UTC)
            order.payment_confirmed_at = datetime.now(UTC)
            order.payment_confirmed_by = user.id
            if not order.payment_notes:
                order.payment_notes = "Complimentary Free Grant (0.00 GHS)"
            if order.provisioning_status == "pending":
                order.provisioning_status = "ready_for_activation"
        elif body.amount_received is not None:
            order.payment_amount_received = Decimal(str(body.amount_received))

    if body.payment_status is not None:
        new_s = body.payment_status.strip().lower()
        order.payment_status = new_s
        if new_s == "paid":
            order.paid_at = order.paid_at or datetime.now(UTC)
            order.payment_confirmed_at = datetime.now(UTC)
            order.payment_confirmed_by = user.id

    if body.notes is not None:
        order.payment_notes = body.notes.strip()[:2000]

    # Always track the specific staff/owner ID on the order
    order.payment_confirmed_by = user.id

    meta = dict(order.meta_json or {})
    actions = list(meta.get("audit_history") or [])
    actions.append({
        "action": "payment_status_updated",
        "actor_id": str(user.id),
        "actor_name": getattr(user, "full_name", None) or getattr(user, "username", None) or "Staff",
        "actor_email": getattr(user, "email", None),
        "timestamp": datetime.now(UTC).isoformat(),
        "old_method": old_method,
        "new_method": order.payment_method,
        "old_status": old_status,
        "new_status": order.payment_status,
        "amount_received": str(order.payment_amount_received or "0"),
        "notes": order.payment_notes,
    })
    meta["audit_history"] = actions
    meta["last_action_by_id"] = str(user.id)
    meta["last_action_by_name"] = getattr(user, "full_name", None) or getattr(user, "username", None)
    order.meta_json = meta

    session.add(
        PlatformAuditLog(
            customer_id=order.customer_id,
            actor_id=user.id,
            action="order.payment_status_updated",
            target_type="order",
            target_id=str(order.id),
            result="success",
            metadata_json={
                "old_method": old_method,
                "new_method": order.payment_method,
                "old_status": old_status,
                "new_status": order.payment_status,
                "amount_received": str(order.payment_amount_received or "0"),
                "notes": order.payment_notes,
                "staff_id": str(user.id),
                "staff_name": getattr(user, "full_name", None) or getattr(user, "username", None),
            },
        )
    )
    await session.commit()
    await session.refresh(order)
    return OrderResponse.model_validate(order)


@router.post(
    "/customers/{customer_id}/provision",
    response_model=OrderResponse,
    dependencies=[Depends(RequirePermission(Permission.SYSTEM_ADMIN))],
)
async def provision_customer_hosting(
    customer_id: UUID,
    body: StaffProvisionHostingRequest,
    session: DbSession,
    settings: SettingsDep,
) -> OrderResponse:
    from app.services.platform.orders import OrderService

    customer = await session.get(Customer, customer_id)
    if customer is None:
        from app.core.exceptions import NotFoundError

        raise NotFoundError("Customer not found.")
    return await OrderService(settings, session).provision_for_customer(
        customer=customer,
        plan_id=body.plan_id,
        domain_name=body.domain_name,
        domain_extension=body.domain_extension,
    )


@router.post(
    "/staff-users",
    dependencies=[Depends(RequirePermission(Permission.SYSTEM_ADMIN))],
)
async def create_staff_user(
    body: StaffUserCreateRequest,
    session: DbSession,
    settings: SettingsDep,
) -> dict:
    return await StaffPlatformService(settings, session).create_staff_user(
        email=body.email,
        password=body.password,
        full_name=body.full_name,
        role=body.role,
    )


@router.get(
    "/staff-users",
    response_model=list[StaffUserItem],
    dependencies=[Depends(RequirePermission(Permission.SYSTEM_ADMIN))],
)
async def list_staff_users(
    session: DbSession,
    settings: SettingsDep,
) -> list[StaffUserItem]:
    rows = await StaffPlatformService(settings, session).list_staff_users()
    return [StaffUserItem.model_validate(r) for r in rows]


@router.patch(
    "/staff-users/{user_id}",
    response_model=StaffUserItem,
    dependencies=[Depends(RequirePermission(Permission.SYSTEM_ADMIN))],
)
async def update_staff_user(
    user_id: UUID,
    body: StaffUserUpdateRequest,
    session: DbSession,
    settings: SettingsDep,
) -> StaffUserItem:
    row = await StaffPlatformService(settings, session).update_staff_user(
        user_id,
        is_active=body.is_active,
        role=body.role,
        full_name=body.full_name,
        password=body.password,
    )
    return StaffUserItem.model_validate(row)


@router.get(
    "/plans",
    response_model=list[HostingPlanSchema],
    dependencies=[Depends(RequirePermission(Permission.PLATFORM_READ))],
)
async def list_plans(
    session: DbSession,
    settings: SettingsDep,
    include_inactive: bool = Query(default=True),
) -> list[HostingPlanSchema]:
    rows = await StaffPlatformService(settings, session).list_plans(
        include_inactive=include_inactive
    )
    return [HostingPlanSchema.model_validate(p) for p in rows]


@router.post(
    "/plans",
    response_model=HostingPlanSchema,
    dependencies=[Depends(RequirePermission(Permission.PLATFORM_WRITE))],
)
async def create_plan(
    body: HostingPlanUpsertRequest,
    session: DbSession,
    settings: SettingsDep,
) -> HostingPlanSchema:
    plan = await StaffPlatformService(settings, session).create_plan(body.model_dump())
    return HostingPlanSchema.model_validate(plan)


@router.patch(
    "/plans/{plan_id}",
    response_model=HostingPlanSchema,
    dependencies=[Depends(RequirePermission(Permission.PLATFORM_WRITE))],
)
async def update_plan(
    plan_id: UUID,
    body: HostingPlanPatchRequest,
    session: DbSession,
    settings: SettingsDep,
) -> HostingPlanSchema:
    plan = await StaffPlatformService(settings, session).update_plan(
        plan_id, body.model_dump(exclude_unset=True)
    )
    return HostingPlanSchema.model_validate(plan)


@router.post(
    "/plans/rebalance-from-price",
    response_model=list[HostingPlanSchema],
    dependencies=[Depends(RequirePermission(Permission.PLATFORM_WRITE))],
)
async def rebalance_plans_from_price(
    session: DbSession,
    settings: SettingsDep,
) -> list[HostingPlanSchema]:
    """Recalculate every plan's CPU/RAM/storage/bandwidth/AI from its monthly price."""
    rows = await StaffPlatformService(settings, session).rebalance_plans_from_price()
    return [HostingPlanSchema.model_validate(p) for p in rows]


@router.post(
    "/environments/{environment_id}/suspend",
    response_model=StaffEnvironmentItem,
    dependencies=[Depends(RequirePermission(Permission.PLATFORM_OPS))],
)
async def suspend_environment(
    environment_id: UUID,
    session: DbSession,
    settings: SettingsDep,
) -> StaffEnvironmentItem:
    svc = StaffPlatformService(settings, session)
    env = await svc.suspend_environment(environment_id)
    return StaffEnvironmentItem.model_validate(svc.env_item_payload(env))


@router.post(
    "/environments/{environment_id}/restore",
    response_model=StaffEnvironmentItem,
    dependencies=[Depends(RequirePermission(Permission.PLATFORM_OPS))],
)
async def restore_environment(
    environment_id: UUID,
    session: DbSession,
    settings: SettingsDep,
) -> StaffEnvironmentItem:
    svc = StaffPlatformService(settings, session)
    env = await svc.restore_environment(environment_id)
    return StaffEnvironmentItem.model_validate(svc.env_item_payload(env))


@router.post(
    "/environments/{environment_id}/terminate",
    response_model=StaffEnvironmentItem,
    dependencies=[Depends(RequirePermission(Permission.SYSTEM_ADMIN))],
)
async def terminate_environment(
    environment_id: UUID,
    session: DbSession,
    settings: SettingsDep,
    confirm: bool = Query(default=True),
) -> StaffEnvironmentItem:
    """Permanently mark a tenant environment terminated (superadmin only, requires confirmation)."""
    if not confirm:
        from app.core.exceptions import ValidationError

        raise ValidationError("Destructive action confirmation required (confirm=true).")
    svc = StaffPlatformService(settings, session)
    env = await svc.terminate_environment(environment_id)
    return StaffEnvironmentItem.model_validate(svc.env_item_payload(env))


@router.post(
    "/environments/{environment_id}/stacks/clear",
    response_model=MessageResponse,
    dependencies=[Depends(RequirePermission(Permission.PLATFORM_OPS))],
)
async def clear_environment_stack(
    environment_id: UUID,
    session: DbSession,
    settings: SettingsDep,
    drop_database: bool = Query(default=False),
) -> MessageResponse:
    """Staff: wipe a customer's broken stack (site folder only) and leave a parking page."""
    from app.models.platform import CustomerEnvironment
    from app.core.exceptions import NotFoundError
    from app.services.platform.stacks import EnvironmentStackService

    env = await session.get(CustomerEnvironment, environment_id)
    if env is None:
        raise NotFoundError("Environment not found.")
    result = await EnvironmentStackService(settings, session).clear_install(
        env, drop_database=drop_database, actor="staff"
    )
    return MessageResponse(message=str(result.get("message") or "Installation cleared."))


@router.post(
    "/environments/{environment_id}/health/check",
    dependencies=[Depends(RequirePermission(Permission.PLATFORM_OPS))],
)
async def staff_env_health_check(
    environment_id: UUID,
    session: DbSession,
    settings: SettingsDep,
) -> dict:
    from app.services.platform.health import EnvironmentHealthService

    svc = StaffPlatformService(settings, session)
    env = await svc.get_environment(environment_id)
    result = await EnvironmentHealthService(settings, session).probe(env)
    return {
        "environment_id": env.id,
        "domain": env.domain,
        "status": str(result.get("status") or env.status),
        "health_status": str(result.get("health_status") or env.health_status),
        "summary": str(result.get("summary") or ""),
        "checks": dict(result.get("checks") or {}),
        "checked_at": result.get("checked_at"),
        "message": "Health check completed.",
    }


@router.get(
    "/environments/{environment_id}/usage",
    dependencies=[Depends(RequirePermission(Permission.PLATFORM_READ))],
)
async def staff_env_usage(
    environment_id: UUID,
    session: DbSession,
    settings: SettingsDep,
) -> dict:
    from app.services.platform.usage import usage_snapshot

    env = await StaffPlatformService(settings, session).get_environment(environment_id)
    snap = usage_snapshot(env.document_root, env.storage_limit_gb)
    return {
        "environment_id": env.id,
        "domain": env.domain,
        "cpu_limit": env.cpu_limit,
        "ram_limit_gb": env.ram_limit_gb,
        "storage_limit_gb": env.storage_limit_gb,
        "storage_used_bytes": int(snap["storage_used_bytes"]),
        "storage_used_gb": float(snap["storage_used_gb"]),
        "storage_pct": float(snap["storage_pct"]),
        "file_count": int(snap["file_count"]),
        "isolation_type": env.isolation_type or "filesystem",
        "soft_warning": bool(snap["soft_warning"]),
        "hard_exceeded": bool(snap["hard_exceeded"]),
        "storage_status": str(snap["storage_status"]),
        "message": str(snap["message"]),
        "container_id": env.container_id,
        "ftp_username": env.ftp_username,
    }


@router.get(
    "/environments/{environment_id}/stacks",
    dependencies=[Depends(RequirePermission(Permission.PLATFORM_READ))],
)
async def staff_env_stacks(
    environment_id: UUID,
    session: DbSession,
    settings: SettingsDep,
) -> dict:
    from app.models.platform import HostingPlan, Subscription
    from app.services.platform.stacks import EnvironmentStackService

    env = await StaffPlatformService(settings, session).get_environment(environment_id)
    svc = EnvironmentStackService(settings, session)
    sub = await session.get(Subscription, env.subscription_id)
    plan = await session.get(HostingPlan, sub.plan_id) if sub else None
    progress = svc.read_progress(env)
    active_job_id = None
    if progress and progress.get("job_id") and progress.get("status") in {"queued", "running"}:
        try:
            active_job_id = str(progress["job_id"])
        except (ValueError, TypeError):
            active_job_id = None
    return {
        "environment_id": env.id,
        "stacks": svc.list_stacks(plan),
        "current": await svc.reconcile_stack(env),
        "progress": progress,
        "active_job_id": active_job_id,
    }


@router.get(
    "/environments/{environment_id}/logs",
    dependencies=[Depends(RequirePermission(Permission.PLATFORM_OPS))],
)
async def staff_env_logs(
    environment_id: UUID,
    session: DbSession,
    settings: SettingsDep,
    lines: int = Query(default=200, ge=20, le=500),
) -> dict:
    from app.services.platform.env_logs import read_environment_logs

    env = await StaffPlatformService(settings, session).get_environment(environment_id)
    payload = read_environment_logs(env, lines=lines)
    return {
        "environment_id": env.id,
        "sources": list(payload.get("sources") or []),
        "entries": list(payload.get("entries") or []),
        "message": payload.get("message"),
    }


@router.post(
    "/environments/{environment_id}/filesystem/repair",
    response_model=MessageResponse,
    dependencies=[Depends(RequirePermission(Permission.PLATFORM_OPS))],
)
async def staff_repair_env_filesystem(
    environment_id: UUID,
    session: DbSession,
    settings: SettingsDep,
) -> MessageResponse:
    from pathlib import Path

    from app.core.exceptions import AppException
    from app.services.platform.unix_identity import UnixIdentityService

    env = await StaffPlatformService(settings, session).get_environment(environment_id)
    if not env.document_root:
        raise AppException("No site folder yet.")
    unix = UnixIdentityService(settings, session)
    unix.repair_dac(env, dry_run=False, actor="staff")
    cfg = Path(env.document_root) / "wp-config.php"
    if cfg.exists():
        text = cfg.read_text(encoding="utf-8", errors="replace")
        if "FS_METHOD" not in text:
            needle = "/* That's all, stop editing!"
            inject = "define( 'FS_METHOD', 'direct' );\n"
            if needle in text:
                text = text.replace(needle, inject + needle)
            else:
                text += "\n" + inject
            cfg.write_text(text, encoding="utf-8")
            unix.apply_ownership(env, prepare_sftp_jail=False)
    await session.flush()
    return MessageResponse(message="Site folder DAC repaired (tenant ownership).")


@router.patch(
    "/environments/{environment_id}/subdomain",
    response_model=StaffEnvironmentItem,
    dependencies=[Depends(RequirePermission(Permission.DOMAINS_WRITE))],
)
async def update_environment_subdomain(
    environment_id: UUID,
    body: StaffUpdateSubdomainRequest,
    session: DbSession,
    settings: SettingsDep,
    user: CurrentUser,
) -> StaffEnvironmentItem:
    """Hosting operator only: edit/change subdomain of personal hostings."""
    svc = StaffPlatformService(settings, session)
    env = await svc.update_environment_subdomain(
        environment_id, body.domain, actor_id=user.id
    )
    return StaffEnvironmentItem.model_validate(svc.env_item_payload(env))


@router.post(
    "/environments/{environment_id}/stacks/install",
    dependencies=[Depends(RequirePermission(Permission.PLATFORM_OPS))],
)
async def staff_install_stack(
    environment_id: UUID,
    session: DbSession,
    settings: SettingsDep,
    stack: str = Query(min_length=2, max_length=32),
    replace: bool = Query(default=False),
) -> dict:
    from app.services.platform.stacks import EnvironmentStackService

    env = await StaffPlatformService(settings, session).get_environment(environment_id)
    svc = EnvironmentStackService(settings, session)
    job, task_id = await svc.queue_install(env, stack=stack, replace=replace)
    if task_id:
        return {
            "environment_id": env.id,
            "stack": stack,
            "queued": True,
            "job_id": job.id,
            "message": f"Installing {stack}…",
            "current": svc.current_stack(env),
            "progress": svc.read_progress(env),
        }
    result = await svc.install(env, stack=stack, replace=replace, job=job)
    job.status = "success"
    job.result = result
    return {
        "environment_id": env.id,
        "stack": stack,
        "queued": False,
        "job_id": job.id,
        "message": str(result.get("message") or f"{stack} installed."),
        "result": result,
        "current": result,
        "progress": svc.read_progress(env),
    }


@router.get(
    "/customers/{customer_id}/audit",
    dependencies=[Depends(RequirePermission(Permission.PLATFORM_READ))],
)
async def customer_audit(
    customer_id: UUID,
    session: DbSession,
    settings: SettingsDep,
    limit: int = Query(default=50, ge=1, le=200),
) -> list[dict]:
    return await StaffPlatformService(settings, session).list_customer_audit(
        customer_id, limit=limit
    )


@router.get(
    "/health-check",
    response_model=MessageResponse,
    dependencies=[Depends(RequirePermission(Permission.PLATFORM_READ))],
)
async def platform_admin_ready() -> MessageResponse:
    return MessageResponse(message="Staff platform console API ready.")


@router.get(
    "/hosting-provider",
    dependencies=[Depends(RequirePermission(Permission.PLATFORM_READ))],
)
async def hosting_provider_status(settings: SettingsDep) -> dict:
    """Staff: which hosting engine is default + OLSPanel connectivity (no secrets)."""
    from app.services.hosting_provider import get_hosting_provider, resolve_provider_kind

    kind = resolve_provider_kind(settings)
    provider = get_hosting_provider(kind, settings=settings)
    health = await provider.health()
    return {
        "default_provider": kind.value,
        "olspanel_configured": bool(
            (settings.olspanel_base_url or "").strip()
            and (settings.olspanel_admin_username or "").strip()
            and (settings.olspanel_admin_password or "").strip()
        ),
        "olspanel_base_url": (settings.olspanel_base_url or "").rstrip("/") or None,
        "health": health,
        "note": (
            "Install OLSPanel only on a clean hosting node (ports 80/443). "
            "Keep billing on IFNOTUS. Existing nginx tenants stay provider=legacy until migrated."
        ),
    }


@router.get(
    "/integrations",
    response_model=IntegrationsStatusResponse,
    dependencies=[Depends(RequirePermission(Permission.PLATFORM_READ))],
)
async def get_integrations(settings: SettingsDep) -> IntegrationsStatusResponse:
    data = IntegrationsSettingsStore(settings).status()
    return IntegrationsStatusResponse.model_validate(data)


@router.get(
    "/billing-terms",
    response_model=BillingTermsAdminResponse,
    dependencies=[Depends(RequirePermission(Permission.PLATFORM_READ))],
)
async def get_billing_terms(settings: SettingsDep) -> BillingTermsAdminResponse:
    from app.services.platform.billing_terms_store import BillingTermsStore

    data = BillingTermsStore(settings).get_config()
    return BillingTermsAdminResponse.model_validate(data)


@router.put(
    "/billing-terms",
    response_model=BillingTermsAdminResponse,
    dependencies=[Depends(RequirePermission(Permission.PLATFORM_WRITE))],
)
async def update_billing_terms(
    body: BillingTermsAdminUpdateRequest,
    settings: SettingsDep,
) -> BillingTermsAdminResponse:
    from app.services.platform.billing_terms_store import BillingTermsStore

    data = BillingTermsStore(settings).update_config(body.model_dump())
    return BillingTermsAdminResponse.model_validate(data)


@router.put(
    "/integrations",
    response_model=IntegrationsStatusResponse,
    dependencies=[Depends(RequirePermission(Permission.PLATFORM_WRITE))],
)
async def update_integrations(
    body: IntegrationsUpdateRequest,
    settings: SettingsDep,
) -> IntegrationsStatusResponse:
    store = IntegrationsSettingsStore(settings)
    data = store.update(body.model_dump(exclude_none=True))
    return IntegrationsStatusResponse.model_validate(data)


@router.post(
    "/integrations/import-env",
    response_model=IntegrationsStatusResponse,
    dependencies=[Depends(RequirePermission(Permission.PLATFORM_WRITE))],
)
async def import_integrations_from_env(settings: SettingsDep) -> IntegrationsStatusResponse:
    """Copy current .env integration values into the encrypted settings store."""
    data = IntegrationsSettingsStore(settings).import_from_env()
    return IntegrationsStatusResponse.model_validate(data)


@router.get(
    "/integrations/sms-balance",
    dependencies=[Depends(RequirePermission(Permission.PLATFORM_READ))],
)
async def get_sms_balance(
    session: DbSession,
    settings: SettingsDep,
) -> dict:
    """Get live balance from Arkasel/SMS provider + total SMS sent & cost tracking, excluding test accounts IFADE5 & IF2ACB."""
    from app.models.platform import Notification, Customer, CustomerEnvironment
    from app.services.platform.delivery import DeliveryService
    from sqlalchemy import func, select, or_

    delivery = DeliveryService(settings)
    bal = delivery.check_sms_balance()

    # Find customer IDs for test accounts IFADE5 & IF2ACB to exclude from paid SMS totals
    excluded_cust_res = await session.execute(
        select(Customer.id).join(CustomerEnvironment, CustomerEnvironment.customer_id == Customer.id, isouter=True).where(
            or_(
                Customer.storage_slug.in_(["IFADE5", "IF2ACB", "ifade5", "if2acb"]),
                CustomerEnvironment.hosting_name.in_(["ifade5", "if2acb", "IFADE5", "IF2ACB"]),
            )
        )
    )
    excluded_cust_ids = set(excluded_cust_res.scalars().all())

    stmt = select(func.count(Notification.id)).where(Notification.channel == "sms")
    if excluded_cust_ids:
        stmt = stmt.where(Notification.customer_id.notin_(excluded_cust_ids))
    res = await session.execute(stmt)
    total_sent = int(res.scalar() or 0)
    unit_rate = 0.04
    estimated_spent = round(total_sent * unit_rate, 2)

    # Recent SMS logs for system administrator / hosting operator transparency
    recent_stmt = (
        select(Notification, Customer)
        .join(Customer, Customer.id == Notification.customer_id, isouter=True)
        .where(Notification.channel == "sms")
        .order_by(Notification.created_at.desc())
        .limit(30)
    )
    recent_res = await session.execute(recent_stmt)
    logs = []
    for notif, cust in recent_res.all():
        logs.append({
            "id": str(notif.id),
            "customer_id": str(notif.customer_id),
            "customer_name": cust.full_name if cust else "Unknown",
            "account_code": getattr(cust, "storage_slug", None) if cust else None,
            "title": notif.title,
            "body": notif.body,
            "created_at": notif.created_at.isoformat() if notif.created_at else None,
        })

    return {
        **bal,
        "total_sms_sent": total_sent,
        "estimated_spent_ghs": estimated_spent,
        "unit_rate_ghs": unit_rate,
        "recent_logs": logs,
    }


@router.post(
    "/notifications/send-custom",
    dependencies=[Depends(RequirePermission(Permission.BILLING_MANAGE))],
)
async def send_custom_notification(
    body: StaffSendCustomMessageRequest,
    session: DbSession,
    settings: SettingsDep,
    user: CurrentUser,
) -> dict:
    """Allow billing agents & admins to send custom broadcast or individual SMS/email/in-app messages."""
    import asyncio
    from app.core.exceptions import AppException, NotFoundError
    from app.models.platform import Customer, CustomerEnvironment, Notification, PlatformAuditLog
    from app.services.platform.delivery import DeliveryService
    from sqlalchemy import select

    delivery = DeliveryService(settings)
    target_customers: list[Customer] = []

    rec_type = body.recipient_type.strip().lower()
    if rec_type == "individual":
        if not body.customer_id:
            raise AppException("customer_id is required for individual messages.")
        c = await session.get(Customer, body.customer_id)
        if not c:
            raise NotFoundError("Customer not found.")
        target_customers = [c]
    elif rec_type == "active_subscribers":
        res = await session.execute(
            select(Customer)
            .join(CustomerEnvironment, CustomerEnvironment.customer_id == Customer.id)
            .where(CustomerEnvironment.status.in_(["active", "provisioning"]))
            .distinct()
        )
        target_customers = list(res.scalars().all())
    else:  # "all"
        res = await session.execute(select(Customer).order_by(Customer.created_at.desc()))
        target_customers = list(res.scalars().all())

    sent_count = 0
    channel = body.channel.strip().lower()

    for cust in target_customers:
        # Create in-app notification record
        notif = Notification(
            customer_id=cust.id,
            title=body.title.strip()[:255],
            body=body.message.strip()[:2000],
            kind="billing" if "bill" in body.title.lower() else "info",
            channel=channel if channel in {"sms", "email", "panel"} else "panel",
            is_read=False,
        )
        session.add(notif)

        # Deliver SMS if requested and phone available
        if channel in {"sms", "both"} and cust.phone:
            try:
                await asyncio.to_thread(delivery.send_sms, to=cust.phone, body=body.message.strip()[:320])
            except Exception:
                pass

        # Deliver Email if requested and email available
        if channel in {"email", "both"} and cust.email:
            try:
                await asyncio.to_thread(
                    delivery.send_email,
                    to=cust.email,
                    subject=body.title.strip(),
                    html=f"<p>{body.message.strip()}</p>",
                    text=body.message.strip(),
                )
            except Exception:
                pass

        sent_count += 1

    session.add(
        PlatformAuditLog(
            actor_id=user.id,
            action="notification.custom_broadcast",
            target_type="notification",
            details={
                "recipient_type": rec_type,
                "channel": channel,
                "title": body.title,
                "recipients_count": sent_count,
            },
        )
    )
    await session.commit()

    return {
        "success": True,
        "recipients_count": sent_count,
        "message": f"Message dispatched to {sent_count} recipient(s) via {channel}.",
    }



@router.get(
    "/coupons",
    dependencies=[Depends(RequirePermission(Permission.PLATFORM_READ))],
)
async def list_coupons(session: DbSession) -> list[dict]:
    from app.services.platform.coupons import CouponService

    rows = await CouponService(session).list_coupons()
    return [
        {
            "id": str(c.id),
            "code": c.code,
            "description": c.description,
            "discount_type": c.discount_type,
            "discount_value": float(c.discount_value),
            "active": c.active,
            "usage_limit": c.usage_limit,
            "usage_count": int(c.usage_count or 0),
            "usage_limit_per_customer": c.usage_limit_per_customer,
            "minimum_order_amount": float(c.minimum_order_amount) if c.minimum_order_amount is not None else None,
            "maximum_discount_amount": float(c.maximum_discount_amount)
            if c.maximum_discount_amount is not None
            else None,
            "plan_slugs": list(c.plan_slugs or []),
            "billing_term_months": list(c.billing_term_months or []),
            "new_customers_only": bool(c.new_customers_only),
        }
        for c in rows
    ]


@router.post(
    "/coupons",
    dependencies=[Depends(RequirePermission(Permission.PLATFORM_WRITE))],
)
async def upsert_coupon(
    body: dict,
    session: DbSession,
    user: CurrentUser,
) -> dict:
    from decimal import Decimal

    from app.services.platform.coupons import CouponService

    c = await CouponService(session).upsert(
        code=str(body.get("code") or ""),
        description=body.get("description"),
        discount_type=str(body.get("discount_type") or "percentage"),
        discount_value=Decimal(str(body.get("discount_value") or 0)),
        active=bool(body.get("active", True)),
        usage_limit=body.get("usage_limit"),
        usage_limit_per_customer=body.get("usage_limit_per_customer"),
        minimum_order_amount=body.get("minimum_order_amount"),
        maximum_discount_amount=body.get("maximum_discount_amount"),
        plan_slugs=list(body.get("plan_slugs") or []),
        billing_term_months=list(body.get("billing_term_months") or []),
        new_customers_only=bool(body.get("new_customers_only", False)),
        created_by=user.id,
    )
    await session.commit()
    return {"id": str(c.id), "code": c.code, "active": c.active}


@router.get(
    "/capacity",
    response_model=StaffCapacityDashboardResponse,
    dependencies=[Depends(RequirePermission(Permission.PLATFORM_READ))],
)
async def platform_capacity(
    session: DbSession,
    settings: SettingsDep,
) -> StaffCapacityDashboardResponse:
    """Staff hosting-operations capacity dashboard for the shared node."""
    from app.services.platform.staff_capacity import StaffCapacityService

    data = await StaffCapacityService(settings, session).dashboard()
    nodes = [CapacityNodeResponse.model_validate(n) for n in data.get("nodes") or []]
    return StaffCapacityDashboardResponse(
        display_name=str(data.get("display_name") or "Shared Node 01"),
        hostname=str(data.get("hostname") or "ifnotus-1"),
        checked_at=data.get("checked_at"),
        live=dict(data.get("live") or {}),
        policy=dict(data.get("policy") or {}),
        counts=dict(data.get("counts") or {}),
        ops=dict(data.get("ops") or {}),
        host_pressure=dict(data.get("host_pressure") or {}),
        nodes=nodes,
        selling_paused=bool(data.get("selling_paused")),
    )


@router.get(
    "/site-theme",
    response_model=SiteThemeStatusResponse,
    dependencies=[Depends(RequirePermission(Permission.PLATFORM_READ))],
)
async def get_site_theme(settings: SettingsDep) -> SiteThemeStatusResponse:
    return SiteThemeStatusResponse.model_validate(SiteThemeStore(settings).status())


@router.put(
    "/site-theme",
    response_model=SiteThemeStatusResponse,
    dependencies=[Depends(RequirePermission(Permission.PLATFORM_WRITE))],
)
async def update_site_theme(
    body: SiteThemeUpdateRequest,
    settings: SettingsDep,
) -> SiteThemeStatusResponse:
    data = SiteThemeStore(settings).update(
        body.theme,
        colors=body.colors,
        plan_colors=body.plan_colors,
        home_layout=body.home_layout,
        maintenance_mode=body.maintenance_mode,
        maintenance_message=body.maintenance_message,
    )
    return SiteThemeStatusResponse.model_validate(data)
