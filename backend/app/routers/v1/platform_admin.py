"""Staff product console APIs — customers, plans, orders, env lifecycle."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Query

from app.api.deps import CurrentUser, DbSession, RequirePermission, SettingsDep
from app.core.permissions import Permission
from app.models.platform import Customer
from app.schemas.common import MessageResponse
from app.schemas.integrations import IntegrationsStatusResponse, IntegrationsUpdateRequest
from app.schemas.platform import CustomerResponse, HostingPlanSchema, OrderResponse
from app.schemas.platform_admin import (
    HostingPlanPatchRequest,
    HostingPlanUpsertRequest,
    SiteThemeStatusResponse,
    SiteThemeUpdateRequest,
    StaffConfirmPaymentRequest,
    StaffCustomerDetailResponse,
    StaffCustomerListItem,
    StaffEnvironmentItem,
    StaffGrantCreditsRequest,
    StaffGrantCreditsResponse,
    StaffOrderItem,
    StaffProvisionHostingRequest,
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


@router.get(
    "/orders",
    response_model=list[StaffOrderItem],
    dependencies=[Depends(RequirePermission(Permission.PLATFORM_READ))],
)
async def list_orders(
    session: DbSession,
    settings: SettingsDep,
    payment_status: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
) -> list[StaffOrderItem]:
    rows = await StaffPlatformService(settings, session).list_orders(
        payment_status=payment_status, limit=limit
    )
    return [StaffOrderItem.model_validate(r) for r in rows]


@router.post(
    "/orders/{order_id}/confirm-payment",
    response_model=OrderResponse,
    dependencies=[Depends(RequirePermission(Permission.CUSTOMERS_MANAGE))],
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
    )


@router.post(
    "/orders/{order_id}/retry-provision",
    response_model=OrderResponse,
    dependencies=[Depends(RequirePermission(Permission.CUSTOMERS_MANAGE))],
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
    dependencies=[Depends(RequirePermission(Permission.CUSTOMERS_MANAGE))],
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
) -> StaffEnvironmentItem:
    """Permanently mark a tenant environment terminated (superadmin only)."""
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
        "current": svc.current_stack(env),
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
    "/integrations",
    response_model=IntegrationsStatusResponse,
    dependencies=[Depends(RequirePermission(Permission.PLATFORM_READ))],
)
async def get_integrations(settings: SettingsDep) -> IntegrationsStatusResponse:
    data = IntegrationsSettingsStore(settings).status()
    return IntegrationsStatusResponse.model_validate(data)


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
    )
    return SiteThemeStatusResponse.model_validate(data)
