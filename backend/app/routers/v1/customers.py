"""IFNOTUS customer portal + product APIs."""

from __future__ import annotations

import ipaddress
from uuid import UUID

from fastapi import APIRouter, File, Query, Request, UploadFile
from sqlalchemy import select

from app.api.deps import AccessControlDep, CurrentUser, DbSession, SettingsDep
from app.core.exceptions import AppException, AuthenticationError, AuthorizationError, NotFoundError
from app.core.permissions import Permission, Role
from app.core.security import create_token_pair, hash_password
from app.models.platform import CustomerEnvironment, EnvironmentDatabase, HostingPlan, PlatformAuditLog, Subscription
from app.schemas.ai import (
    AiApplyActionRequest,
    AiChatRequest,
    AiChatResponse,
    AiSessionCreateRequest,
    AiSessionDetail,
    AiSessionListResponse,
    AiSessionSummary,
    AiUsageStats,
)
from app.schemas.auth import LoginRequest, LoginResponse
from app.schemas.common import MessageResponse
from app.schemas.databases import (
    DbQueryRequest,
    DbQueryResponse,
    DbRowMutationRequest,
    DbRowsRequest,
    DbSchemaResponse,
)
from app.schemas.hosting import (
    FileChmodRequest,
    FileDetailSchema,
    FileUploadCompleteRequest,
    FileUploadInitRequest,
    FileUploadInitResponse,
    MailboxCreate,
    MailboxPasswordReset,
    MailboxUpdate,
    MailAliasCreate,
    MailAliasSchema,
    MailAliasUpdate,
    MailDomainResponse,
    MailboxSchema,
)
from app.schemas.operations import FileListResponse, OperationResult
from app.schemas.platform import (
    AiCreditAccountResponse,
    AiOperationCompleteRequest,
    AiOperationRequest,
    AiOperationResponse,
    AttachCustomDomainRequest,
    UnassignCustomDomainRequest,
    AutoRenewRequest,
    CapacityNodeResponse,
    StaffCapacityDashboardResponse,
    ChangePlanRequest,
    CreateDomainOrderRequest,
    CreateEnvironmentDomainRequest,
    CustomerDomainItemResponse,
    CustomerDomainListResponse,
    CreateOrderRequest,
    CreateOrderResponse,
    CreditTopUpRequest,
    CreditTopUpResponse,
    EnvironmentDnsRecordCreateRequest,
    EnvironmentDomainEntry,
    EnvironmentDomainListResponse,
    EnvironmentGitCloneRequest,
    EnvironmentRedirectCreateRequest,
    HostingPlanSchema,
    UpdateEnvironmentDomainRequest,
    CustomerCompleteProfileRequest,
    CustomerDashboardResponse,
    CustomerFileMkdirRequest,
    CustomerFileWriteRequest,
    CustomerFileMoveRequest,
    CustomerFileCopyRequest,
    CustomerFileExtractRequest,
    CustomerFileCompressRequest,
    CustomerTrashEntrySchema,
    CustomerTrashListResponse,
    CustomerTrashRestoreRequest,
    CustomerTrashMoveRequest,
    CustomerPasswordChangeRequest,
    CustomerPhoneOtpRequest,
    CustomerPhoneOtpRequestResponse,
    CustomerPhoneOtpVerifyRequest,
    CustomerProfileUpdateRequest,
    CustomerRegisterRequest,
    CustomerRegisterResponse,
    CustomerResponse,
    CustomerVerifyEmailRequest,
    DomainAvailabilityRequest,
    DomainAvailabilityResponse,
    StudentHostnameRequest,
    StudentHostnameResponse,
    PanelAliasResolveResponse,
    HostingSsoHandoffRequest,
    HostingSsoHandoffResponse,
    PanelLoginRequest,
    PanelPasswordCreateRequest,
    PanelStatusResponse,
    TotpConfirmRequest,
    TotpSetupResponse,
    EnvironmentDatabaseResponse,
    EnvironmentDatabaseCreateRequest,
    EnvironmentDatabaseImportRequest,
    EnvironmentDatabaseImportResponse,
    EnvironmentDatabaseRevealResponse,
    PhpMyAdminOpenResponse,
    HostingPasswordSetRequest,
    HostingPasswordSetResponse,
    SubscriptionCancelRequest,
    SubscriptionCancelResponse,
    EnvironmentDatabaseV2Response,
    ApplicationInstanceCreateRequest,
    ApplicationInstanceResponse,
    ApplicationCatalogEntry,
    EnvironmentDnsResponse,
    EnvironmentBackupResponse,
    EnvironmentBackupRestoreResponse,
    EnvironmentFtpResponse,
    EnvironmentSftpKeyCreate,
    EnvironmentSftpKeyResponse,
    EnvironmentSftpResponse,
    EnvironmentSshResponse,
    EnvironmentResponse,
    EnvironmentSslResponse,
    EnvironmentMonitoringResponse,
    EnvironmentUsageResponse,
    EnvironmentHealthResponse,
    HostingPanelThemeActivateRequest,
    HostingPanelThemePurchaseRequest,
    HostingPanelThemeStatusResponse,
    NotificationResponse,
    OrderResponse,
    RenewPaymentResponse,
    RenewSubscriptionRequest,
    StackInstallRequest,
    StackInstallResponse,
    StackClearRequest,
    StackClearResponse,
    StackJobStatusResponse,
    StackStatusResponse,
    EnvLogsResponse,
    StackInfoSchema,
    EnvCronCreateRequest,
    EnvCronUpdateRequest,
    EnvCronListResponse,
    EnvCronJobSchema,
    InvoiceViewResponse,
    SubscriptionResponse,
    SubmitMomoRequest,
    VerifyPaymentRequest,
)
from app.schemas.support import (
    SupportTicketCreateRequest,
    SupportTicketMessageCreateRequest,
    SupportTicketMessageResponse,
    SupportTicketResponse,
)
from app.services.hosting.databases import DatabaseManagerService
from app.services.hosting.db_studio import DatabaseStudioService
from app.services.hosting.files import FileManagerService
from app.services.platform.billing import SubscriptionBillingService
from app.services.platform.credits import AiCreditService
from app.services.platform.customers import CustomerService
from app.services.platform.notifications import NotificationService
from app.services.platform.orders import OrderService
from app.services.platform.paystack import PaystackService
from app.services.platform.provisioning import ProvisioningEngine
from app.services.platform.registrar import DomainRegistrar
from app.services.platform.resources import ResourceManager
from app.services.platform.tenant import TenantService
from app.services.platform.tickets import SupportTicketService

router = APIRouter()


def _require_customer_user(user) -> None:
    roles = set(user.roles or [])
    if (
        user.is_superuser
        or Role.CUSTOMER.value in roles
        or Role.PLATFORM_OWNER.value in roles
        or Role.PLATFORM_ADMIN.value in roles
        or Role.ADMIN.value in roles
        or Role.SUPERADMIN.value in roles
        or Role.HOSTING_OPERATOR.value in roles
        or Role.OPERATOR.value in roles
        or Role.BILLING_AGENT.value in roles
        or Role.SUPPORT_AGENT.value in roles
        or Role.AUDITOR.value in roles
    ):
        return
    raise AuthorizationError("Customer account required.")


def _is_staff_user(user) -> bool:
    roles = set(getattr(user, "roles", None) or [])
    return bool(
        getattr(user, "is_superuser", False)
        or (
            roles
            & {
                Role.PLATFORM_OWNER.value,
                Role.PLATFORM_ADMIN.value,
                Role.ADMIN.value,
                Role.SUPERADMIN.value,
                Role.HOSTING_OPERATOR.value,
                Role.OPERATOR.value,
                Role.SUPPORT_AGENT.value,
                Role.BILLING_AGENT.value,
            }
        )
    )


async def _resolve_env_for_user(
    session: DbSession,
    settings: SettingsDep,
    user: CurrentUser,
    environment_id: UUID,
) -> CustomerEnvironment:
    if _is_staff_user(user):
        return await TenantService(session).get_owned_environment(None, environment_id)
    customer = await CustomerService(settings, session).require_for_user(user.id)
    return await TenantService(session).get_owned_environment(customer.id, environment_id)


def _env_response(env, plan=None) -> EnvironmentResponse:
    from app.services.platform.entitlements import effective_entitlements
    from app.services.platform.plan_matrix import capabilities_for

    data = EnvironmentResponse.model_validate(env)
    return data.model_copy(
        update={
            "db_password_set": bool(getattr(env, "db_password_encrypted", None)),
            "ip_address": None,
            "document_root": None,
            "container_port": None,
            "capabilities": capabilities_for(plan),
            "entitlements": effective_entitlements(plan),
            "provisioning_step": getattr(env, "provisioning_step", None),
            "unix_username": getattr(env, "unix_username", None),
            "unix_uid": getattr(env, "unix_uid", None),
            "unix_gid": getattr(env, "unix_gid", None),
        }
    )


def _customer_db_host(host: str | None) -> str:
    value = (host or "localhost").strip()
    if value in {"127.0.0.1", "::1", "0.0.0.0"}:
        return "localhost"
    try:
        ipaddress.ip_address(value.strip("[]"))
        return "localhost"
    except ValueError:
        return value

@router.post("/register", response_model=CustomerRegisterResponse)
async def register_customer(
    body: CustomerRegisterRequest,
    session: DbSession,
    settings: SettingsDep,
) -> CustomerRegisterResponse:
    svc = CustomerService(settings, session)
    customer, token = await svc.register(body)
    return CustomerRegisterResponse(customer=customer, verification_token=token)


@router.post("/verify-email", response_model=CustomerResponse)
async def verify_email(
    body: CustomerVerifyEmailRequest,
    session: DbSession,
    settings: SettingsDep,
) -> CustomerResponse:
    return await CustomerService(settings, session).verify_email(body)


def _client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    real_ip = request.headers.get("x-real-ip")
    return (real_ip.strip() if real_ip else None) or (
        request.client.host if request.client else "unknown"
    )


@router.post("/phone/request-otp", response_model=CustomerPhoneOtpRequestResponse)
async def request_phone_otp(
    body: CustomerPhoneOtpRequest,
    session: DbSession,
    settings: SettingsDep,
) -> CustomerPhoneOtpRequestResponse:
    return await CustomerService(settings, session).request_phone_otp(body)


@router.post("/phone/verify-otp", response_model=LoginResponse)
async def verify_phone_otp(
    body: CustomerPhoneOtpVerifyRequest,
    request: Request,
    session: DbSession,
    settings: SettingsDep,
    access: AccessControlDep,
) -> LoginResponse:
    from app.services.access_control import AccessContext
    from app.services.security_actions import detect_source

    ua = request.headers.get("user-agent")
    ip = _client_ip(request)
    ctx = AccessContext(
        ip_address=ip,
        user_agent=ua,
        device_fingerprint=request.headers.get("x-device-fingerprint"),
        request_id=request.headers.get("x-request-id"),
        source=detect_source(ua),
    )
    svc = CustomerService(settings, session)
    try:
        user, customer = await svc.verify_phone_otp(
            phone=body.phone,
            challenge_id=body.challenge_id,
            code=body.code,
            ip_address=ip,
        )
    except AuthenticationError as exc:
        await access.record_login_failure(
            ctx,
            username_or_email=body.phone,
            reason=str(exc.message) if hasattr(exc, "message") else "invalid_otp",
        )
        raise

    pair = create_token_pair(settings, subject=user.id)
    await access.record_login_success(
        ctx,
        username_or_email=user.email,
        user_id=user.id,
        trust_ip=False,
    )
    profile_ok = CustomerService.is_profile_complete(customer)
    return LoginResponse(
        status="ok",
        access_token=pair.access_token,
        refresh_token=pair.refresh_token,
        token_type=pair.token_type,
        expires_in=pair.expires_in,
        message=(
            "Welcome back."
            if profile_ok
            else "Phone verified. Finish your profile to continue."
        ),
    )


@router.post("/login", response_model=LoginResponse)
async def customer_login(
    body: LoginRequest,
    request: Request,
    session: DbSession,
    settings: SettingsDep,
    access: AccessControlDep,
) -> LoginResponse:
    from app.services.access_control import AccessContext
    from app.services.security_actions import detect_source

    ua = request.headers.get("user-agent")
    ip = _client_ip(request)
    ctx = AccessContext(
        ip_address=ip,
        user_agent=ua,
        device_fingerprint=body.device_fingerprint or request.headers.get("x-device-fingerprint"),
        request_id=request.headers.get("x-request-id"),
        source=detect_source(ua),
    )
    svc = CustomerService(settings, session)
    try:
        user, customer = await svc.authenticate_password(body.email, body.password, ip_address=ip)
        if getattr(user, "totp_enabled", False):
            from app.services import totp as totp_svc

            if not totp_svc.verify_code(user.totp_secret or "", body.totp_code or ""):
                return LoginResponse(
                    status="totp_required",
                    message="Enter the 6-digit code from your authenticator app.",
                )
    except AuthenticationError as exc:
        await access.record_login_failure(
            ctx,
            username_or_email=body.email,
            reason=str(exc.message) if hasattr(exc, "message") else "invalid_credentials",
        )
        raise
    pair = create_token_pair(settings, subject=user.id)
    await access.record_login_success(
        ctx,
        username_or_email=user.email,
        user_id=user.id,
        trust_ip=False,
    )
    return LoginResponse(
        status="ok",
        access_token=pair.access_token,
        refresh_token=pair.refresh_token,
        token_type=pair.token_type,
        expires_in=pair.expires_in,
        message=f"Welcome to IFNOTUS, {customer.full_name}.",
    )


@router.get("/panel/status", response_model=PanelStatusResponse)
async def panel_status(
    session: DbSession,
    username: str | None = Query(default=None, max_length=128),
    host: str | None = Query(default=None, max_length=253),
) -> PanelStatusResponse:
    """Public hint for tenant fpanel login (username + whether password exists)."""
    from app.services.platform.panel_passwords import PanelPasswordService

    data = await PanelPasswordService(session).status(username=username, host=host)
    return PanelStatusResponse.model_validate(data)


@router.post("/panel/create-password", response_model=PanelStatusResponse)
async def panel_create_password(
    body: PanelPasswordCreateRequest,
    session: DbSession,
) -> PanelStatusResponse:
    """First-time hosting panel password (username is the auto-assigned hosting_name)."""
    from app.services.platform.panel_passwords import PanelPasswordService

    data = await PanelPasswordService(session).create_password(body.username, body.password)
    return PanelStatusResponse.model_validate(data)


@router.post("/panel/login", response_model=LoginResponse)
async def panel_login(
    body: PanelLoginRequest,
    request: Request,
    session: DbSession,
    settings: SettingsDep,
    access: AccessControlDep,
) -> LoginResponse:
    """Tenant-only hosting panel login (hosting_name + panel password). Not for staff."""
    from app.services.access_control import AccessContext
    from app.services.platform.panel_passwords import PanelPasswordService
    from app.services.security_actions import detect_source

    ua = request.headers.get("user-agent")
    ip = _client_ip(request)
    ctx = AccessContext(
        ip_address=ip,
        user_agent=ua,
        device_fingerprint=body.device_fingerprint or request.headers.get("x-device-fingerprint"),
        request_id=request.headers.get("x-request-id"),
        source=detect_source(ua),
    )
    try:
        user, customer, env = await PanelPasswordService(session).authenticate(
            body.username,
            body.password,
            ip_address=ip,
        )
    except AuthenticationError as exc:
        await access.record_login_failure(
            ctx,
            username_or_email=body.username,
            reason=str(exc.message) if hasattr(exc, "message") else "invalid_panel_credentials",
        )
        raise
    pair = create_token_pair(settings, subject=user.id)
    await access.record_login_success(
        ctx,
        username_or_email=user.email,
        user_id=user.id,
        trust_ip=False,
    )
    return LoginResponse(
        status="ok",
        access_token=pair.access_token,
        refresh_token=pair.refresh_token,
        token_type=pair.token_type,
        expires_in=pair.expires_in,
        message=f"Welcome to the hosting panel for {env.domain or body.username}.",
    )


async def _db_user(session, user):
    from app.models.user import User

    return await session.get(User, user.id)


@router.get("/me", response_model=CustomerResponse)
async def customer_me(
    user: CurrentUser,
    session: DbSession,
    settings: SettingsDep,
) -> CustomerResponse:
    _require_customer_user(user)
    customer = await CustomerService(settings, session).require_for_user(user.id)
    row = await _db_user(session, user)
    return CustomerService.to_response(customer, row)


@router.patch("/me", response_model=CustomerResponse)
async def update_customer_me(
    body: CustomerProfileUpdateRequest,
    user: CurrentUser,
    session: DbSession,
    settings: SettingsDep,
) -> CustomerResponse:
    _require_customer_user(user)
    svc = CustomerService(settings, session)
    customer = await svc.require_for_user(user.id)
    row = await _db_user(session, user)
    customer = await svc.update_profile(customer, body, user=row)
    return CustomerService.to_response(customer, row)


@router.post("/me/complete-profile", response_model=CustomerResponse)
async def complete_customer_profile(
    body: CustomerCompleteProfileRequest,
    user: CurrentUser,
    session: DbSession,
    settings: SettingsDep,
) -> CustomerResponse:
    _require_customer_user(user)
    svc = CustomerService(settings, session)
    customer = await svc.require_for_user(user.id)
    row = await _db_user(session, user)
    if row is None:
        raise AuthenticationError("Account not found.")
    customer = await svc.complete_profile(customer, row, body)
    return CustomerService.to_response(customer, row)


@router.post("/me/password", response_model=MessageResponse)
async def change_customer_password(
    body: CustomerPasswordChangeRequest,
    user: CurrentUser,
    session: DbSession,
    settings: SettingsDep,
) -> MessageResponse:
    _require_customer_user(user)
    from app.models.user import User

    row = await session.get(User, user.id)
    if row is None:
        raise AuthorizationError("Account not found.")
    await CustomerService(settings, session).change_password(
        row, body.current_password, body.new_password
    )
    return MessageResponse(message="Password updated.")


@router.post("/me/totp/setup", response_model=TotpSetupResponse)
async def totp_setup(
    user: CurrentUser,
    session: DbSession,
    settings: SettingsDep,
) -> TotpSetupResponse:
    _require_customer_user(user)
    from app.models.user import User

    row = await session.get(User, user.id)
    if row is None:
        raise AuthorizationError("Account not found.")
    data = await CustomerService(settings, session).totp_setup(row)
    return TotpSetupResponse.model_validate(data)


@router.post("/me/totp/confirm", response_model=MessageResponse)
async def totp_confirm(
    body: TotpConfirmRequest,
    user: CurrentUser,
    session: DbSession,
    settings: SettingsDep,
) -> MessageResponse:
    _require_customer_user(user)
    from app.models.user import User

    row = await session.get(User, user.id)
    if row is None:
        raise AuthorizationError("Account not found.")
    await CustomerService(settings, session).totp_confirm(row, body.code)
    return MessageResponse(message="Authenticator is on.")


@router.post("/me/totp/disable", response_model=MessageResponse)
async def totp_disable(
    body: TotpConfirmRequest,
    user: CurrentUser,
    session: DbSession,
    settings: SettingsDep,
) -> MessageResponse:
    _require_customer_user(user)
    from app.models.user import User

    row = await session.get(User, user.id)
    if row is None:
        raise AuthorizationError("Account not found.")
    await CustomerService(settings, session).totp_disable(row, body.code)
    return MessageResponse(message="Authenticator is off.")


@router.get("/dashboard", response_model=CustomerDashboardResponse)
async def customer_dashboard(
    user: CurrentUser,
    session: DbSession,
    settings: SettingsDep,
) -> CustomerDashboardResponse:
    _require_customer_user(user)
    customers = CustomerService(settings, session)
    customer = await customers.require_for_user(user.id)
    credits = await AiCreditService(session).get_account(customer.id)
    envs = await ProvisioningEngine(settings, session).list_environments(customer.id)
    subs_result = await session.execute(
        select(Subscription)
        .where(
            Subscription.customer_id == customer.id,
            Subscription.status.notin_(("cancelled", "canceled", "terminated")),
        )
        .order_by(Subscription.created_at.desc())
    )
    subs = list(subs_result.scalars().all())
    unread_badge = await SupportTicketService(settings, session).count_awaiting_customer(customer.id)
    usage = await ResourceManager(session).active_subscription_usage(customer.id)
    orders = await OrderService(settings, session).list_orders(customer.id)
    from app.services.platform.plan_matrix import features_for

    plan_rows: dict = {}
    for sub in subs:
        if sub.plan_id in plan_rows:
            continue
        row = await session.get(HostingPlan, sub.plan_id)
        if row is not None:
            plan_rows[sub.plan_id] = row
    sub_by_id = {s.id: s for s in subs}
    plan_schemas = [
        HostingPlanSchema.model_validate(p).model_copy(update={"features": features_for(p)})
        for p in plan_rows.values()
    ]
    env_payloads = []
    for e in envs:
        sub = sub_by_id.get(e.subscription_id)
        env_payloads.append(_env_response(e, plan_rows.get(sub.plan_id) if sub else None))
    row = await _db_user(session, user)
    from app.services.platform.credits import TOKENS_PER_CREDIT, tokens_from_credits

    return CustomerDashboardResponse(
        customer=CustomerService.to_response(customer, row),
        credits=AiCreditAccountResponse(
            customer_id=credits.customer_id,
            credits_remaining=credits.credits_remaining,
            total_allocated=credits.total_allocated,
            lifetime_used=credits.lifetime_used,
            tokens_remaining=tokens_from_credits(credits.credits_remaining),
            tokens_per_credit=TOKENS_PER_CREDIT,
        ),
        environments=env_payloads,
        subscriptions=[SubscriptionResponse.model_validate(s) for s in subs],
        unread_notifications=unread_badge,
        usage=usage,
        orders=[OrderResponse.model_validate(o) for o in orders],
        momo=OrderService(settings, session)._momo_details(),
        plans=plan_schemas,
    )


@router.post("/orders", response_model=CreateOrderResponse)
async def create_order(
    body: CreateOrderRequest,
    user: CurrentUser,
    session: DbSession,
    settings: SettingsDep,
) -> CreateOrderResponse:
    from app.core.exceptions import ValidationError

    _require_customer_user(user)
    svc = CustomerService(settings, session)
    customer = await svc.require_for_user(user.id)
    if not CustomerService.can_order(customer):
        missing = ", ".join(CustomerService.missing_for_order(customer)) or "profile details"
        raise ValidationError(
            f"Add your {missing.replace('_', ' ')} before ordering.",
            code="profile_incomplete_for_order",
        )
    data = await OrderService(settings, session).create_order(customer, body)
    return CreateOrderResponse(**data)


@router.post("/orders/preview-coupon")
async def preview_coupon(
    body: dict,
    user: CurrentUser,
    session: DbSession,
    settings: SettingsDep,
) -> dict:
    """Validate a coupon against a plan + term without creating an order."""
    from decimal import Decimal
    from uuid import UUID as _UUID

    from app.core.exceptions import NotFoundError, ValidationError
    from app.models.platform import HostingPlan, Order
    from app.services.platform.billing_terms_store import BillingTermsStore
    from app.services.platform.coupons import CouponService
    from sqlalchemy import func, select

    _require_customer_user(user)
    customer = await CustomerService(settings, session).require_for_user(user.id)
    plan_id = body.get("plan_id")
    code = body.get("code")
    if not plan_id or not code:
        raise ValidationError("plan_id and code are required.", code="coupon_preview_input")
    plan = await session.get(HostingPlan, _UUID(str(plan_id)))
    if not plan or not plan.is_active:
        raise NotFoundError("Plan not found.")
    months = int(body.get("billing_term_months") or 1)
    term = BillingTermsStore(settings).resolve_term(months, monthly_price=plan.price_monthly)
    prior = (
        await session.execute(select(func.count()).select_from(Order).where(Order.customer_id == customer.id))
    ).scalar_one()
    applied = await CouponService(session).validate_for_order(
        code=str(code),
        customer=customer,
        plan=plan,
        plan_total=term["plan_total"],
        billing_term_months=int(term["months"]),
        is_new_customer=int(prior or 0) == 0,
    )
    return {
        "code": applied["code"],
        "discount_type": applied["discount_type"],
        "discount_value": float(applied["discount_value"]),
        "discount_amount": float(applied["discount_amount"]),
        "plan_total_before": float(term["plan_total"]),
        "plan_total_after": float(applied["plan_total_after"]),
    }


@router.get("/orders", response_model=list[OrderResponse])
async def list_orders(
    user: CurrentUser,
    session: DbSession,
    settings: SettingsDep,
) -> list[OrderResponse]:
    _require_customer_user(user)
    customer = await CustomerService(settings, session).require_for_user(user.id)
    orders = await OrderService(settings, session).list_orders(customer.id)
    return [OrderResponse.model_validate(o) for o in orders]


@router.get("/orders/{order_id}", response_model=InvoiceViewResponse)
async def get_invoice(
    order_id: UUID,
    user: CurrentUser,
    session: DbSession,
    settings: SettingsDep,
) -> InvoiceViewResponse:
    _require_customer_user(user)
    customer = await CustomerService(settings, session).require_for_user(user.id)
    return await OrderService(settings, session).invoice_view(customer.id, order_id)


@router.post("/orders/{order_id}/momo", response_model=OrderResponse)
async def submit_momo_transaction(
    order_id: UUID,
    body: SubmitMomoRequest,
    user: CurrentUser,
    session: DbSession,
    settings: SettingsDep,
) -> OrderResponse:
    _require_customer_user(user)
    customer = await CustomerService(settings, session).require_for_user(user.id)
    return await OrderService(settings, session).submit_momo_transaction(
        customer.id, order_id, body.transaction_id
    )


@router.post("/orders/verify-payment", response_model=OrderResponse)
async def verify_payment(
    body: VerifyPaymentRequest,
    user: CurrentUser,
    session: DbSession,
    settings: SettingsDep,
) -> OrderResponse:
    _require_customer_user(user)
    # Ensure the order belongs to this customer
    customer = await CustomerService(settings, session).require_for_user(user.id)
    order = await OrderService(settings, session).verify_and_activate(body.reference)
    if order.customer_id != customer.id and not user.is_superuser:
        raise AuthorizationError("This payment does not belong to your account.")
    return order


@router.post("/billing/webhook")
async def paystack_webhook(
    request: Request,
    session: DbSession,
    settings: SettingsDep,
) -> MessageResponse:
    body = await request.body()
    signature = request.headers.get("x-paystack-signature")
    paystack = PaystackService(settings)
    if not paystack.verify_webhook_signature(body, signature):
        raise AuthorizationError("Invalid Paystack signature.")
    import json

    event = json.loads(body.decode() or "{}")
    if event.get("event") == "charge.success":
        data = event.get("data") or {}
        reference = data.get("reference")
        if reference:
            await OrderService(settings, session).verify_and_activate(reference)
    return MessageResponse(message="ok")


@router.get("/environments", response_model=list[EnvironmentResponse])
async def list_environments(
    user: CurrentUser,
    session: DbSession,
    settings: SettingsDep,
) -> list[EnvironmentResponse]:
    _require_customer_user(user)
    customer = await CustomerService(settings, session).require_for_user(user.id)
    envs = await ProvisioningEngine(settings, session).list_environments(customer.id)
    tenant = TenantService(session)
    out = []
    for e in envs:
        plan = await tenant.plan_for_environment(e)
        out.append(_env_response(e, plan))
    return out


@router.get("/environments/{environment_id}", response_model=EnvironmentResponse)
async def get_environment_by_id(
    environment_id: UUID,
    user: CurrentUser,
    session: DbSession,
    settings: SettingsDep,
) -> EnvironmentResponse:
    """Retrieve environment metadata for active customer or staff."""
    _require_customer_user(user)
    env = await _resolve_env_for_user(session, settings, user, environment_id)
    tenant = TenantService(session)
    plan = await tenant.plan_for_environment(env)
    return _env_response(env, plan)


@router.get(
    "/environments/{environment_id}/files",
    response_model=FileListResponse,
)
async def list_env_files(
    environment_id: UUID,
    user: CurrentUser,
    session: DbSession,
    settings: SettingsDep,
    path: str = Query(default="."),
) -> FileListResponse:
    _require_customer_user(user)
    customer = await CustomerService(settings, session).require_for_user(user.id)
    env = await TenantService(session).get_owned_environment(customer.id, environment_id)
    roots = await TenantService(session).roots_for_environment(customer.id, environment_id)
    return await _tenant_files(settings, env, roots).list_files(path)


@router.get(
    "/environments/{environment_id}/files/content",
    response_model=FileDetailSchema,
)
async def read_env_file(
    environment_id: UUID,
    user: CurrentUser,
    session: DbSession,
    settings: SettingsDep,
    path: str = Query(...),
) -> FileDetailSchema:
    _require_customer_user(user)
    customer = await CustomerService(settings, session).require_for_user(user.id)
    env = await TenantService(session).get_owned_environment(customer.id, environment_id)
    roots = await TenantService(session).roots_for_environment(customer.id, environment_id)
    return await _tenant_files(settings, env, roots).read_file(path)


@router.put(
    "/environments/{environment_id}/files/content",
    response_model=OperationResult,
)
async def write_env_file(
    environment_id: UUID,
    body: CustomerFileWriteRequest,
    user: CurrentUser,
    session: DbSession,
    settings: SettingsDep,
) -> OperationResult:
    _require_customer_user(user)
    customer = await CustomerService(settings, session).require_for_user(user.id)
    env = await TenantService(session).get_owned_environment(customer.id, environment_id)
    await TenantService(session).require_capability(env, "file_manager", label="File manager")
    roots = await TenantService(session).roots_for_environment(customer.id, environment_id)
    return await _tenant_files(settings, env, roots).write_file(body.path, body.content)


@router.post(
    "/environments/{environment_id}/files/mkdir",
    response_model=OperationResult,
)
async def mkdir_env_file(
    environment_id: UUID,
    body: CustomerFileMkdirRequest,
    user: CurrentUser,
    session: DbSession,
    settings: SettingsDep,
) -> OperationResult:
    _require_customer_user(user)
    customer = await CustomerService(settings, session).require_for_user(user.id)
    env = await TenantService(session).get_owned_environment(customer.id, environment_id)
    await TenantService(session).require_capability(env, "file_manager", label="File manager")
    roots = await TenantService(session).roots_for_environment(customer.id, environment_id)
    return await _tenant_files(settings, env, roots).mkdir(body.path)


@router.delete(
    "/environments/{environment_id}/files",
    response_model=OperationResult,
)
async def delete_env_file(
    environment_id: UUID,
    user: CurrentUser,
    session: DbSession,
    settings: SettingsDep,
    path: str = Query(...),
    permanent: bool = Query(default=False),
) -> OperationResult:
    _require_customer_user(user)
    customer = await CustomerService(settings, session).require_for_user(user.id)
    env = await TenantService(session).get_owned_environment(customer.id, environment_id)
    await TenantService(session).require_capability(env, "file_manager", label="File manager")
    roots = await TenantService(session).roots_for_environment(customer.id, environment_id)
    res = await _tenant_files(settings, env, roots).delete(path, permanent=permanent, deleted_by=str(user.id))
    session.add(
        PlatformAuditLog(
            customer_id=customer.id,
            actor_id=user.id,
            action="file_permanently_deleted" if permanent else "file_moved_to_trash",
            target_type="environment_file",
            target_id=str(environment_id),
            result="success" if res.success else "failure",
            metadata_json={"path": path, "permanent": permanent},
        )
    )
    await session.commit()
    return res


@router.get(
    "/environments/{environment_id}/files/trash",
    response_model=CustomerTrashListResponse,
)
async def list_env_trash(
    environment_id: UUID,
    user: CurrentUser,
    session: DbSession,
    settings: SettingsDep,
) -> CustomerTrashListResponse:
    _require_customer_user(user)
    customer = await CustomerService(settings, session).require_for_user(user.id)
    env = await TenantService(session).get_owned_environment(customer.id, environment_id)
    await TenantService(session).require_capability(env, "file_manager", label="File manager")
    roots = await TenantService(session).roots_for_environment(customer.id, environment_id)
    res = await _tenant_files(settings, env, roots).list_trash()
    return CustomerTrashListResponse(
        entries=[
            CustomerTrashEntrySchema(
                trash_id=e.trash_id,
                original_path=e.original_path,
                display_name=e.display_name,
                item_type=e.item_type,
                size_bytes=e.size_bytes,
                deleted_at=e.deleted_at,
                deleted_by=e.deleted_by,
            )
            for e in res.entries
        ],
        total_size_bytes=res.total_size_bytes,
        count=res.count,
    )


@router.post(
    "/environments/{environment_id}/files/trash",
    response_model=OperationResult,
)
async def move_env_trash(
    environment_id: UUID,
    body: CustomerTrashMoveRequest,
    user: CurrentUser,
    session: DbSession,
    settings: SettingsDep,
) -> OperationResult:
    _require_customer_user(user)
    customer = await CustomerService(settings, session).require_for_user(user.id)
    env = await TenantService(session).get_owned_environment(customer.id, environment_id)
    await TenantService(session).require_capability(env, "file_manager", label="File manager")
    roots = await TenantService(session).roots_for_environment(customer.id, environment_id)
    res = await _tenant_files(settings, env, roots).move_to_trash(body.paths, deleted_by=str(user.id))
    session.add(
        PlatformAuditLog(
            customer_id=customer.id,
            actor_id=user.id,
            action="file_moved_to_trash",
            target_type="environment_file",
            target_id=str(environment_id),
            result="success" if res.get("success") else "failure",
            metadata_json={"paths": body.paths, "moved": res.get("moved", 0), "failed": res.get("failed", 0)},
        )
    )
    await session.commit()
    return OperationResult(success=res.get("success", True), message=res.get("message", "Moved to Trash"))


@router.post(
    "/environments/{environment_id}/files/trash/restore",
    response_model=OperationResult,
)
async def restore_env_trash(
    environment_id: UUID,
    body: CustomerTrashRestoreRequest,
    user: CurrentUser,
    session: DbSession,
    settings: SettingsDep,
) -> OperationResult:
    _require_customer_user(user)
    customer = await CustomerService(settings, session).require_for_user(user.id)
    env = await TenantService(session).get_owned_environment(customer.id, environment_id)
    await TenantService(session).require_capability(env, "file_manager", label="File manager")
    roots = await TenantService(session).roots_for_environment(customer.id, environment_id)
    res = await _tenant_files(settings, env, roots).restore_from_trash(
        body.trash_id, conflict_mode=body.conflict_mode
    )
    session.add(
        PlatformAuditLog(
            customer_id=customer.id,
            actor_id=user.id,
            action="file_restored",
            target_type="environment_file",
            target_id=str(environment_id),
            result="success" if res.success else "failure",
            metadata_json={"trash_id": body.trash_id, "conflict_mode": body.conflict_mode},
        )
    )
    await session.commit()
    return res


@router.delete(
    "/environments/{environment_id}/files/trash/{trash_id}",
    response_model=OperationResult,
)
async def delete_env_trash_item(
    environment_id: UUID,
    trash_id: str,
    user: CurrentUser,
    session: DbSession,
    settings: SettingsDep,
) -> OperationResult:
    _require_customer_user(user)
    customer = await CustomerService(settings, session).require_for_user(user.id)
    env = await TenantService(session).get_owned_environment(customer.id, environment_id)
    await TenantService(session).require_capability(env, "file_manager", label="File manager")
    roots = await TenantService(session).roots_for_environment(customer.id, environment_id)
    res = await _tenant_files(settings, env, roots).permanent_delete_trash(trash_id)
    session.add(
        PlatformAuditLog(
            customer_id=customer.id,
            actor_id=user.id,
            action="file_permanently_deleted",
            target_type="environment_file",
            target_id=str(environment_id),
            result="success" if res.success else "failure",
            metadata_json={"trash_id": trash_id},
        )
    )
    await session.commit()
    return res


@router.delete(
    "/environments/{environment_id}/files/trash",
    response_model=OperationResult,
)
async def empty_env_trash(
    environment_id: UUID,
    user: CurrentUser,
    session: DbSession,
    settings: SettingsDep,
) -> OperationResult:
    _require_customer_user(user)
    customer = await CustomerService(settings, session).require_for_user(user.id)
    env = await TenantService(session).get_owned_environment(customer.id, environment_id)
    await TenantService(session).require_capability(env, "file_manager", label="File manager")
    roots = await TenantService(session).roots_for_environment(customer.id, environment_id)
    res = await _tenant_files(settings, env, roots).empty_trash()
    session.add(
        PlatformAuditLog(
            customer_id=customer.id,
            actor_id=user.id,
            action="trash_emptied",
            target_type="environment_file",
            target_id=str(environment_id),
            result="success" if res.success else "failure",
            metadata_json={},
        )
    )
    await session.commit()
    return res


def _tenant_files(settings, env, roots) -> FileManagerService:
    return FileManagerService(
        settings,
        only_roots=roots,
        storage_limit_gb=env.storage_limit_gb,
        owner_uid=getattr(env, "unix_uid", None),
        owner_gid=getattr(env, "unix_gid", None),
    )


@router.post(
    "/environments/{environment_id}/files/move",
    response_model=OperationResult,
)
async def move_env_file(
    environment_id: UUID,
    body: CustomerFileMoveRequest,
    user: CurrentUser,
    session: DbSession,
    settings: SettingsDep,
) -> OperationResult:
    _require_customer_user(user)
    customer = await CustomerService(settings, session).require_for_user(user.id)
    env = await TenantService(session).get_owned_environment(customer.id, environment_id)
    await TenantService(session).require_capability(env, "file_manager", label="File manager")
    roots = await TenantService(session).roots_for_environment(customer.id, environment_id)
    return await _tenant_files(settings, env, roots).move(body.source, body.destination)


@router.post(
    "/environments/{environment_id}/files/copy",
    response_model=OperationResult,
)
async def copy_env_file(
    environment_id: UUID,
    body: CustomerFileCopyRequest,
    user: CurrentUser,
    session: DbSession,
    settings: SettingsDep,
) -> OperationResult:
    _require_customer_user(user)
    customer = await CustomerService(settings, session).require_for_user(user.id)
    env = await TenantService(session).get_owned_environment(customer.id, environment_id)
    await TenantService(session).require_capability(env, "file_manager", label="File manager")
    roots = await TenantService(session).roots_for_environment(customer.id, environment_id)
    return await _tenant_files(settings, env, roots).copy(body.source, body.destination)


@router.post(
    "/environments/{environment_id}/files/chmod",
    response_model=OperationResult,
)
async def chmod_env_file(
    environment_id: UUID,
    body: FileChmodRequest,
    user: CurrentUser,
    session: DbSession,
    settings: SettingsDep,
) -> OperationResult:
    _require_customer_user(user)
    customer = await CustomerService(settings, session).require_for_user(user.id)
    env = await TenantService(session).get_owned_environment(customer.id, environment_id)
    await TenantService(session).require_capability(env, "file_manager", label="File manager")
    roots = await TenantService(session).roots_for_environment(customer.id, environment_id)
    return await _tenant_files(settings, env, roots).chmod(body.path, body.mode)


@router.post(
    "/environments/{environment_id}/files/unzip",
    response_model=OperationResult,
)
async def unzip_env_file(
    environment_id: UUID,
    user: CurrentUser,
    session: DbSession,
    settings: SettingsDep,
    path: str = Query(...),
    extract_here: bool = Query(default=False),
    destination: str | None = Query(default=None),
) -> OperationResult:
    _require_customer_user(user)
    customer = await CustomerService(settings, session).require_for_user(user.id)
    env = await TenantService(session).get_owned_environment(customer.id, environment_id)
    await TenantService(session).require_capability(env, "file_manager", label="File manager")
    roots = await TenantService(session).roots_for_environment(customer.id, environment_id)
    return await _tenant_files(settings, env, roots).unzip(
        path, extract_here=extract_here, destination=destination
    )


@router.post(
    "/environments/{environment_id}/files/extract",
    response_model=OperationResult,
)
async def extract_env_archive(
    environment_id: UUID,
    body: CustomerFileExtractRequest,
    user: CurrentUser,
    session: DbSession,
    settings: SettingsDep,
) -> OperationResult:
    _require_customer_user(user)
    customer = await CustomerService(settings, session).require_for_user(user.id)
    env = await TenantService(session).get_owned_environment(customer.id, environment_id)
    await TenantService(session).require_capability(env, "file_manager", label="File manager")
    roots = await TenantService(session).roots_for_environment(customer.id, environment_id)
    return await _tenant_files(settings, env, roots).unzip(
        body.path, extract_here=body.extract_here, destination=body.destination
    )


@router.post(
    "/environments/{environment_id}/files/compress",
    response_model=OperationResult,
)
async def compress_env_files(
    environment_id: UUID,
    body: CustomerFileCompressRequest,
    user: CurrentUser,
    session: DbSession,
    settings: SettingsDep,
) -> OperationResult:
    _require_customer_user(user)
    customer = await CustomerService(settings, session).require_for_user(user.id)
    env = await TenantService(session).get_owned_environment(customer.id, environment_id)
    await TenantService(session).require_capability(env, "file_manager", label="File manager")
    roots = await TenantService(session).roots_for_environment(customer.id, environment_id)
    return await _tenant_files(settings, env, roots).compress(
        body.paths,
        archive_name=body.archive_name,
        destination_dir=body.destination_dir,
    )


@router.get(
    "/environments/{environment_id}/files/download",
)
async def download_env_file(
    environment_id: UUID,
    user: CurrentUser,
    session: DbSession,
    settings: SettingsDep,
    path: str = Query(...),
):
    from fastapi.responses import FileResponse

    _require_customer_user(user)
    customer = await CustomerService(settings, session).require_for_user(user.id)
    env = await TenantService(session).get_owned_environment(customer.id, environment_id)
    await TenantService(session).require_capability(env, "file_manager", label="File manager")
    roots = await TenantService(session).roots_for_environment(customer.id, environment_id)
    file_path, filename = _tenant_files(settings, env, roots).resolve_download(path)
    return FileResponse(path=file_path, filename=filename, media_type="application/octet-stream")


@router.post(
    "/environments/{environment_id}/files/upload",
    response_model=OperationResult,
)
async def upload_env_file(
    environment_id: UUID,
    user: CurrentUser,
    session: DbSession,
    settings: SettingsDep,
    path: str = Query(default="."),
    file: UploadFile = File(...),
) -> OperationResult:
    """Upload into the environment document root (enforces package storage limit)."""
    _require_customer_user(user)
    customer = await CustomerService(settings, session).require_for_user(user.id)
    env = await TenantService(session).get_owned_environment(customer.id, environment_id)
    await TenantService(session).require_capability(env, "file_manager", label="File manager")
    roots = await TenantService(session).roots_for_environment(customer.id, environment_id)
    return await _tenant_files(settings, env, roots).upload(path, file)


@router.post(
    "/environments/{environment_id}/files/upload/init",
    response_model=FileUploadInitResponse,
)
async def upload_env_init(
    environment_id: UUID,
    body: FileUploadInitRequest,
    user: CurrentUser,
    session: DbSession,
    settings: SettingsDep,
) -> FileUploadInitResponse:
    _require_customer_user(user)
    customer = await CustomerService(settings, session).require_for_user(user.id)
    env = await TenantService(session).get_owned_environment(customer.id, environment_id)
    await TenantService(session).require_capability(env, "file_manager", label="File manager")
    roots = await TenantService(session).roots_for_environment(customer.id, environment_id)
    return await _tenant_files(settings, env, roots).init_chunked_upload(
        body.filename,
        body.path,
        body.size_bytes,
        chunk_size=body.chunk_size,
    )


@router.post(
    "/environments/{environment_id}/files/upload/chunk",
    response_model=OperationResult,
)
async def upload_env_chunk(
    environment_id: UUID,
    user: CurrentUser,
    session: DbSession,
    settings: SettingsDep,
    upload_id: str = Query(...),
    chunk_index: int = Query(..., ge=0),
    file: UploadFile = File(...),
) -> OperationResult:
    _require_customer_user(user)
    customer = await CustomerService(settings, session).require_for_user(user.id)
    env = await TenantService(session).get_owned_environment(customer.id, environment_id)
    await TenantService(session).require_capability(env, "file_manager", label="File manager")
    roots = await TenantService(session).roots_for_environment(customer.id, environment_id)
    data = await file.read()
    return await _tenant_files(settings, env, roots).upload_chunk(upload_id, chunk_index, data)


@router.post(
    "/environments/{environment_id}/files/upload/complete",
    response_model=OperationResult,
)
async def upload_env_complete(
    environment_id: UUID,
    body: FileUploadCompleteRequest,
    user: CurrentUser,
    session: DbSession,
    settings: SettingsDep,
) -> OperationResult:
    _require_customer_user(user)
    customer = await CustomerService(settings, session).require_for_user(user.id)
    env = await TenantService(session).get_owned_environment(customer.id, environment_id)
    await TenantService(session).require_capability(env, "file_manager", label="File manager")
    roots = await TenantService(session).roots_for_environment(customer.id, environment_id)
    return await _tenant_files(settings, env, roots).complete_chunked_upload(body.upload_id)


@router.get(
    "/environments/{environment_id}/database",
    response_model=EnvironmentDatabaseResponse,
)
async def get_env_database(
    environment_id: UUID,
    user: CurrentUser,
    session: DbSession,
    settings: SettingsDep,
    reveal: bool = False,
    db_id: str | None = Query(default=None),
) -> EnvironmentDatabaseResponse:
    _require_customer_user(user)
    customer = await CustomerService(settings, session).require_for_user(user.id)
    env = await TenantService(session).get_owned_environment(customer.id, environment_id)
    from app.services.platform.environment_databases import EnvironmentDatabaseService

    # 1. If explicit db_id or env has no primary db, look up in EnvironmentDatabase table
    if db_id or not (env.db_name and env.db_engine):
        dbs = await EnvironmentDatabaseService(settings, session).list_databases(env, None)
        target = next((d for d in dbs if str(d.id) == db_id), None) if db_id else (dbs[0] if dbs else None)
        if target:
            password = None
            uri = None
            if reveal and target.password_set:
                try:
                    rev = await EnvironmentDatabaseService(settings, session).reveal(env, str(target.id))
                    password = rev.password
                    uri = rev.connection_uri
                except Exception:
                    pass
            return EnvironmentDatabaseResponse(
                environment_id=env.id,
                engine=target.engine,
                name=target.name,
                username=target.username,
                host=_customer_db_host(target.host),
                port=target.port,
                password_set=target.password_set,
                password=password,
                connection_uri=uri,
            )

    password = None
    uri = None
    if reveal and env.db_password_encrypted:
        db = DatabaseManagerService(settings)
        password = db._decrypt(env.db_password_encrypted)
        if env.db_engine and env.db_name:
            uri = db._build_uri(
                engine=env.db_engine,
                name=env.db_name,
                username=env.db_username,
                password=password,
                host=_customer_db_host(env.db_host),
                port=env.db_port,
                path=None,
                mask_password=False,
            )
    return EnvironmentDatabaseResponse(
        environment_id=env.id,
        engine=env.db_engine,
        name=env.db_name,
        username=env.db_username,
        host=_customer_db_host(env.db_host),
        port=env.db_port,
        password_set=bool(env.db_password_encrypted),
        password=password,
        connection_uri=uri,
    )


@router.get(
    "/environments/{environment_id}/databases-v2",
    response_model=list[EnvironmentDatabaseV2Response],
)
@router.get(
    "/environments/{environment_id}/databases",
    response_model=list[EnvironmentDatabaseV2Response],
)
async def list_env_databases_v2(
    environment_id: UUID,
    user: CurrentUser,
    session: DbSession,
    settings: SettingsDep,
) -> list[EnvironmentDatabaseV2Response]:
    """List MySQL/PostgreSQL databases for this environment (legacy row included)."""
    _require_customer_user(user)
    customer = await CustomerService(settings, session).require_for_user(user.id)
    env = await TenantService(session).get_owned_environment(customer.id, environment_id)
    plan = await TenantService(session).require_capability(env, "db_manage", label="Database management")
    from app.services.platform.environment_databases import EnvironmentDatabaseService

    return await EnvironmentDatabaseService(settings, session).list_databases(env, plan)


@router.post(
    "/environments/{environment_id}/databases",
    response_model=EnvironmentDatabaseV2Response,
)
async def create_env_database(
    environment_id: UUID,
    body: EnvironmentDatabaseCreateRequest,
    user: CurrentUser,
    session: DbSession,
    settings: SettingsDep,
) -> EnvironmentDatabaseV2Response:
    _require_customer_user(user)
    customer = await CustomerService(settings, session).require_for_user(user.id)
    env = await TenantService(session).get_owned_environment(customer.id, environment_id)
    plan = await TenantService(session).require_capability(env, "db_manage", label="Database management")
    from app.services.platform.environment_databases import EnvironmentDatabaseService

    return await EnvironmentDatabaseService(settings, session).create(env, plan, body)


@router.post(
    "/environments/{environment_id}/databases/{database_id}/reveal",
    response_model=EnvironmentDatabaseRevealResponse,
)
async def reveal_env_database(
    environment_id: UUID,
    database_id: str,
    user: CurrentUser,
    session: DbSession,
    settings: SettingsDep,
) -> EnvironmentDatabaseRevealResponse:
    _require_customer_user(user)
    customer = await CustomerService(settings, session).require_for_user(user.id)
    env = await TenantService(session).get_owned_environment(customer.id, environment_id)
    await TenantService(session).require_capability(env, "db_manage", label="Database management")
    from app.services.platform.environment_databases import EnvironmentDatabaseService

    return await EnvironmentDatabaseService(settings, session).reveal(env, database_id)


@router.post(
    "/environments/{environment_id}/databases/{database_id}/phpmyadmin",
    response_model=PhpMyAdminOpenResponse,
)
async def open_env_phpmyadmin(
    environment_id: UUID,
    database_id: str,
    user: CurrentUser,
    session: DbSession,
    settings: SettingsDep,
) -> PhpMyAdminOpenResponse:
    """Issue a one-time phpMyAdmin sign-on URL for a MySQL database on this site."""
    _require_customer_user(user)
    customer = await CustomerService(settings, session).require_for_user(user.id)
    env = await TenantService(session).get_owned_environment(customer.id, environment_id)
    await TenantService(session).require_capability(env, "db_manage", label="Database management")
    from app.services.hosting.phpmyadmin import PhpMyAdminService
    from app.services.platform.environment_databases import EnvironmentDatabaseService

    revealed = await EnvironmentDatabaseService(settings, session).reveal(env, database_id)
    PhpMyAdminService.assert_mysql_engine(revealed.engine)
    if not revealed.password:
        raise AppException("No password stored for this database.", code="db_no_password")
    issued = PhpMyAdminService(settings).issue_signon(
        username=revealed.username or "",
        password=revealed.password,
        database=revealed.name,
        host=revealed.host or "localhost",
        port=int(revealed.port or 3306),
    )
    return PhpMyAdminOpenResponse(
        url=issued["url"],
        engine=str(revealed.engine or "mysql"),
        database=revealed.name,
        expires_in=int(issued["expires_in"]),
    )


@router.post(
    "/environments/{environment_id}/database/phpmyadmin",
    response_model=PhpMyAdminOpenResponse,
)
async def open_primary_env_phpmyadmin(
    environment_id: UUID,
    user: CurrentUser,
    session: DbSession,
    settings: SettingsDep,
) -> PhpMyAdminOpenResponse:
    """phpMyAdmin for the site's primary stack database or first available MySQL database."""
    _require_customer_user(user)
    customer = await CustomerService(settings, session).require_for_user(user.id)
    env = await TenantService(session).get_owned_environment(customer.id, environment_id)
    await TenantService(session).require_capability(env, "db_manage", label="Database management")
    from app.services.hosting.phpmyadmin import PhpMyAdminService
    from app.services.platform.environment_databases import EnvironmentDatabaseService

    db_id = str(getattr(env, "db_registry_id", None) or "")
    if not db_id and not (env.db_name and env.db_engine):
        dbs = await EnvironmentDatabaseService(settings, session).list_databases(env, None)
        mysql_dbs = [d for d in dbs if (d.engine or "").lower() in {"mysql", "mariadb"}]
        if not mysql_dbs:
            raise AppException("No MySQL database found on this site. Create one from Databases first.", code="no_database")
        db_id = str(mysql_dbs[0].id)
    elif not db_id:
        db_id = f"legacy:{env.id}"

    revealed = await EnvironmentDatabaseService(settings, session).reveal(env, db_id)
    PhpMyAdminService.assert_mysql_engine(revealed.engine)
    if not revealed.password:
        raise AppException("No password stored for this database.", code="db_no_password")
    issued = PhpMyAdminService(settings).issue_signon(
        username=revealed.username or "",
        password=revealed.password,
        database=revealed.name,
        host=revealed.host or "localhost",
        port=int(revealed.port or 3306),
    )
    return PhpMyAdminOpenResponse(
        url=issued["url"],
        engine=str(revealed.engine or "mysql"),
        database=revealed.name,
        expires_in=int(issued["expires_in"]),
    )


@router.post(
    "/environments/{environment_id}/databases/{database_id}/reset-password",
    response_model=EnvironmentDatabaseRevealResponse,
)
async def reset_env_database_password(
    environment_id: UUID,
    database_id: str,
    user: CurrentUser,
    session: DbSession,
    settings: SettingsDep,
) -> EnvironmentDatabaseRevealResponse:
    _require_customer_user(user)
    customer = await CustomerService(settings, session).require_for_user(user.id)
    env = await TenantService(session).get_owned_environment(customer.id, environment_id)
    plan = await TenantService(session).require_capability(env, "db_manage", label="Database management")
    _require_db_write(plan)
    from app.services.platform.environment_databases import EnvironmentDatabaseService

    return await EnvironmentDatabaseService(settings, session).reset_password(env, database_id)


@router.delete(
    "/environments/{environment_id}/databases/{database_id}",
    response_model=OperationResult,
)
async def delete_env_database(
    environment_id: UUID,
    database_id: str,
    user: CurrentUser,
    session: DbSession,
    settings: SettingsDep,
) -> OperationResult:
    _require_customer_user(user)
    customer = await CustomerService(settings, session).require_for_user(user.id)
    env = await TenantService(session).get_owned_environment(customer.id, environment_id)
    plan = await TenantService(session).require_capability(env, "db_manage", label="Database management")
    _require_db_write(plan)
    from app.services.platform.environment_databases import EnvironmentDatabaseService

    await EnvironmentDatabaseService(settings, session).delete(env, plan, database_id)
    return OperationResult(success=True, message="Database deleted.")


@router.post(
    "/environments/{environment_id}/databases/{database_id}/backup",
)
async def backup_env_database(
    environment_id: UUID,
    database_id: str,
    user: CurrentUser,
    session: DbSession,
    settings: SettingsDep,
) -> dict:
    _require_customer_user(user)
    customer = await CustomerService(settings, session).require_for_user(user.id)
    env = await TenantService(session).get_owned_environment(customer.id, environment_id)
    plan = await TenantService(session).require_capability(env, "db_manage", label="Database management")
    from app.services.platform.environment_databases import EnvironmentDatabaseService

    return await EnvironmentDatabaseService(settings, session).backup(env, plan, database_id)


@router.post(
    "/environments/{environment_id}/databases/{database_id}/import",
    response_model=EnvironmentDatabaseImportResponse,
)
async def import_env_database_sql(
    environment_id: UUID,
    database_id: str,
    body: EnvironmentDatabaseImportRequest,
    user: CurrentUser,
    session: DbSession,
    settings: SettingsDep,
) -> EnvironmentDatabaseImportResponse:
    """Import a .sql file or statements directly into a database."""
    _require_customer_user(user)
    customer = await CustomerService(settings, session).require_for_user(user.id)
    env = await TenantService(session).get_owned_environment(customer.id, environment_id)
    plan = await TenantService(session).require_capability(env, "db_manage", label="Database management")
    from app.services.platform.environment_databases import EnvironmentDatabaseService

    return await EnvironmentDatabaseService(settings, session).import_sql(env, database_id, body.sql)


@router.post(
    "/environments/{environment_id}/database/import",
    response_model=EnvironmentDatabaseImportResponse,
)
async def import_primary_env_database_sql(
    environment_id: UUID,
    body: EnvironmentDatabaseImportRequest,
    user: CurrentUser,
    session: DbSession,
    settings: SettingsDep,
) -> EnvironmentDatabaseImportResponse:
    """Import a .sql file or statements into the primary site database."""
    _require_customer_user(user)
    customer = await CustomerService(settings, session).require_for_user(user.id)
    env = await TenantService(session).get_owned_environment(customer.id, environment_id)
    plan = await TenantService(session).require_capability(env, "db_manage", label="Database management")
    from app.services.platform.environment_databases import EnvironmentDatabaseService

    db_id = str(getattr(env, "db_registry_id", "") or f"legacy-{env.id}")
    return await EnvironmentDatabaseService(settings, session).import_sql(env, db_id, body.sql)


@router.get(
    "/environments/{environment_id}/applications/catalog",
    response_model=list[ApplicationCatalogEntry],
)
async def list_application_catalog(
    environment_id: UUID,
    user: CurrentUser,
    session: DbSession,
    settings: SettingsDep,
) -> list[ApplicationCatalogEntry]:
    _require_customer_user(user)
    customer = await CustomerService(settings, session).require_for_user(user.id)
    tenant = TenantService(session)
    env = await tenant.get_owned_environment(customer.id, environment_id)
    plan = await tenant.plan_for_environment(env)
    from app.services.platform.application_runtime import ApplicationRuntimeService

    rows = ApplicationRuntimeService(settings, session).list_catalog(plan)
    return [ApplicationCatalogEntry.model_validate(r) for r in rows]


@router.get(
    "/environments/{environment_id}/applications",
    response_model=list[ApplicationInstanceResponse],
)
async def list_env_applications(
    environment_id: UUID,
    user: CurrentUser,
    session: DbSession,
    settings: SettingsDep,
) -> list[ApplicationInstanceResponse]:
    _require_customer_user(user)
    customer = await CustomerService(settings, session).require_for_user(user.id)
    env = await TenantService(session).get_owned_environment(customer.id, environment_id)
    from app.services.platform.application_runtime import ApplicationRuntimeService, app_to_response

    apps = await ApplicationRuntimeService(settings, session).list_apps(env)
    return [ApplicationInstanceResponse.model_validate(app_to_response(a)) for a in apps]


@router.post(
    "/environments/{environment_id}/applications",
    response_model=ApplicationInstanceResponse,
)
async def create_env_application(
    environment_id: UUID,
    body: ApplicationInstanceCreateRequest,
    user: CurrentUser,
    session: DbSession,
    settings: SettingsDep,
) -> ApplicationInstanceResponse:
    _require_customer_user(user)
    customer = await CustomerService(settings, session).require_for_user(user.id)
    tenant = TenantService(session)
    env = await tenant.get_owned_environment(customer.id, environment_id)
    plan = await tenant.plan_for_environment(env)
    from app.services.platform.application_runtime import ApplicationRuntimeService, app_to_response

    svc = ApplicationRuntimeService(settings, session)
    item = await svc.create(
        env,
        plan=plan,
        name=body.name,
        framework=body.framework,
        git_url=body.git_url,
        runtime_version=body.runtime_version,
        build_command=body.build_command,
        start_command=body.start_command,
        env_vars=body.env_vars,
    )
    row = ApplicationInstanceResponse.model_validate(app_to_response(item))
    row.message = "Application created. Deploy to start."
    return row


@router.post(
    "/environments/{environment_id}/applications/{application_id}/deploy",
    response_model=ApplicationInstanceResponse,
)
async def deploy_env_application(
    environment_id: UUID,
    application_id: UUID,
    user: CurrentUser,
    session: DbSession,
    settings: SettingsDep,
) -> ApplicationInstanceResponse:
    _require_customer_user(user)
    customer = await CustomerService(settings, session).require_for_user(user.id)
    env = await TenantService(session).get_owned_environment(customer.id, environment_id)
    from app.services.platform.application_runtime import ApplicationRuntimeService, app_to_response

    svc = ApplicationRuntimeService(settings, session)
    item = await svc.deploy(env, application_id)
    row = ApplicationInstanceResponse.model_validate(app_to_response(item))
    row.message = "Deployed."
    return row


@router.post(
    "/environments/{environment_id}/applications/{application_id}/restart",
    response_model=ApplicationInstanceResponse,
)
async def restart_env_application(
    environment_id: UUID,
    application_id: UUID,
    user: CurrentUser,
    session: DbSession,
    settings: SettingsDep,
) -> ApplicationInstanceResponse:
    _require_customer_user(user)
    customer = await CustomerService(settings, session).require_for_user(user.id)
    env = await TenantService(session).get_owned_environment(customer.id, environment_id)
    from app.services.platform.application_runtime import ApplicationRuntimeService, app_to_response

    item = await ApplicationRuntimeService(settings, session).restart(env, application_id)
    row = ApplicationInstanceResponse.model_validate(app_to_response(item))
    row.message = "Restarted."
    return row


@router.delete(
    "/environments/{environment_id}/applications/{application_id}",
    status_code=204,
)
async def delete_env_application(
    environment_id: UUID,
    application_id: UUID,
    user: CurrentUser,
    session: DbSession,
    settings: SettingsDep,
) -> None:
    _require_customer_user(user)
    customer = await CustomerService(settings, session).require_for_user(user.id)
    env = await TenantService(session).get_owned_environment(customer.id, environment_id)
    from app.services.platform.application_runtime import ApplicationRuntimeService

    await ApplicationRuntimeService(settings, session).delete(env, application_id)


async def _resolve_env_db_id(
    session: DbSession,
    env: CustomerEnvironment,
    db_id: str | None = None,
) -> str:
    from app.services.platform.environment_databases import _decode_host_ref

    if db_id:
        try:
            db_uuid = UUID(db_id)
            res = await session.execute(
                select(EnvironmentDatabase).where(
                    EnvironmentDatabase.environment_id == env.id,
                    EnvironmentDatabase.id == db_uuid,
                )
            )
            row = res.scalar_one_or_none()
            if row:
                meta = _decode_host_ref(row.host_ref)
                rid = meta.get("registry_id")
                if rid:
                    return str(rid)
        except (ValueError, TypeError):
            pass
        return str(db_id)

    rid = getattr(env, "db_registry_id", None)
    if rid:
        return str(rid)

    res = await session.execute(
        select(EnvironmentDatabase)
        .where(EnvironmentDatabase.environment_id == env.id)
        .order_by(EnvironmentDatabase.created_at.desc())
    )
    first_db = res.scalars().first()
    if first_db:
        meta = _decode_host_ref(first_db.host_ref)
        rid = meta.get("registry_id")
        if rid:
            return str(rid)
        return str(first_db.id)

    raise AppException(
        "No database on this site yet. Create one in Databases or install WordPress/Laravel from Stack.",
        code="no_database",
    )


def _require_db_write(plan) -> None:
    from app.services.platform.plan_matrix import feature_level

    if feature_level(plan, "db_manage") != "yes":
        raise AppException(
            "This package can browse tables. Changing data needs a higher pack.",
            code="pack_feature",
        )


def _deny_limited_db_writes(plan, sql: str | None) -> None:
    from app.services.platform.plan_matrix import feature_level

    if not sql or not DatabaseStudioService.is_write_sql(sql):
        return
    if feature_level(plan, "db_manage") != "yes":
        raise AppException(
            "This package can browse tables. Changing data needs a higher pack.",
            code="pack_feature",
        )


@router.get(
    "/environments/{environment_id}/database/schema",
    response_model=DbSchemaResponse,
)
async def get_env_database_schema(
    environment_id: UUID,
    user: CurrentUser,
    session: DbSession,
    settings: SettingsDep,
    db_id: str | None = Query(default=None),
) -> DbSchemaResponse:
    _require_customer_user(user)
    customer = await CustomerService(settings, session).require_for_user(user.id)
    env = await TenantService(session).get_owned_environment(customer.id, environment_id)
    await TenantService(session).require_capability(env, "db_manage", label="Database management")
    resolved_id = await _resolve_env_db_id(session, env, db_id)
    return await DatabaseStudioService(DatabaseManagerService(settings)).schema_managed(resolved_id)


@router.get(
    "/environments/{environment_id}/database/rows",
    response_model=DbQueryResponse,
)
async def get_env_database_rows(
    environment_id: UUID,
    user: CurrentUser,
    session: DbSession,
    settings: SettingsDep,
    table: str | None = Query(default=None),
    collection: str | None = Query(default=None),
    schema_name: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db_id: str | None = Query(default=None),
) -> DbQueryResponse:
    _require_customer_user(user)
    customer = await CustomerService(settings, session).require_for_user(user.id)
    env = await TenantService(session).get_owned_environment(customer.id, environment_id)
    await TenantService(session).require_capability(env, "db_manage", label="Database management")
    resolved_id = await _resolve_env_db_id(session, env, db_id)
    body = DbRowsRequest(
        table=table, collection=collection, schema_name=schema_name, limit=limit, offset=offset
    )
    return await DatabaseStudioService(DatabaseManagerService(settings)).rows_managed(resolved_id, body)


@router.post(
    "/environments/{environment_id}/database/rows/insert",
    response_model=DbQueryResponse,
)
async def insert_env_database_row(
    environment_id: UUID,
    body: DbRowMutationRequest,
    user: CurrentUser,
    session: DbSession,
    settings: SettingsDep,
    db_id: str | None = Query(default=None),
) -> DbQueryResponse:
    _require_customer_user(user)
    customer = await CustomerService(settings, session).require_for_user(user.id)
    env = await TenantService(session).get_owned_environment(customer.id, environment_id)
    plan = await TenantService(session).require_capability(env, "db_manage", label="Database management")
    _require_db_write(plan)
    resolved_id = await _resolve_env_db_id(session, env, db_id)
    return await DatabaseStudioService(DatabaseManagerService(settings)).insert_row_managed(
        resolved_id, body
    )


@router.patch(
    "/environments/{environment_id}/database/rows",
    response_model=DbQueryResponse,
)
async def update_env_database_row(
    environment_id: UUID,
    body: DbRowMutationRequest,
    user: CurrentUser,
    session: DbSession,
    settings: SettingsDep,
    db_id: str | None = Query(default=None),
) -> DbQueryResponse:
    _require_customer_user(user)
    customer = await CustomerService(settings, session).require_for_user(user.id)
    env = await TenantService(session).get_owned_environment(customer.id, environment_id)
    plan = await TenantService(session).require_capability(env, "db_manage", label="Database management")
    _require_db_write(plan)
    resolved_id = await _resolve_env_db_id(session, env, db_id)
    return await DatabaseStudioService(DatabaseManagerService(settings)).update_row_managed(
        resolved_id, body
    )


@router.post(
    "/environments/{environment_id}/database/rows/delete",
    response_model=DbQueryResponse,
)
async def delete_env_database_row(
    environment_id: UUID,
    body: DbRowMutationRequest,
    user: CurrentUser,
    session: DbSession,
    settings: SettingsDep,
    db_id: str | None = Query(default=None),
) -> DbQueryResponse:
    _require_customer_user(user)
    customer = await CustomerService(settings, session).require_for_user(user.id)
    env = await TenantService(session).get_owned_environment(customer.id, environment_id)
    plan = await TenantService(session).require_capability(env, "db_manage", label="Database management")
    _require_db_write(plan)
    resolved_id = await _resolve_env_db_id(session, env, db_id)
    return await DatabaseStudioService(DatabaseManagerService(settings)).delete_row_managed(
        resolved_id, body
    )


@router.get(
    "/environments/{environment_id}/ftp",
    response_model=EnvironmentFtpResponse,
)
async def get_env_ftp(
    environment_id: UUID,
    user: CurrentUser,
    session: DbSession,
    settings: SettingsDep,
    reveal: bool = False,
) -> EnvironmentFtpResponse:
    _require_customer_user(user)
    customer = await CustomerService(settings, session).require_for_user(user.id)
    env = await TenantService(session).get_owned_environment(customer.id, environment_id)
    from app.services.platform.ftp import EnvironmentFtpService

    svc = EnvironmentFtpService(settings, session)
    if not env.ftp_username:
        try:
            await svc.ensure_account(env)
        except Exception as exc:  # noqa: BLE001
            return EnvironmentFtpResponse(
                environment_id=env.id,
                enabled=False,
                host=svc._public_host(),
                wordpress_host="localhost",
                port=settings.ftp_port,
                message=str(exc)[:400],
            )
    data = svc.status_payload(env, reveal=reveal)
    return EnvironmentFtpResponse(**data)


@router.post(
    "/environments/{environment_id}/ftp/ensure",
    response_model=EnvironmentFtpResponse,
)
async def ensure_env_ftp(
    environment_id: UUID,
    user: CurrentUser,
    session: DbSession,
    settings: SettingsDep,
    reset_password: bool = False,
) -> EnvironmentFtpResponse:
    _require_customer_user(user)
    customer = await CustomerService(settings, session).require_for_user(user.id)
    env = await TenantService(session).get_owned_environment(customer.id, environment_id)
    await TenantService(session).require_capability(env, "sftp", label="FTP")
    from app.services.platform.ftp import EnvironmentFtpService
    from app.services.platform.fs_ownership import fix_web_ownership

    if env.document_root:
        fix_web_ownership(
            env.document_root,
            user=settings.web_run_user,
            uid=getattr(env, "unix_uid", None),
            gid=getattr(env, "unix_gid", None),
        )
    svc = EnvironmentFtpService(settings, session)
    created = await svc.ensure_account(env, reset_password=reset_password)
    data = svc.status_payload(env, reveal=True)
    data["password"] = created.get("password") or data.get("password")
    data["message"] = "Your FTP login is ready. Copy the details below."
    return EnvironmentFtpResponse(**data)


@router.get(
    "/environments/{environment_id}/sftp",
    response_model=EnvironmentSftpResponse,
)
async def get_env_sftp(
    environment_id: UUID,
    user: CurrentUser,
    session: DbSession,
    settings: SettingsDep,
    reveal: bool = False,
) -> EnvironmentSftpResponse:
    _require_customer_user(user)
    customer = await CustomerService(settings, session).require_for_user(user.id)
    env = await TenantService(session).get_owned_environment(customer.id, environment_id)
    from app.services.platform.sftp_access import EnvironmentSftpService

    svc = EnvironmentSftpService(settings, session)
    allowed = await svc.sftp_allowed(env)
    password = svc.reveal_password(env) if reveal and allowed and env.sftp_enabled else None
    return EnvironmentSftpResponse(**svc.status_payload(env, allowed=allowed, reveal=reveal, password=password))


@router.post(
    "/environments/{environment_id}/sftp/ensure",
    response_model=EnvironmentSftpResponse,
)
async def ensure_env_sftp(
    environment_id: UUID,
    user: CurrentUser,
    session: DbSession,
    settings: SettingsDep,
    reset_password: bool = False,
) -> EnvironmentSftpResponse:
    _require_customer_user(user)
    customer = await CustomerService(settings, session).require_for_user(user.id)
    env = await TenantService(session).get_owned_environment(customer.id, environment_id)
    await TenantService(session).require_capability(env, "sftp", label="SFTP")
    from app.services.platform.sftp_access import EnvironmentSftpService

    svc = EnvironmentSftpService(settings, session)
    data = await svc.ensure_account(env, reset_password=reset_password, actor=f"user:{user.id}")
    data["message"] = "Your SFTP login is ready. File transfer only — no shell."
    return EnvironmentSftpResponse(**data)


@router.post(
    "/environments/{environment_id}/sftp/keys",
    response_model=EnvironmentSftpKeyResponse,
)
async def add_env_sftp_key(
    environment_id: UUID,
    body: EnvironmentSftpKeyCreate,
    user: CurrentUser,
    session: DbSession,
    settings: SettingsDep,
) -> EnvironmentSftpKeyResponse:
    _require_customer_user(user)
    customer = await CustomerService(settings, session).require_for_user(user.id)
    env = await TenantService(session).get_owned_environment(customer.id, environment_id)
    await TenantService(session).require_capability(env, "sftp", label="SFTP")
    from app.services.platform.sftp_access import EnvironmentSftpService

    entry = await EnvironmentSftpService(settings, session).add_key(
        env,
        public_key=body.public_key,
        name=body.name,
        actor=f"user:{user.id}",
    )
    return EnvironmentSftpKeyResponse(**entry)


@router.delete(
    "/environments/{environment_id}/sftp/keys/{key_id}",
    response_model=MessageResponse,
)
async def delete_env_sftp_key(
    environment_id: UUID,
    key_id: str,
    user: CurrentUser,
    session: DbSession,
    settings: SettingsDep,
) -> MessageResponse:
    _require_customer_user(user)
    customer = await CustomerService(settings, session).require_for_user(user.id)
    env = await TenantService(session).get_owned_environment(customer.id, environment_id)
    await TenantService(session).require_capability(env, "sftp", label="SFTP")
    from app.services.platform.sftp_access import EnvironmentSftpService

    await EnvironmentSftpService(settings, session).remove_key(env, key_id, actor=f"user:{user.id}")
    return MessageResponse(message="SSH key removed.")


@router.get(
    "/environments/{environment_id}/ssh",
    response_model=EnvironmentSshResponse,
)
async def get_env_ssh(
    environment_id: UUID,
    user: CurrentUser,
    session: DbSession,
    settings: SettingsDep,
    reveal: bool = False,
) -> EnvironmentSshResponse:
    _require_customer_user(user)
    customer = await CustomerService(settings, session).require_for_user(user.id)
    env = await TenantService(session).get_owned_environment(customer.id, environment_id)
    from app.services.platform.ssh_access import EnvironmentSshService

    ssh = EnvironmentSshService(settings, session)
    allowed = await ssh.ssh_allowed(env)
    password = None
    if reveal and allowed:
        password = ssh.reveal_password(env)
    return EnvironmentSshResponse(**ssh.status_payload(env, allowed=allowed, reveal=reveal, password=password))


@router.get(
    "/environments/{environment_id}/panel-theme",
    response_model=HostingPanelThemeStatusResponse,
)
async def get_env_panel_theme(
    environment_id: UUID,
    user: CurrentUser,
    session: DbSession,
    settings: SettingsDep,
) -> HostingPanelThemeStatusResponse:
    _require_customer_user(user)
    customer = await CustomerService(settings, session).require_for_user(user.id)
    await TenantService(session).get_owned_environment(customer.id, environment_id)
    from app.services.platform.hosting_panel_theme_store import HostingPanelThemeStore

    return HostingPanelThemeStatusResponse.model_validate(
        HostingPanelThemeStore(settings).status_for(environment_id)
    )


@router.put(
    "/environments/{environment_id}/panel-theme",
    response_model=HostingPanelThemeStatusResponse,
)
async def set_env_panel_theme(
    environment_id: UUID,
    body: HostingPanelThemeActivateRequest,
    user: CurrentUser,
    session: DbSession,
    settings: SettingsDep,
) -> HostingPanelThemeStatusResponse:
    _require_customer_user(user)
    customer = await CustomerService(settings, session).require_for_user(user.id)
    await TenantService(session).get_owned_environment(customer.id, environment_id)
    from app.services.platform.hosting_panel_theme_store import HostingPanelThemeStore

    return HostingPanelThemeStatusResponse.model_validate(
        HostingPanelThemeStore(settings).set_active(environment_id, body.theme_id)
    )


@router.post(
    "/environments/{environment_id}/panel-theme/purchase",
    response_model=RenewPaymentResponse,
)
async def purchase_env_panel_theme(
    environment_id: UUID,
    body: HostingPanelThemePurchaseRequest,
    user: CurrentUser,
    session: DbSession,
    settings: SettingsDep,
) -> RenewPaymentResponse:
    _require_customer_user(user)
    customer = await CustomerService(settings, session).require_for_user(user.id)
    await TenantService(session).get_owned_environment(customer.id, environment_id)
    result = await OrderService(settings, session).create_panel_theme_order(
        customer,
        environment_id=environment_id,
        theme_id=body.theme_id,
    )
    order = result.get("order")
    return RenewPaymentResponse(
        reference=result["reference"],
        authorization_url=None,
        demo=False,
        amount=result["amount"],
        currency="GHS",
        invoice_number=getattr(order, "invoice_number", None) or result.get("invoice_number"),
        order_id=getattr(order, "id", None),
        message="Pay ₵2 via Mobile Money, then share the transaction ID on the invoice to unlock this hosting theme.",
    )


@router.get("/environments/{environment_id}/mail", response_model=MailDomainResponse)
async def get_env_mail(
    environment_id: UUID,
    user: CurrentUser,
    session: DbSession,
    settings: SettingsDep,
) -> MailDomainResponse:
    _require_customer_user(user)
    customer = await CustomerService(settings, session).require_for_user(user.id)
    env = await TenantService(session).get_owned_environment(customer.id, environment_id)
    from app.models.platform import HostingPlan, Subscription
    from app.services.platform.environment_mail import EnvironmentMailService

    sub = await session.get(Subscription, env.subscription_id)
    plan = await session.get(HostingPlan, sub.plan_id) if sub else None
    return await EnvironmentMailService(settings, session).get_mail(env, plan)


@router.post(
    "/environments/{environment_id}/mail/mailboxes",
    response_model=MailboxSchema,
)
async def create_env_mailbox(
    environment_id: UUID,
    body: MailboxCreate,
    user: CurrentUser,
    session: DbSession,
    settings: SettingsDep,
) -> MailboxSchema:
    _require_customer_user(user)
    customer = await CustomerService(settings, session).require_for_user(user.id)
    env = await TenantService(session).get_owned_environment(customer.id, environment_id)
    from app.models.platform import HostingPlan, Subscription
    from app.services.platform.environment_mail import EnvironmentMailService

    sub = await session.get(Subscription, env.subscription_id)
    plan = await session.get(HostingPlan, sub.plan_id) if sub else None
    return await EnvironmentMailService(settings, session).create_mailbox(env, plan, body)


@router.patch(
    "/environments/{environment_id}/mail/mailboxes/{mailbox_id}",
    response_model=MailboxSchema,
)
async def update_env_mailbox(
    environment_id: UUID,
    mailbox_id: UUID,
    body: MailboxUpdate,
    user: CurrentUser,
    session: DbSession,
    settings: SettingsDep,
) -> MailboxSchema:
    _require_customer_user(user)
    customer = await CustomerService(settings, session).require_for_user(user.id)
    env = await TenantService(session).get_owned_environment(customer.id, environment_id)
    from app.models.platform import HostingPlan, Subscription
    from app.services.platform.environment_mail import EnvironmentMailService

    sub = await session.get(Subscription, env.subscription_id)
    plan = await session.get(HostingPlan, sub.plan_id) if sub else None
    return await EnvironmentMailService(settings, session).update_mailbox(env, plan, mailbox_id, body)


@router.post(
    "/environments/{environment_id}/mail/mailboxes/{mailbox_id}/reset-password",
    response_model=MailboxSchema,
)
async def reset_env_mailbox_password(
    environment_id: UUID,
    mailbox_id: UUID,
    body: MailboxPasswordReset,
    user: CurrentUser,
    session: DbSession,
    settings: SettingsDep,
) -> MailboxSchema:
    _require_customer_user(user)
    customer = await CustomerService(settings, session).require_for_user(user.id)
    env = await TenantService(session).get_owned_environment(customer.id, environment_id)
    from app.models.platform import HostingPlan, Subscription
    from app.services.platform.environment_mail import EnvironmentMailService

    sub = await session.get(Subscription, env.subscription_id)
    plan = await session.get(HostingPlan, sub.plan_id) if sub else None
    return await EnvironmentMailService(settings, session).reset_password(
        env, plan, mailbox_id, body.password
    )


@router.delete(
    "/environments/{environment_id}/mail/mailboxes/{mailbox_id}",
    response_model=OperationResult,
)
async def delete_env_mailbox(
    environment_id: UUID,
    mailbox_id: UUID,
    user: CurrentUser,
    session: DbSession,
    settings: SettingsDep,
) -> OperationResult:
    _require_customer_user(user)
    customer = await CustomerService(settings, session).require_for_user(user.id)
    env = await TenantService(session).get_owned_environment(customer.id, environment_id)
    from app.models.platform import HostingPlan, Subscription
    from app.services.platform.environment_mail import EnvironmentMailService

    sub = await session.get(Subscription, env.subscription_id)
    plan = await session.get(HostingPlan, sub.plan_id) if sub else None
    await EnvironmentMailService(settings, session).delete_mailbox(env, plan, mailbox_id)
    return OperationResult(success=True, message="Mailbox deleted.")


@router.post(
    "/environments/{environment_id}/mail/aliases",
    response_model=MailAliasSchema,
)
async def create_env_mail_alias(
    environment_id: UUID,
    body: MailAliasCreate,
    user: CurrentUser,
    session: DbSession,
    settings: SettingsDep,
) -> MailAliasSchema:
    _require_customer_user(user)
    customer = await CustomerService(settings, session).require_for_user(user.id)
    env = await TenantService(session).get_owned_environment(customer.id, environment_id)
    from app.models.platform import HostingPlan, Subscription
    from app.services.platform.environment_mail import EnvironmentMailService

    sub = await session.get(Subscription, env.subscription_id)
    plan = await session.get(HostingPlan, sub.plan_id) if sub else None
    return await EnvironmentMailService(settings, session).create_alias(env, plan, body)


@router.patch(
    "/environments/{environment_id}/mail/aliases/{alias_id}",
    response_model=MailAliasSchema,
)
async def update_env_mail_alias(
    environment_id: UUID,
    alias_id: UUID,
    body: MailAliasUpdate,
    user: CurrentUser,
    session: DbSession,
    settings: SettingsDep,
) -> MailAliasSchema:
    _require_customer_user(user)
    customer = await CustomerService(settings, session).require_for_user(user.id)
    env = await TenantService(session).get_owned_environment(customer.id, environment_id)
    from app.models.platform import HostingPlan, Subscription
    from app.services.platform.environment_mail import EnvironmentMailService

    sub = await session.get(Subscription, env.subscription_id)
    plan = await session.get(HostingPlan, sub.plan_id) if sub else None
    return await EnvironmentMailService(settings, session).update_alias(env, plan, alias_id, body)


@router.delete(
    "/environments/{environment_id}/mail/aliases/{alias_id}",
    response_model=OperationResult,
)
async def delete_env_mail_alias(
    environment_id: UUID,
    alias_id: UUID,
    user: CurrentUser,
    session: DbSession,
    settings: SettingsDep,
) -> OperationResult:
    _require_customer_user(user)
    customer = await CustomerService(settings, session).require_for_user(user.id)
    env = await TenantService(session).get_owned_environment(customer.id, environment_id)
    from app.models.platform import HostingPlan, Subscription
    from app.services.platform.environment_mail import EnvironmentMailService

    sub = await session.get(Subscription, env.subscription_id)
    plan = await session.get(HostingPlan, sub.plan_id) if sub else None
    await EnvironmentMailService(settings, session).delete_alias(env, plan, alias_id)
    return OperationResult(success=True, message="Forwarder deleted.")


@router.post(
    "/environments/{environment_id}/ssh/ensure",
    response_model=EnvironmentSshResponse,
)
async def ensure_env_ssh(
    environment_id: UUID,
    user: CurrentUser,
    session: DbSession,
    settings: SettingsDep,
) -> EnvironmentSshResponse:
    _require_customer_user(user)
    customer = await CustomerService(settings, session).require_for_user(user.id)
    env = await TenantService(session).get_owned_environment(customer.id, environment_id)
    from app.services.platform.ssh_access import EnvironmentSshService

    ssh = EnvironmentSshService(settings, session)
    data = await ssh.ensure_access(env)
    if data.get("ssh_allowed"):
        data["message"] = (
            "Jailed SSH is ready on your site Unix login (same password as SFTP). "
            "FTP uses a separate username and password when enabled. "
            "This is not root and not the operator IP."
        )
    return EnvironmentSshResponse(**data)


@router.post(
    "/environments/{environment_id}/filesystem/repair",
    response_model=MessageResponse,
)
async def repair_env_filesystem(
    environment_id: UUID,
    user: CurrentUser,
    session: DbSession,
    settings: SettingsDep,
) -> MessageResponse:
    """Fix site folder permissions so WordPress can install plugins without FTP."""
    _require_customer_user(user)
    customer = await CustomerService(settings, session).require_for_user(user.id)
    env = await TenantService(session).get_owned_environment(customer.id, environment_id)
    from pathlib import Path

    if not env.document_root:
        raise AppException("No site folder yet.")
    from app.services.platform.unix_identity import UnixIdentityService

    unix = UnixIdentityService(settings, session)
    unix.repair_dac(env, dry_run=False, actor=f"user:{user.id}")
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
    return MessageResponse(
        message="Site folder DAC repaired (tenant ownership, no world access).",
    )


@router.post(
    "/environments/{environment_id}/database/query",
    response_model=DbQueryResponse,
)
async def query_env_database(
    environment_id: UUID,
    body: DbQueryRequest,
    user: CurrentUser,
    session: DbSession,
    settings: SettingsDep,
    db_id: str | None = Query(default=None),
) -> DbQueryResponse:
    _require_customer_user(user)
    customer = await CustomerService(settings, session).require_for_user(user.id)
    env = await TenantService(session).get_owned_environment(customer.id, environment_id)
    plan = await TenantService(session).require_capability(env, "db_manage", label="Database management")
    _deny_limited_db_writes(plan, body.sql)
    resolved_id = await _resolve_env_db_id(session, env, db_id)
    return await DatabaseStudioService(DatabaseManagerService(settings)).query_managed(
        resolved_id, body
    )


@router.get(
    "/environments/{environment_id}/monitoring",
    response_model=EnvironmentMonitoringResponse,
)
async def env_monitoring(
    environment_id: UUID,
    user: CurrentUser,
    session: DbSession,
    settings: SettingsDep,
) -> EnvironmentMonitoringResponse:
    """Resource usage snapshot for the hosting panel overview."""
    _require_customer_user(user)
    customer = await CustomerService(settings, session).require_for_user(user.id)
    env = await TenantService(session).get_owned_environment(customer.id, environment_id)
    plan = await TenantService(session).require_capability(env, "monitoring", label="Resource monitoring")
    from app.services.platform.environment_monitoring import EnvironmentMonitoringService

    svc = EnvironmentMonitoringService(settings, session)
    snap = await svc.snapshot(env, plan, full=svc.is_full_monitoring(plan))
    return EnvironmentMonitoringResponse(
        environment_id=env.id,
        domain=env.domain,
        level=str(snap.get("level") or "limited"),
        checked_at=snap.get("checked_at"),
        disk=dict(snap.get("disk") or {}),
        health_status=str(snap.get("health_status") or "unknown"),
        site_status=str(snap.get("site_status") or env.status),
        ssl=dict(snap.get("ssl") or {}),
        backups=dict(snap.get("backups") or {}),
        applications=dict(snap.get("applications") or {}),
        mail=dict(snap.get("mail") or {}),
        processes=dict(snap.get("processes") or {}) if snap.get("processes") else None,
        memory=dict(snap.get("memory") or {}) if snap.get("memory") else None,
        cpu=dict(snap.get("cpu") or {}) if snap.get("cpu") else None,
        databases=dict(snap.get("databases") or {}) if snap.get("databases") else None,
        note=snap.get("note"),
    )


@router.get(
    "/environments/{environment_id}/usage",
    response_model=EnvironmentUsageResponse,
)
async def env_usage(
    environment_id: UUID,
    user: CurrentUser,
    session: DbSession,
    settings: SettingsDep,
) -> EnvironmentUsageResponse:
    _require_customer_user(user)
    customer = await CustomerService(settings, session).require_for_user(user.id)
    tenant = TenantService(session)
    env = await tenant.get_owned_environment(customer.id, environment_id)
    plan = await tenant.plan_for_environment(env)
    from app.services.platform.environment_storage import EnvironmentStorageService

    composite = await EnvironmentStorageService(settings, session).composite_snapshot(env, plan)
    disk = dict(composite.get("disk") or {})

    live: dict = {}
    applied: dict = {}
    slice_limits = None
    app_limits = None
    try:
        from app.services.platform.resource_enforcement import limits_for_plan
        from app.services.platform.systemd_env_slice import EnvironmentSliceService, limits_from_env

        slice_svc = EnvironmentSliceService()
        # Ensure slice exists so usage + enforcement stay aligned (no-op if already applied).
        applied = slice_svc.ensure_slice(env, plan)
        live = slice_svc.read_usage(env)
        slice_limits = limits_from_env(env, plan)
        app_limits = limits_for_plan(plan)
    except Exception:  # noqa: BLE001
        # Slice module may be missing on older hosts — still sample processes.
        from app.services.platform.environment_monitoring import environment_live_stats
        from app.services.platform.resource_enforcement import limits_for_plan

        applied = {}
        slice_limits = None
        try:
            app_limits = limits_for_plan(plan)
        except Exception:  # noqa: BLE001
            app_limits = None
        proc = environment_live_stats(
            unix_username=env.unix_username,
            unix_uid=getattr(env, "unix_uid", None),
            document_root=env.document_root,
            domain=env.domain,
        )
        if proc.get("available"):
            live = {
                "available": True,
                "source": proc.get("source") or "psutil",
                "memory_mb": float(proc.get("memory_rss_mb") or 0),
                "cpu_percent": float(proc.get("cpu_percent") or 0),
                "process_count": int(proc.get("process_count") or 0),
            }

    ram_limit_mb = float(env.ram_limit_gb or 0) * 1024
    mem_mb = live.get("memory_mb")
    # Idle sites are a valid 0 reading once metrics are available.
    if mem_mb is None and live.get("available"):
        mem_mb = 0.0
    mem_pct = None
    if mem_mb is not None and ram_limit_mb > 0:
        mem_pct = round(min(999.0, (float(mem_mb) / ram_limit_mb) * 100), 1)
    cpu_pct = live.get("cpu_percent")
    if cpu_pct is None and live.get("available"):
        cpu_pct = 0.0
    cpu_vcpu = None
    cpu_of_limit_pct = None
    if cpu_pct is not None:
        # psutil CPU% is relative to one core (can exceed 100 with multiple threads).
        cpu_vcpu = round(max(0.0, float(cpu_pct) / 100.0), 3)
        limit_vcpu = float(env.cpu_limit or 0)
        if limit_vcpu > 0:
            cpu_of_limit_pct = round(min(999.0, (cpu_vcpu / limit_vcpu) * 100), 1)

    from datetime import UTC, datetime

    from app.services.platform.resource_status import build_resource_statuses

    resource_statuses = build_resource_statuses(
        env=env,
        plan=plan,
        settings=settings,
        disk=disk,
        os_quota=dict(composite.get("os_quota") or {}),
        live=live,
        slice_applied=applied,
    )

    return EnvironmentUsageResponse(
        environment_id=env.id,
        domain=env.domain,
        cpu_limit=env.cpu_limit,
        ram_limit_gb=env.ram_limit_gb,
        storage_limit_gb=env.storage_limit_gb,
        storage_used_bytes=int(disk.get("storage_used_bytes") or 0),
        storage_used_gb=float(disk.get("storage_used_gb") or 0),
        storage_pct=float(disk.get("storage_pct") or 0),
        file_count=int(disk.get("file_count") or 0),
        isolation_type=env.isolation_type or "filesystem",
        soft_warning=bool(disk.get("soft_warning")),
        high_warning=bool(disk.get("high_warning")),
        critical_warning=bool(disk.get("critical_warning")),
        hard_exceeded=bool(disk.get("hard_exceeded")),
        storage_status=str(disk.get("storage_status") or "ok"),
        storage_tier=str(disk.get("storage_tier") or composite.get("tier") or "ok"),
        components=dict(composite.get("components") or {}),
        os_quota=dict(composite.get("os_quota") or {}),
        host=dict(composite.get("host") or {}),
        cpu_usage_percent=float(cpu_of_limit_pct) if cpu_of_limit_pct is not None else (
            float(cpu_pct) if cpu_pct is not None else None
        ),
        cpu_usage_vcpu=cpu_vcpu,
        memory_usage_mb=float(mem_mb) if mem_mb is not None else None,
        memory_limit_mb=round(ram_limit_mb, 1) if ram_limit_mb else None,
        memory_pct=mem_pct,
        process_count=int(live["process_count"]) if live.get("process_count") is not None else None,
        process_limit=(
            int(slice_limits.tasks_max)
            if slice_limits is not None
            else (int(app_limits.max_processes) if app_limits is not None else None)
        ),
        resources_enforced=bool(resource_statuses.get("resources_enforced")),
        resource_slice=str(applied.get("slice") or live.get("slice") or "") or None,
        metrics_source=str(live.get("source") or "") or None,
        metrics_updated_at=datetime.now(UTC).isoformat(),
        resource_statuses=resource_statuses,
        message=str(composite.get("message") or disk.get("message") or ""),
        note=str(
            composite.get("note")
            or resource_statuses.get("summary")
            or (
                "Live disk is measured under your site folder. CPU/RAM samples come from your "
                "environment resource slice when available."
            )
        ),
    )


@router.post(
    "/environments/{environment_id}/health/check",
    response_model=EnvironmentHealthResponse,
)
async def env_health_check(
    environment_id: UUID,
    user: CurrentUser,
    session: DbSession,
    settings: SettingsDep,
) -> EnvironmentHealthResponse:
    """Run a live health probe for this environment (HTTP, docroot, container)."""
    _require_customer_user(user)
    customer = await CustomerService(settings, session).require_for_user(user.id)
    env = await TenantService(session).get_owned_environment(customer.id, environment_id)
    from app.services.platform.health import EnvironmentHealthService

    result = await EnvironmentHealthService(settings, session).probe(env)
    return EnvironmentHealthResponse(
        environment_id=env.id,
        domain=env.domain,
        status=str(result.get("status") or env.status),
        health_status=str(result.get("health_status") or env.health_status),
        summary=str(result.get("summary") or ""),
        checks=dict(result.get("checks") or {}),
        checked_at=result.get("checked_at"),
        queued=False,
        message="Health check completed.",
    )


@router.get(
    "/environments/{environment_id}/stacks",
    response_model=StackStatusResponse,
)
async def env_stacks(
    environment_id: UUID,
    user: CurrentUser,
    session: DbSession,
    settings: SettingsDep,
) -> StackStatusResponse:
    _require_customer_user(user)
    customer = await CustomerService(settings, session).require_for_user(user.id)
    env = await TenantService(session).get_owned_environment(customer.id, environment_id)
    from app.models.platform import HostingPlan, Subscription
    from app.services.platform.stacks import EnvironmentStackService

    svc = EnvironmentStackService(settings, session)
    sub = await session.get(Subscription, env.subscription_id)
    plan = await session.get(HostingPlan, sub.plan_id) if sub else None
    progress = svc.read_progress(env)
    active_job_id = None
    if progress and progress.get("job_id") and progress.get("status") in {"queued", "running"}:
        try:
            active_job_id = UUID(str(progress["job_id"]))
        except (ValueError, TypeError):
            active_job_id = None
    return StackStatusResponse(
        environment_id=env.id,
        stacks=[StackInfoSchema(**s) for s in svc.list_stacks(plan)],
        current=await svc.reconcile_stack(env),
        progress=progress,
        active_job_id=active_job_id,
    )


@router.get(
    "/environments/{environment_id}/logs",
    response_model=EnvLogsResponse,
)
async def env_logs(
    environment_id: UUID,
    user: CurrentUser,
    session: DbSession,
    settings: SettingsDep,
    lines: int = Query(default=200, ge=20, le=500),
) -> EnvLogsResponse:
    _require_customer_user(user)
    customer = await CustomerService(settings, session).require_for_user(user.id)
    env = await TenantService(session).get_owned_environment(customer.id, environment_id)
    from app.services.platform.env_logs import read_environment_logs

    payload = read_environment_logs(env, lines=lines)
    return EnvLogsResponse(
        environment_id=env.id,
        sources=list(payload.get("sources") or []),
        entries=list(payload.get("entries") or []),
        message=payload.get("message"),
    )


@router.post(
    "/environments/{environment_id}/stacks/install",
    response_model=StackInstallResponse,
)
async def env_install_stack(
    environment_id: UUID,
    body: StackInstallRequest,
    user: CurrentUser,
    session: DbSession,
    settings: SettingsDep,
) -> StackInstallResponse:
    _require_customer_user(user)
    customer = await CustomerService(settings, session).require_for_user(user.id)
    env = await TenantService(session).get_owned_environment(customer.id, environment_id)
    from app.services.platform.stacks import EnvironmentStackService

    svc = EnvironmentStackService(settings, session)
    job, task_id = await svc.queue_install(env, stack=body.stack, replace=body.replace)
    if task_id:
        progress = svc.read_progress(env)
        return StackInstallResponse(
            environment_id=env.id,
            stack=body.stack,
            queued=True,
            job_id=job.id,
            message=f"Installing {body.stack}… follow the live progress below.",
            current=svc.current_stack(env),
            progress=progress,
        )
    # Inline fallback when Redis/worker is down
    result = await svc.install(env, stack=body.stack, replace=body.replace, job=job)
    job.status = "success"
    job.result = result
    return StackInstallResponse(
        environment_id=env.id,
        stack=body.stack,
        queued=False,
        job_id=job.id,
        message=str(result.get("message") or f"{body.stack} installed."),
        result=result,
        current=result,
        progress=svc.read_progress(env),
    )


@router.post(
    "/environments/{environment_id}/stacks/clear",
    response_model=StackClearResponse,
)
async def env_clear_stack(
    environment_id: UUID,
    body: StackClearRequest,
    user: CurrentUser,
    session: DbSession,
    settings: SettingsDep,
) -> StackClearResponse:
    """Clear a broken/unwanted stack install for this environment only."""
    _require_customer_user(user)
    customer = await CustomerService(settings, session).require_for_user(user.id)
    env = await TenantService(session).get_owned_environment(customer.id, environment_id)
    from app.services.platform.stacks import EnvironmentStackService

    svc = EnvironmentStackService(settings, session)
    result = await svc.clear_install(env, drop_database=body.drop_database, actor="customer")
    return StackClearResponse(
        environment_id=env.id,
        message=str(result.get("message") or "Installation cleared."),
        result=result,
        current=svc.current_stack(env),
    )


@router.get(
    "/environments/{environment_id}/stacks/jobs/{job_id}",
    response_model=StackJobStatusResponse,
)
async def env_stack_job_status(
    environment_id: UUID,
    job_id: UUID,
    user: CurrentUser,
    session: DbSession,
    settings: SettingsDep,
) -> StackJobStatusResponse:
    _require_customer_user(user)
    customer = await CustomerService(settings, session).require_for_user(user.id)
    env = await TenantService(session).get_owned_environment(customer.id, environment_id)
    from app.core.exceptions import NotFoundError
    from app.models.platform import PlatformJob
    from app.services.platform.stacks import EnvironmentStackService

    job = await session.get(PlatformJob, job_id)
    if job is None or job.environment_id != env.id or job.customer_id != customer.id:
        raise NotFoundError("Install job not found.")

    svc = EnvironmentStackService(settings, session)
    progress = svc.read_progress(env)
    # Prefer progress file when it matches this job.
    if progress and str(progress.get("job_id") or "") not in {"", str(job.id)}:
        progress = None

    status = job.status
    if progress and progress.get("status") in {"queued", "running", "success", "failed"}:
        # Live file can finish before DB commit is visible; allow upgrade.
        if status in {"pending", "queued", "running"} or (
            progress.get("status") in {"success", "failed"} and status != progress.get("status")
        ):
            if status not in {"success", "failed"} or progress.get("status") == "failed":
                status = str(progress["status"])
            elif progress.get("status") == "success" and status != "failed":
                status = "success"

    stack = None
    if isinstance(job.payload, dict):
        stack = str(job.payload.get("stack") or "") or None
    if progress and progress.get("stack"):
        stack = str(progress.get("stack"))

    error = job.error_info
    if progress and progress.get("error"):
        error = str(progress.get("error"))

    if progress and progress.get("message"):
        message = str(progress.get("message"))
    elif status == "success":
        message = "Stack installed successfully."
    elif status in {"pending", "queued"}:
        message = "Waiting for the installer worker…"
    elif status == "running":
        message = str((progress or {}).get("label") or "Installing…")
    elif status == "failed":
        message = error or "Install failed."
    else:
        message = None

    current = svc.current_stack(env) if status == "success" else None
    return StackJobStatusResponse(
        environment_id=env.id,
        job_id=job.id,
        status=status,
        stack=stack,
        message=message,
        error=error,
        progress=progress,
        current=current,
        result=job.result if isinstance(job.result, dict) else None,
    )


@router.get(
    "/environments/{environment_id}/cron",
    response_model=EnvCronListResponse,
)
async def env_list_cron(
    environment_id: UUID,
    user: CurrentUser,
    session: DbSession,
    settings: SettingsDep,
) -> EnvCronListResponse:
    _require_customer_user(user)
    customer = await CustomerService(settings, session).require_for_user(user.id)
    tenant = TenantService(session)
    env = await tenant.get_owned_environment(customer.id, environment_id)
    plan = await tenant.plan_for_environment(env)
    from app.services.platform.env_cron import EnvironmentCronService

    svc = EnvironmentCronService(settings, session)
    jobs = svc.list_jobs(env)
    ent = svc.entitlements(plan)
    return EnvCronListResponse(
        environment_id=env.id,
        jobs=[EnvCronJobSchema.model_validate(j) for j in jobs],
        max_jobs=ent.max_jobs,
        min_interval_minutes=ent.min_interval_minutes,
        jobs_used=len(jobs),
        runs_as=env.unix_username,
        note=(
            f"Up to {ent.max_jobs} job(s); minimum interval {ent.min_interval_minutes} minutes. "
            f"Commands run as {env.unix_username or 'your hosting user'} in your site folder."
        ),
    )


@router.post(
    "/environments/{environment_id}/cron",
    response_model=EnvCronJobSchema,
)
async def env_create_cron(
    environment_id: UUID,
    body: EnvCronCreateRequest,
    user: CurrentUser,
    session: DbSession,
    settings: SettingsDep,
) -> EnvCronJobSchema:
    _require_customer_user(user)
    customer = await CustomerService(settings, session).require_for_user(user.id)
    tenant = TenantService(session)
    env = await tenant.get_owned_environment(customer.id, environment_id)
    plan = await tenant.require_capability(env, "cron", label="Cron jobs")
    from app.services.platform.env_cron import EnvironmentCronService

    job = EnvironmentCronService(settings, session).add_job(
        env,
        schedule=body.schedule,
        command=body.command,
        enabled=body.enabled,
        plan=plan,
    )
    return EnvCronJobSchema.model_validate(job)


@router.patch(
    "/environments/{environment_id}/cron/{job_id}",
    response_model=EnvCronJobSchema,
)
async def env_update_cron(
    environment_id: UUID,
    job_id: str,
    body: EnvCronUpdateRequest,
    user: CurrentUser,
    session: DbSession,
    settings: SettingsDep,
) -> EnvCronJobSchema:
    _require_customer_user(user)
    customer = await CustomerService(settings, session).require_for_user(user.id)
    tenant = TenantService(session)
    env = await tenant.get_owned_environment(customer.id, environment_id)
    plan = await tenant.require_capability(env, "cron", label="Cron jobs")
    from app.services.platform.env_cron import EnvironmentCronService

    job = EnvironmentCronService(settings, session).update_job(
        env,
        job_id,
        schedule=body.schedule,
        command=body.command,
        enabled=body.enabled,
        plan=plan,
    )
    return EnvCronJobSchema.model_validate(job)


@router.delete(
    "/environments/{environment_id}/cron/{job_id}",
    response_model=MessageResponse,
)
async def env_delete_cron(
    environment_id: UUID,
    job_id: str,
    user: CurrentUser,
    session: DbSession,
    settings: SettingsDep,
) -> MessageResponse:
    _require_customer_user(user)
    customer = await CustomerService(settings, session).require_for_user(user.id)
    env = await TenantService(session).get_owned_environment(customer.id, environment_id)
    from app.services.platform.env_cron import EnvironmentCronService

    EnvironmentCronService(settings, session).delete_job(env, job_id)
    return MessageResponse(message="Cron job deleted.")


@router.post(
    "/environments/{environment_id}/cron/{job_id}/run",
    response_model=EnvCronJobSchema,
)
async def env_run_cron(
    environment_id: UUID,
    job_id: str,
    user: CurrentUser,
    session: DbSession,
    settings: SettingsDep,
) -> EnvCronJobSchema:
    _require_customer_user(user)
    customer = await CustomerService(settings, session).require_for_user(user.id)
    env = await TenantService(session).get_owned_environment(customer.id, environment_id)
    from app.services.platform.env_cron import EnvironmentCronService

    job = EnvironmentCronService(settings, session).run_job(env, job_id)
    return EnvCronJobSchema.model_validate(job)


@router.get(
    "/environments/{environment_id}/dns",
    response_model=EnvironmentDnsResponse,
)
async def env_dns(
    environment_id: UUID,
    user: CurrentUser,
    session: DbSession,
    settings: SettingsDep,
) -> EnvironmentDnsResponse:
    _require_customer_user(user)
    customer = await CustomerService(settings, session).require_for_user(user.id)
    env = await TenantService(session).get_owned_environment(customer.id, environment_id)
    from app.services.platform.dns import EnvironmentDnsService

    payload = await EnvironmentDnsService(settings, session).status_payload(env)
    return EnvironmentDnsResponse.model_validate(payload)


@router.post(
    "/environments/{environment_id}/dns/ensure-a",
    response_model=EnvironmentDnsResponse,
)
async def env_dns_ensure_a(
    environment_id: UUID,
    user: CurrentUser,
    session: DbSession,
    settings: SettingsDep,
) -> EnvironmentDnsResponse:
    """Publish the site on IFNOTUS nameservers or push A records when Namecheap DNS is used."""
    _require_customer_user(user)
    customer = await CustomerService(settings, session).require_for_user(user.id)
    env = await TenantService(session).get_owned_environment(customer.id, environment_id)
    from app.services.platform.dns import EnvironmentDnsService

    svc = EnvironmentDnsService(settings, session)
    result = await svc.ensure_a(env)
    if not result.get("ok") and not result.get("local"):
        raise AppException(str(result.get("message") or "DNS ensure failed."))
    payload = await svc.status_payload(env)
    nc = result.get("namecheap") or {}
    response = EnvironmentDnsResponse.model_validate(payload)
    response.namecheap_pushed = bool(nc.get("ok") or nc.get("pushed"))
    response.message = str(result.get("message") or response.message)
    return response


@router.get("/environments/{environment_id}/redirects")
async def env_list_redirects(
    environment_id: UUID,
    user: CurrentUser,
    session: DbSession,
    settings: SettingsDep,
) -> list[dict]:
    _require_customer_user(user)
    customer = await CustomerService(settings, session).require_for_user(user.id)
    env = await TenantService(session).get_owned_environment(customer.id, environment_id)
    from app.services.hosting.domains import DomainService
    from app.services.platform.dns import EnvironmentDnsService

    await EnvironmentDnsService(settings, session).ensure_hosting_domain_for_mail(env)
    await session.refresh(env)
    rows = await DomainService(settings, session).list_redirects(env.hosting_domain_id)
    return [r.model_dump() for r in rows]


@router.post("/environments/{environment_id}/redirects")
async def env_create_redirect(
    environment_id: UUID,
    body: EnvironmentRedirectCreateRequest,
    user: CurrentUser,
    session: DbSession,
    settings: SettingsDep,
) -> dict:
    _require_customer_user(user)
    customer = await CustomerService(settings, session).require_for_user(user.id)
    env = await TenantService(session).get_owned_environment(customer.id, environment_id)
    from app.core.exceptions import ValidationError
    from app.models.platform import HostingPlan, Subscription
    from app.schemas.hosting import DomainRedirectCreate
    from app.services.hosting.domains import DomainService
    from app.services.platform.dns import EnvironmentDnsService
    from app.services.platform.plan_matrix import feature_included, pack_denied_message

    sub = await session.get(Subscription, env.subscription_id)
    plan = await session.get(HostingPlan, sub.plan_id) if sub else None
    if not feature_included(plan, "redirects"):
        raise ValidationError(pack_denied_message("Redirects"))

    await EnvironmentDnsService(settings, session).ensure_hosting_domain_for_mail(env)
    await session.refresh(env)
    row = await DomainService(settings, session).create_redirect(
        env.hosting_domain_id,
        DomainRedirectCreate(
            source_path=body.source_path,
            target_url=body.target_url,
            status_code=body.status_code,
        ),
    )
    return row.model_dump()


@router.delete("/environments/{environment_id}/redirects/{redirect_id}")
async def env_delete_redirect(
    environment_id: UUID,
    redirect_id: UUID,
    user: CurrentUser,
    session: DbSession,
    settings: SettingsDep,
) -> MessageResponse:
    _require_customer_user(user)
    customer = await CustomerService(settings, session).require_for_user(user.id)
    env = await TenantService(session).get_owned_environment(customer.id, environment_id)
    from app.services.hosting.domains import DomainService

    if not env.hosting_domain_id:
        raise AppException("No domain on this site yet.")
    await DomainService(settings, session).delete_redirect(env.hosting_domain_id, redirect_id)
    return MessageResponse(message="Redirect removed.")


@router.get("/environments/{environment_id}/zone")
async def env_zone_records(
    environment_id: UUID,
    user: CurrentUser,
    session: DbSession,
    settings: SettingsDep,
) -> dict:
    """Zone Editor analogue — DNS records for this site’s domain (no VPS IP values)."""
    _require_customer_user(user)
    customer = await CustomerService(settings, session).require_for_user(user.id)
    env = await TenantService(session).get_owned_environment(customer.id, environment_id)
    from app.services.hosting.domains import DomainService
    from app.services.platform.dns import EnvironmentDnsService

    dns = EnvironmentDnsService(settings, session)
    await dns.ensure_hosting_domain_for_mail(env)
    await session.refresh(env)
    included = dns.is_included_hostname(env.domain)
    records = await DomainService(settings, session).list_dns_records(env.hosting_domain_id)
    # Never leak A values that look like the operator IP in the customer panel.
    public_ip = (settings.server_public_ip or "").strip()
    safe = []
    for r in records:
        d = r.model_dump()
        if d.get("record_type") in {"A", "AAAA"} and public_ip and d.get("value") == public_ip:
            d["value"] = "(IFNOTUS hosting)"
        safe.append(d)
    return {
        "domain": env.domain,
        "included_hostname": included,
        "editable": not included,
        "nameservers": dns.nameservers(),
        "records": safe,
        "message": (
            "DNS for this free hostname is managed for you."
            if included
            else "Add records while this domain uses IFNOTUS nameservers."
        ),
    }


@router.post("/environments/{environment_id}/zone")
async def env_zone_add(
    environment_id: UUID,
    body: EnvironmentDnsRecordCreateRequest,
    user: CurrentUser,
    session: DbSession,
    settings: SettingsDep,
) -> dict:
    _require_customer_user(user)
    customer = await CustomerService(settings, session).require_for_user(user.id)
    env = await TenantService(session).get_owned_environment(customer.id, environment_id)
    from app.schemas.hosting import DomainDnsRecordCreate
    from app.services.hosting.domains import DomainService
    from app.services.platform.dns import EnvironmentDnsService

    dns = EnvironmentDnsService(settings, session)
    await dns.ensure_hosting_domain_for_mail(env)
    await session.refresh(env)
    if dns.is_included_hostname(env.domain):
        raise AppException("DNS for this free hostname is managed for you.")
    # Block customers from pasting the Contabo IP into public DNS copy in our panel stores;
    # A records for custom domains are published via authoritative DNS without showing IP in UI.
    value = body.value.strip()
    if body.record_type in {"A", "AAAA"} and value == (settings.server_public_ip or ""):
        value = settings.server_public_ip or value
    row = await DomainService(settings, session).create_dns_record(
        env.hosting_domain_id,
        DomainDnsRecordCreate(
            record_type=body.record_type,
            host=body.host,
            value=value,
            ttl=body.ttl,
            priority=body.priority,
        ),
    )
    return row.model_dump()


@router.get("/environments/{environment_id}/git")
async def env_git_status(
    environment_id: UUID,
    user: CurrentUser,
    session: DbSession,
    settings: SettingsDep,
) -> dict:
    _require_customer_user(user)
    customer = await CustomerService(settings, session).require_for_user(user.id)
    env = await TenantService(session).get_owned_environment(customer.id, environment_id)
    from app.services.platform.env_git import EnvironmentGitService

    return await EnvironmentGitService(settings, session).status(env)


@router.post("/environments/{environment_id}/git/clone")
async def env_git_clone(
    environment_id: UUID,
    body: EnvironmentGitCloneRequest,
    user: CurrentUser,
    session: DbSession,
    settings: SettingsDep,
) -> dict:
    _require_customer_user(user)
    customer = await CustomerService(settings, session).require_for_user(user.id)
    env = await TenantService(session).get_owned_environment(customer.id, environment_id)
    from app.services.platform.env_git import EnvironmentGitService

    return await EnvironmentGitService(settings, session).clone(
        env, repo_url=body.repo_url, branch=body.branch
    )


@router.post("/environments/{environment_id}/git/pull")
async def env_git_pull(
    environment_id: UUID,
    user: CurrentUser,
    session: DbSession,
    settings: SettingsDep,
) -> dict:
    _require_customer_user(user)
    customer = await CustomerService(settings, session).require_for_user(user.id)
    env = await TenantService(session).get_owned_environment(customer.id, environment_id)
    from app.services.platform.env_git import EnvironmentGitService

    return await EnvironmentGitService(settings, session).pull(env)


@router.post(
    "/environments/{environment_id}/domains/custom",
    response_model=EnvironmentDnsResponse,
)
async def env_attach_custom_domain(
    environment_id: UUID,
    body: AttachCustomDomainRequest,
    user: CurrentUser,
    session: DbSession,
    settings: SettingsDep,
) -> EnvironmentDnsResponse:
    """Add a professional domain the traditional way (addon on this site) or assign one you already own."""
    _require_customer_user(user)
    customer = await CustomerService(settings, session).require_for_user(user.id)
    env = await TenantService(session).get_owned_environment(customer.id, environment_id)
    from app.services.platform.dns import EnvironmentDnsService

    svc = EnvironmentDnsService(settings, session)
    result = await svc.attach_custom_domain(env, body.domain_name)
    payload = await svc.status_payload(env)
    response = EnvironmentDnsResponse.model_validate(payload)
    response.message = str(result.get("message") or response.message)
    response.namecheap_pushed = bool((result.get("registrar_ns") or {}).get("ok"))
    return response


@router.post(
    "/environments/{environment_id}/domains/unassign",
    response_model=EnvironmentDnsResponse,
)
async def env_unassign_custom_domain(
    environment_id: UUID,
    body: UnassignCustomDomainRequest,
    user: CurrentUser,
    session: DbSession,
    settings: SettingsDep,
) -> EnvironmentDnsResponse:
    """Remove a professional domain from this site without deleting the registration."""
    _require_customer_user(user)
    customer = await CustomerService(settings, session).require_for_user(user.id)
    env = await TenantService(session).get_owned_environment(customer.id, environment_id)
    from app.services.platform.dns import EnvironmentDnsService

    svc = EnvironmentDnsService(settings, session)
    result = await svc.unassign_custom_domain(env, body.domain_name)
    payload = await svc.status_payload(env)
    response = EnvironmentDnsResponse.model_validate(payload)
    response.message = str(result.get("message") or response.message)
    return response


@router.get(
    "/environments/{environment_id}/domain-items",
    response_model=EnvironmentDomainListResponse,
)
async def env_list_domain_items(
    environment_id: UUID,
    user: CurrentUser,
    session: DbSession,
    settings: SettingsDep,
) -> EnvironmentDomainListResponse:
    """List domains, subdomains, and addon domains attached to this hosting environment."""
    _require_customer_user(user)
    customer = await CustomerService(settings, session).require_for_user(user.id)
    env = await TenantService(session).get_owned_environment(customer.id, environment_id)

    from pathlib import Path
    from sqlalchemy import func
    from app.models.hosting import Domain
    from app.models.platform import CustomerDomain, Subscription, HostingPlan

    primary_name = (env.domain or "").strip().lower()
    unix_username = (env.unix_username or env.hosting_name or "").strip().lower()
    if not unix_username and env.domain:
        unix_username = env.domain.split(".")[0].replace("-", "").lower()[:8]
    if not unix_username:
        unix_username = "user"
    home_dir = f"/home3/{unix_username}"

    # Plan checks
    plan = None
    if env.subscription_id:
        sub = await session.get(Subscription, env.subscription_id)
        if sub and sub.plan_id:
            plan = await session.get(HostingPlan, sub.plan_id)

    custom_domains_limit = None
    if plan and isinstance(plan.features, dict) and "custom_domains" in plan.features:
        try:
            custom_domains_limit = int(plan.features["custom_domains"])
        except (ValueError, TypeError):
            pass
    package_supported = custom_domains_limit != 0

    items: list[EnvironmentDomainEntry] = []

    # 1. Primary domain entry
    primary_doc_root = "/public_html"
    primary_redirect = None
    primary_force_https = True
    primary_ssl = bool(env.ssl_status == "active" or env.ssl_expiry)
    primary_created = env.created_at

    if env.hosting_domain_id:
        h_dom = await session.get(Domain, env.hosting_domain_id)
        if h_dom:
            primary_redirect = h_dom.redirect_url
            primary_force_https = h_dom.force_https
    elif primary_name:
        h_dom = (
            await session.execute(
                select(Domain).where(func.lower(Domain.name) == primary_name)
            )
        ).scalar_one_or_none()
        if h_dom:
            primary_redirect = h_dom.redirect_url
            primary_force_https = h_dom.force_https

    items.append(
        EnvironmentDomainEntry(
            id=str(env.hosting_domain_id or env.id),
            domain_name=primary_name,
            domain_type="primary",
            document_root=primary_doc_root,
            full_document_root=f"{home_dir}{primary_doc_root}",
            redirects_to=primary_redirect,
            force_https=primary_force_https,
            is_primary=True,
            ssl_active=primary_ssl,
            can_delete=False,
            created_at=primary_created,
        )
    )

    # 2. Addon and Subdomain entries from CustomerDomain and Domain tables
    cd_res = await session.execute(
        select(CustomerDomain).where(
            CustomerDomain.customer_id == customer.id,
            CustomerDomain.environment_id == env.id,
        ).order_by(CustomerDomain.created_at.desc())
    )
    seen_names = {primary_name}
    custom_count = 0

    for cd in cd_res.scalars().all():
        cd_name = (cd.domain_name or "").strip().lower()
        if not cd_name or cd_name in seen_names:
            continue
        seen_names.add(cd_name)
        custom_count += 1

        d_row = (
            await session.execute(
                select(Domain).where(func.lower(Domain.name) == cd_name)
            )
        ).scalar_one_or_none()

        d_root = "/public_html"
        d_redirect = None
        d_force = True
        if d_row:
            d_redirect = d_row.redirect_url
            d_force = d_row.force_https
            if d_row.document_root:
                raw_p = Path(d_row.document_root)
                if raw_p.name in {"public", "public_html", "web"} and raw_p.parent.name == cd_name:
                    d_root = f"/{cd_name}/{raw_p.name}"
                elif raw_p.name == "public_html":
                    d_root = "/public_html"
                elif raw_p.is_absolute():
                    d_root = f"/{raw_p.name}"
                else:
                    d_root = f"/{d_row.document_root.lstrip('/')}"
        else:
            d_root = f"/{cd_name}"

        is_sub = cd_name.endswith(f".{primary_name}")
        items.append(
            EnvironmentDomainEntry(
                id=str(cd.id),
                domain_name=cd_name,
                domain_type="subdomain" if is_sub else "addon",
                document_root=d_root,
                full_document_root=f"{home_dir}{d_root}",
                redirects_to=d_redirect,
                force_https=d_force,
                is_primary=False,
                ssl_active=bool(cd.ssl_status == "active" or cd.ssl_expiry),
                can_delete=True,
                created_at=cd.created_at,
            )
        )

    # 3. Check child Domain rows in Domain table
    if env.hosting_domain_id:
        child_res = await session.execute(
            select(Domain).where(Domain.parent_domain_id == env.hosting_domain_id)
        )
        for child in child_res.scalars().all():
            c_name = (child.name or "").strip().lower()
            if not c_name or c_name in seen_names:
                continue
            seen_names.add(c_name)
            custom_count += 1

            c_root = f"/{c_name}"
            if child.document_root:
                raw_p = Path(child.document_root)
                if raw_p.name in {"public", "public_html", "web"} and raw_p.parent.name == c_name:
                    c_root = f"/{c_name}/{raw_p.name}"
                elif raw_p.name == "public_html":
                    c_root = "/public_html"
                elif raw_p.is_absolute():
                    c_root = f"/{raw_p.name}"
                else:
                    c_root = f"/{child.document_root.lstrip('/')}"

            is_sub = c_name.endswith(f".{primary_name}")
            items.append(
                EnvironmentDomainEntry(
                    id=str(child.id),
                    domain_name=c_name,
                    domain_type="subdomain" if is_sub else "addon",
                    document_root=c_root,
                    full_document_root=f"{home_dir}{c_root}",
                    redirects_to=child.redirect_url,
                    force_https=child.force_https,
                    is_primary=False,
                    ssl_active=False,
                    can_delete=True,
                    created_at=child.created_at,
                )
            )

    return EnvironmentDomainListResponse(
        primary_domain=primary_name,
        unix_username=unix_username,
        home_dir=home_dir,
        default_doc_root=primary_doc_root,
        package_supported=package_supported,
        custom_domains_limit=custom_domains_limit,
        custom_domains_count=custom_count,
        items=items,
    )


@router.post(
    "/environments/{environment_id}/domain-items",
    response_model=EnvironmentDomainEntry,
)
async def env_create_domain_item(
    environment_id: UUID,
    body: CreateEnvironmentDomainRequest,
    user: CurrentUser,
    session: DbSession,
    settings: SettingsDep,
) -> EnvironmentDomainEntry:
    """Create a new registered/addon domain or subdomain with a customized document root."""
    _require_customer_user(user)
    customer = await CustomerService(settings, session).require_for_user(user.id)
    env = await TenantService(session).get_owned_environment(customer.id, environment_id)

    from pathlib import Path
    from sqlalchemy import func
    from app.models.hosting import Domain
    from app.models.platform import CustomerDomain, Subscription, HostingPlan
    from app.services.hosting.nginx_provisioner import DomainNginxProvisioner
    from app.services.platform.tenant import ensure_cpanel_directory_layout

    # Check plan limit
    if env.subscription_id:
        sub = await session.get(Subscription, env.subscription_id)
        if sub and sub.plan_id:
            plan = await session.get(HostingPlan, sub.plan_id)
            if plan and isinstance(plan.features, dict) and "custom_domains" in plan.features:
                try:
                    limit = int(plan.features["custom_domains"])
                    if limit == 0:
                        raise AppException(
                            "Your current package does not support adding additional domains or subdomains. Please upgrade your plan.",
                            code="plan_unsupported",
                        )
                    current_count = (
                        await session.execute(
                            select(func.count(CustomerDomain.id)).where(
                                CustomerDomain.customer_id == customer.id,
                                CustomerDomain.environment_id == env.id,
                            )
                        )
                    ).scalar() or 0
                    if current_count >= limit:
                        raise AppException(
                            f"Your package limit of {limit} domain(s) has been reached. Please upgrade to add more domains.",
                            code="plan_limit_reached",
                        )
                except (ValueError, TypeError):
                    pass

    clean_name = body.domain_name.strip().lower()
    if clean_name.startswith("http://"):
        clean_name = clean_name[7:]
    if clean_name.startswith("https://"):
        clean_name = clean_name[8:]
    clean_name = clean_name.strip("/")

    if not clean_name or len(clean_name) < 3:
        raise AppException("Invalid domain name.", code="invalid_domain")

    # Document root resolution
    primary_name = (env.domain or "").strip().lower()
    unix_username = (env.unix_username or env.hosting_name or "user").strip().lower()
    home_dir = f"/home3/{unix_username}"

    if not env.document_root:
        raise AppException("Environment has no root path.", code="no_docroot")
    raw_env_root = Path(env.document_root).resolve()
    site_home = raw_env_root.parent if raw_env_root.name in {"public", "public_html", "web"} else raw_env_root

    if body.share_document_root:
        target_doc_root = site_home / "public_html"
        display_doc_root = "/public_html"
    else:
        req_root = (body.document_root or clean_name).strip().lstrip("/")
        if not req_root:
            req_root = clean_name
        target_doc_root = site_home / req_root
        display_doc_root = f"/{req_root}"

    target_doc_root.mkdir(parents=True, exist_ok=True)
    try:
        target_doc_root.chmod(0o755)
    except OSError:
        pass

    # Ensure cpanel layout update
    ensure_cpanel_directory_layout(site_home, web_dir=site_home / "public_html", hostname=primary_name, subdomains=[clean_name])

    # Save to CustomerDomain
    cd_row = (
        await session.execute(
            select(CustomerDomain).where(func.lower(CustomerDomain.domain_name) == clean_name)
        )
    ).scalar_one_or_none()
    if cd_row is None:
        cd_row = CustomerDomain(
            customer_id=customer.id,
            environment_id=env.id,
            domain_name=clean_name,
            status="active",
        )
        session.add(cd_row)
    else:
        cd_row.customer_id = customer.id
        cd_row.environment_id = env.id
        cd_row.status = "active"

    # Save to Domain
    is_sub = clean_name.endswith(f".{primary_name}")
    dom_row = (
        await session.execute(
            select(Domain).where(func.lower(Domain.name) == clean_name)
        )
    ).scalar_one_or_none()
    if dom_row is None:
        dom_row = Domain(
            name=clean_name,
            domain_type="subdomain" if is_sub else "addon",
            parent_domain_id=env.hosting_domain_id,
            document_root=str(target_doc_root),
            force_https=body.force_https,
            enabled=True,
        )
        session.add(dom_row)
    else:
        dom_row.parent_domain_id = env.hosting_domain_id
        dom_row.document_root = str(target_doc_root)
        dom_row.force_https = body.force_https
        dom_row.enabled = True

    await session.commit()
    await session.refresh(cd_row)
    await session.refresh(dom_row)

    # Provision Nginx vhost safely
    try:
        prov = DomainNginxProvisioner(settings)
        await prov.provision(
            hostname=clean_name,
            document_root=str(target_doc_root),
            force_https=body.force_https,
            enabled=True,
            create_docroot=True,
            unix_user=env.unix_username or env.hosting_name,
        )
    except Exception:
        pass

    return EnvironmentDomainEntry(
        id=str(cd_row.id),
        domain_name=clean_name,
        domain_type="subdomain" if is_sub else "addon",
        document_root=display_doc_root,
        full_document_root=f"{home_dir}{display_doc_root}",
        redirects_to=None,
        force_https=body.force_https,
        is_primary=False,
        ssl_active=False,
        can_delete=True,
        created_at=cd_row.created_at,
    )


@router.patch(
    "/environments/{environment_id}/domain-items/{domain_id}",
    response_model=EnvironmentDomainEntry,
)
async def env_update_domain_item(
    environment_id: UUID,
    domain_id: str,
    body: UpdateEnvironmentDomainRequest,
    user: CurrentUser,
    session: DbSession,
    settings: SettingsDep,
) -> EnvironmentDomainEntry:
    """Update document root, force HTTPS, or redirection for a domain."""
    _require_customer_user(user)
    env = await _resolve_env_for_user(session, settings, user, environment_id)

    from pathlib import Path
    from sqlalchemy import func
    from app.models.hosting import Domain
    from app.models.platform import CustomerDomain
    from app.services.hosting.nginx_provisioner import DomainNginxProvisioner

    primary_name = (env.domain or "").strip().lower()
    unix_username = (env.unix_username or env.hosting_name or "user").strip().lower()
    home_dir = f"/home3/{unix_username}"

    raw_env_root = Path(env.document_root or ".").resolve()
    site_home = raw_env_root.parent if raw_env_root.name in {"public", "public_html", "web"} else raw_env_root

    # Find the domain entry
    cd_row = None
    try:
        cd_uuid = UUID(domain_id)
        cd_row = await session.get(CustomerDomain, cd_uuid)
    except (ValueError, TypeError):
        pass

    dom_name = None
    if cd_row:
        dom_name = cd_row.domain_name
    elif domain_id == str(env.hosting_domain_id) or domain_id == str(env.id):
        dom_name = primary_name
    else:
        dom_name = domain_id

    dom_name = (dom_name or "").strip().lower()
    dom_row = (
        await session.execute(
            select(Domain).where(func.lower(Domain.name) == dom_name)
        )
    ).scalar_one_or_none()

    if dom_row is None and dom_name == primary_name and env.hosting_domain_id:
        dom_row = await session.get(Domain, env.hosting_domain_id)

    display_root = "/public_html"
    if body.document_root is not None:
        req_root = body.document_root.strip().lstrip("/")
        if not req_root:
            req_root = "public_html"
        new_dir = site_home / req_root
        new_dir.mkdir(parents=True, exist_ok=True)
        display_root = f"/{req_root}"
        if dom_row:
            dom_row.document_root = str(new_dir)
    elif dom_row and dom_row.document_root:
        raw_p = Path(dom_row.document_root)
        display_root = f"/{raw_p.name}" if raw_p.is_absolute() else f"/{dom_row.document_root.lstrip('/')}"

    if body.force_https is not None and dom_row:
        dom_row.force_https = body.force_https

    if body.redirects_to is not None and dom_row:
        dom_row.redirect_url = body.redirects_to.strip() if body.redirects_to.strip() else None

    await session.commit()

    # Re-apply Nginx
    if dom_row and dom_row.name:
        try:
            prov = DomainNginxProvisioner(settings)
            await prov.provision(
                hostname=dom_row.name,
                document_root=dom_row.document_root,
                force_https=dom_row.force_https,
                redirect_url=dom_row.redirect_url,
                enabled=True,
                unix_user=env.unix_username or env.hosting_name,
            )
        except Exception:
            pass

    is_primary = dom_name == primary_name
    return EnvironmentDomainEntry(
        id=domain_id,
        domain_name=dom_name,
        domain_type="primary" if is_primary else ("subdomain" if dom_name.endswith(f".{primary_name}") else "addon"),
        document_root=display_root,
        full_document_root=f"{home_dir}{display_root}",
        redirects_to=dom_row.redirect_url if dom_row else None,
        force_https=dom_row.force_https if dom_row else True,
        is_primary=is_primary,
        ssl_active=bool(cd_row.ssl_status == "active" if cd_row else (env.ssl_status == "active")),
        can_delete=not is_primary,
        created_at=cd_row.created_at if cd_row else env.created_at,
    )


@router.delete(
    "/environments/{environment_id}/domain-items/{domain_id}",
    response_model=MessageResponse,
)
async def env_delete_domain_item(
    environment_id: UUID,
    domain_id: str,
    user: CurrentUser,
    session: DbSession,
    settings: SettingsDep,
) -> MessageResponse:
    """Remove a domain or subdomain from this hosting account (preserves files on disk)."""
    _require_customer_user(user)
    env = await _resolve_env_for_user(session, settings, user, environment_id)

    from sqlalchemy import func
    from app.models.hosting import Domain
    from app.models.platform import CustomerDomain
    from app.services.hosting.nginx_provisioner import DomainNginxProvisioner

    primary_name = (env.domain or "").strip().lower()

    cd_row = None
    try:
        cd_uuid = UUID(domain_id)
        cd_row = await session.get(CustomerDomain, cd_uuid)
    except (ValueError, TypeError):
        pass

    target_name = None
    if cd_row:
        if cd_row.environment_id != env.id:
            raise AuthorizationError("Domain does not belong to this environment.")
        target_name = cd_row.domain_name
    else:
        target_name = domain_id

    target_name = (target_name or "").strip().lower()
    if target_name == primary_name:
        raise AppException("Cannot delete the primary domain of this hosting service.", code="primary_domain_protected")

    if cd_row:
        await session.delete(cd_row)

    dom_row = (
        await session.execute(
            select(Domain).where(func.lower(Domain.name) == target_name)
        )
    ).scalar_one_or_none()
    if dom_row:
        await session.delete(dom_row)

    await session.commit()

    # Remove Nginx vhost
    try:
        prov = DomainNginxProvisioner(settings)
        await prov.remove(target_name)
    except Exception:
        pass

    return MessageResponse(message=f"Domain '{target_name}' was removed from your account.")


@router.get(
    "/environments/{environment_id}/ssl",
    response_model=EnvironmentSslResponse,
)
async def env_ssl_status(
    environment_id: UUID,
    user: CurrentUser,
    session: DbSession,
    settings: SettingsDep,
) -> EnvironmentSslResponse:
    """List SSL status for an environment — prefer live certificate notAfter when present."""
    _require_customer_user(user)
    customer = await CustomerService(settings, session).require_for_user(user.id)
    env = await TenantService(session).get_owned_environment(customer.id, environment_id)
    if not env.domain:
        raise AppException("Environment has no domain.")

    from pathlib import Path

    from app.services.applications.readers.ssl import SSLReader

    expiry = env.ssl_expiry
    expiry_source: str | None = "estimate" if expiry else None
    ssl_status = (getattr(env, "ssl_status", None) or "").strip().lower() or None
    message = "No certificate on file yet."
    success = False

    cert_path = Path(f"/etc/letsencrypt/live/{env.domain}/fullchain.pem")
    reader = SSLReader(getattr(settings, "letsencrypt_live_dir", "/etc/letsencrypt/live"))
    cert = await reader.read(
        str(cert_path) if cert_path.exists() else None,
        env.domain,
    )
    if cert.configured and getattr(cert, "valid_until", None):
        expiry = cert.valid_until
        expiry_source = "certificate"
        success = True
        ssl_status = "active"
        message = cert.message or "Certificate loaded from disk."
        env.ssl_expiry = expiry
    elif cert.configured:
        success = True
        message = cert.message or "Certificate present."
        ssl_status = ssl_status or "active"
        if expiry:
            expiry_source = expiry_source or "estimate"
    elif expiry:
        success = True
        message = "Using stored expiry estimate (certificate not readable)."
        expiry_source = "estimate"
        ssl_status = ssl_status or "active"

    return EnvironmentSslResponse(
        environment_id=env.id,
        domain=env.domain,
        success=success,
        queued=False,
        job_id=None,
        message=message,
        ssl_expiry=expiry,
        ssl_status=ssl_status,
        expiry_source=expiry_source,
    )


@router.post(
    "/environments/{environment_id}/ssl/issue",
    response_model=EnvironmentSslResponse,
)
async def env_ssl_issue(
    environment_id: UUID,
    user: CurrentUser,
    session: DbSession,
    settings: SettingsDep,
) -> EnvironmentSslResponse:
    """Queue Let's Encrypt issuance (falls back to inline if Redis enqueue fails)."""
    _require_customer_user(user)
    customer = await CustomerService(settings, session).require_for_user(user.id)
    env = await TenantService(session).get_owned_environment(customer.id, environment_id)
    if not env.domain:
        raise AppException("Environment has no domain.")

    from app.services.platform.dns import EnvironmentSslJobService

    job, task_id = await EnvironmentSslJobService(settings, session).queue_issue_ssl(env)
    if task_id:
        return EnvironmentSslResponse(
            environment_id=env.id,
            domain=env.domain,
            success=True,
            queued=True,
            job_id=job.id,
            message="SSL issue job queued. Certificate will appear after DNS points to this server.",
            ssl_expiry=env.ssl_expiry,
        )

    # Fallback: run inline when worker queue is unavailable
    from app.schemas.hosting import SslActionRequest
    from app.services.hosting.ssl import SslService

    result = await SslService(settings, session).issue(
        SslActionRequest(domain=env.domain, webroot=env.document_root, dry_run=False)
    )
    if result.success:
        env.health_status = "healthy"
        job.status = "success"
        job.result = {"success": True, "message": result.message, "inline": True}
    else:
        job.status = "failed"
        job.error_info = result.message
    return EnvironmentSslResponse(
        environment_id=env.id,
        domain=env.domain,
        success=bool(result.success),
        queued=False,
        job_id=job.id,
        message=result.message,
        ssl_expiry=env.ssl_expiry,
    )


@router.post("/environments/{environment_id}/suspend", response_model=EnvironmentResponse)
async def suspend_environment(
    environment_id: UUID,
    user: CurrentUser,
    session: DbSession,
    settings: SettingsDep,
) -> EnvironmentResponse:
    _require_customer_user(user)
    customer = await CustomerService(settings, session).require_for_user(user.id)
    from app.services.platform.lifecycle import EnvironmentLifecycleService

    env = await EnvironmentLifecycleService(settings, session).suspend(customer.id, environment_id)
    return _env_response(env)


@router.post("/environments/{environment_id}/restore", response_model=EnvironmentResponse)
async def restore_environment(
    environment_id: UUID,
    user: CurrentUser,
    session: DbSession,
    settings: SettingsDep,
) -> EnvironmentResponse:
    _require_customer_user(user)
    customer = await CustomerService(settings, session).require_for_user(user.id)
    from app.services.platform.lifecycle import EnvironmentLifecycleService

    env = await EnvironmentLifecycleService(settings, session).restore(customer.id, environment_id)
    return _env_response(env)


@router.post("/environments/{environment_id}/terminate", response_model=EnvironmentResponse)
async def terminate_environment(
    environment_id: UUID,
    user: CurrentUser,
    session: DbSession,
    settings: SettingsDep,
) -> EnvironmentResponse:
    _require_customer_user(user)
    await CustomerService(settings, session).require_for_user(user.id)
    raise AuthorizationError(
        "Ask IFNOTUS support to close a site. This cannot be undone from the customer panel."
    )


@router.post(
    "/environments/{environment_id}/backups",
    response_model=EnvironmentBackupResponse,
)
async def create_backup(
    environment_id: UUID,
    user: CurrentUser,
    session: DbSession,
    settings: SettingsDep,
) -> EnvironmentBackupResponse:
    _require_customer_user(user)
    customer = await CustomerService(settings, session).require_for_user(user.id)
    from app.services.platform.lifecycle import EnvironmentLifecycleService

    row = await EnvironmentLifecycleService(settings, session).create_backup(
        customer.id, environment_id
    )
    return EnvironmentBackupResponse.model_validate(row)


@router.get(
    "/environments/{environment_id}/backups",
    response_model=list[EnvironmentBackupResponse],
)
async def list_backups(
    environment_id: UUID,
    user: CurrentUser,
    session: DbSession,
    settings: SettingsDep,
) -> list[EnvironmentBackupResponse]:
    _require_customer_user(user)
    customer = await CustomerService(settings, session).require_for_user(user.id)
    from app.services.platform.lifecycle import EnvironmentLifecycleService

    rows = await EnvironmentLifecycleService(settings, session).list_backups(
        customer.id, environment_id
    )
    return [EnvironmentBackupResponse.model_validate(r) for r in rows]


@router.delete(
    "/environments/{environment_id}/backups/{backup_id}",
    status_code=204,
)
async def delete_backup(
    environment_id: UUID,
    backup_id: UUID,
    user: CurrentUser,
    session: DbSession,
    settings: SettingsDep,
) -> None:
    _require_customer_user(user)
    customer = await CustomerService(settings, session).require_for_user(user.id)
    from app.services.platform.backups import EnvironmentBackupService

    await EnvironmentBackupService(settings, session).delete_backup(
        customer.id, environment_id, backup_id
    )


@router.post(
    "/environments/{environment_id}/backups/{backup_id}/restore",
    response_model=EnvironmentBackupRestoreResponse,
)
async def restore_backup(
    environment_id: UUID,
    backup_id: UUID,
    user: CurrentUser,
    session: DbSession,
    settings: SettingsDep,
) -> EnvironmentBackupRestoreResponse:
    """Restore files (+ DB if present) from a successful backup archive."""
    _require_customer_user(user)
    customer = await CustomerService(settings, session).require_for_user(user.id)
    from app.services.platform.backups import EnvironmentBackupService

    job = await EnvironmentBackupService(settings, session).queue_restore(
        customer.id, environment_id, backup_id
    )
    return EnvironmentBackupRestoreResponse(
        job_id=job.id,
        backup_id=backup_id,
        environment_id=environment_id,
        status=job.status,
        message=(
            "Restore job queued."
            if job.status in {"queued", "pending"}
            else "Restore completed."
            if job.status == "success"
            else f"Restore status: {job.status}"
        ),
    )


@router.get("/credits", response_model=AiCreditAccountResponse)
async def get_credits(
    user: CurrentUser,
    session: DbSession,
    settings: SettingsDep,
) -> AiCreditAccountResponse:
    _require_customer_user(user)
    customer = await CustomerService(settings, session).require_for_user(user.id)
    account = await AiCreditService(session).get_account(customer.id)
    from app.services.platform.credits import TOKENS_PER_CREDIT, tokens_from_credits

    return AiCreditAccountResponse(
        customer_id=account.customer_id,
        credits_remaining=account.credits_remaining,
        total_allocated=account.total_allocated,
        lifetime_used=account.lifetime_used,
        tokens_remaining=tokens_from_credits(account.credits_remaining),
        tokens_per_credit=TOKENS_PER_CREDIT,
    )


@router.post("/ai/operations", response_model=AiOperationResponse)
async def start_ai_operation(
    body: AiOperationRequest,
    user: CurrentUser,
    session: DbSession,
    settings: SettingsDep,
) -> AiOperationResponse:
    _require_customer_user(user)
    customer = await CustomerService(settings, session).require_for_user(user.id)
    if body.environment_id is not None:
        await TenantService(session).get_owned_environment(
            customer.id, body.environment_id, allow_suspended=False
        )
    require_confirm = body.permission_level >= 3
    risk = body.risk_classification
    if body.permission_level == 4:
        risk = "critical"
    elif body.permission_level == 3:
        risk = "high"
    op = await AiCreditService(session).start_operation(
        customer_id=customer.id,
        environment_id=body.environment_id,
        operation_type=body.operation_type,
        permission_level=body.permission_level,
        request=body.request,
        risk=risk,
        require_confirm=require_confirm,
    )
    # Levels 1–2: mark complete with stub result (full agent wiring uses existing /ai)
    if not require_confirm:
        op = await AiCreditService(session).complete_operation(
            customer.id,
            op.id,
            success=True,
            result="Accepted. Use IFNOTUS AI chat for live troubleshooting within your environment.",
        )
    return AiOperationResponse.model_validate(op)


@router.post("/ai/operations/{operation_id}/confirm", response_model=AiOperationResponse)
async def confirm_ai_operation(
    operation_id: UUID,
    user: CurrentUser,
    session: DbSession,
    settings: SettingsDep,
) -> AiOperationResponse:
    _require_customer_user(user)
    customer = await CustomerService(settings, session).require_for_user(user.id)
    op = await AiCreditService(session).confirm_operation(customer.id, operation_id)
    op = await AiCreditService(session).complete_operation(
        customer.id,
        op.id,
        success=True,
        result="Confirmed and recorded. Apply the change via IFNOTUS AI propose/apply tools.",
    )
    return AiOperationResponse.model_validate(op)


@router.post("/ai/operations/{operation_id}/complete", response_model=AiOperationResponse)
async def complete_ai_operation(
    operation_id: UUID,
    body: AiOperationCompleteRequest,
    user: CurrentUser,
    session: DbSession,
    settings: SettingsDep,
) -> AiOperationResponse:
    _require_customer_user(user)
    customer = await CustomerService(settings, session).require_for_user(user.id)
    op = await AiCreditService(session).complete_operation(
        customer.id, operation_id, success=body.success, result=body.result
    )
    return AiOperationResponse.model_validate(op)


@router.get("/ai/operations", response_model=list[AiOperationResponse])
async def list_ai_operations(
    user: CurrentUser,
    session: DbSession,
    settings: SettingsDep,
) -> list[AiOperationResponse]:
    _require_customer_user(user)
    customer = await CustomerService(settings, session).require_for_user(user.id)
    ops = await AiCreditService(session).list_operations(customer.id)
    return [AiOperationResponse.model_validate(o) for o in ops]


@router.get("/environments/{environment_id}/ai/status")
async def env_ai_status(
    environment_id: UUID,
    user: CurrentUser,
    session: DbSession,
    settings: SettingsDep,
) -> dict:
    """Dev Companion availability + credit balance for this environment."""
    _require_customer_user(user)
    customer = await CustomerService(settings, session).require_for_user(user.id)
    await TenantService(session).get_owned_environment(customer.id, environment_id)
    from app.services.ai.settings_store import AiSettingsStore
    from app.services.platform.credits import TOKENS_PER_CREDIT, tokens_from_credits

    store = AiSettingsStore(settings)
    credits = await AiCreditService(session).get_account(customer.id)
    status = store.status()
    return {
        "configured": status.configured,
        "model": status.model,
        "base_url": status.base_url,
        "api_key_masked": status.api_key_masked,
        "credits_remaining": credits.credits_remaining,
        "tokens_remaining": tokens_from_credits(credits.credits_remaining),
        "tokens_per_credit": TOKENS_PER_CREDIT,
        "total_allocated": credits.total_allocated,
        "lifetime_used": credits.lifetime_used,
        "environment_id": str(environment_id),
        "scope": "customer_environment",
    }


def _customer_ai_memory(settings: SettingsDep, customer_id: UUID, environment_id: UUID):
    from pathlib import Path

    from app.services.ai.memory import AiMemoryStore

    root = Path(settings.ai_memory_path).resolve() / "customers" / str(customer_id) / str(environment_id)
    return AiMemoryStore(settings, root=root)


@router.get(
    "/environments/{environment_id}/ai/sessions",
    response_model=AiSessionListResponse,
)
async def list_env_ai_sessions(
    environment_id: UUID,
    user: CurrentUser,
    session: DbSession,
    settings: SettingsDep,
    surface: str | None = Query(default="portal"),
    path: str | None = Query(default=None),
) -> AiSessionListResponse:
    _require_customer_user(user)
    customer = await CustomerService(settings, session).require_for_user(user.id)
    await TenantService(session).get_owned_environment(customer.id, environment_id)
    mem = _customer_ai_memory(settings, customer.id, environment_id)
    rows = mem.list_sessions(surface=surface, path=path)
    return AiSessionListResponse(sessions=[AiSessionSummary(**r) for r in rows])


@router.post(
    "/environments/{environment_id}/ai/sessions",
    response_model=AiSessionDetail,
)
async def create_env_ai_session(
    environment_id: UUID,
    body: AiSessionCreateRequest,
    user: CurrentUser,
    session: DbSession,
    settings: SettingsDep,
) -> AiSessionDetail:
    _require_customer_user(user)
    customer = await CustomerService(settings, session).require_for_user(user.id)
    await TenantService(session).get_owned_environment(customer.id, environment_id)
    mem = _customer_ai_memory(settings, customer.id, environment_id)
    created = mem.create_session(
        surface=body.surface or "portal",
        title=body.title,
        path=body.path,
        app_id=body.app_id,
        root_id=body.root_id,
    )
    return AiSessionDetail(**created)


@router.get(
    "/environments/{environment_id}/ai/sessions/{session_id}",
    response_model=AiSessionDetail,
)
async def get_env_ai_session(
    environment_id: UUID,
    session_id: str,
    user: CurrentUser,
    session: DbSession,
    settings: SettingsDep,
) -> AiSessionDetail:
    _require_customer_user(user)
    customer = await CustomerService(settings, session).require_for_user(user.id)
    await TenantService(session).get_owned_environment(customer.id, environment_id)
    mem = _customer_ai_memory(settings, customer.id, environment_id)
    row = mem.get_session(session_id)
    if not row:
        raise NotFoundError("Conversation not found.")
    return AiSessionDetail(**row)


@router.delete(
    "/environments/{environment_id}/ai/sessions/{session_id}",
    response_model=OperationResult,
)
async def delete_env_ai_session(
    environment_id: UUID,
    session_id: str,
    user: CurrentUser,
    session: DbSession,
    settings: SettingsDep,
) -> OperationResult:
    _require_customer_user(user)
    customer = await CustomerService(settings, session).require_for_user(user.id)
    await TenantService(session).get_owned_environment(customer.id, environment_id)
    mem = _customer_ai_memory(settings, customer.id, environment_id)
    ok = mem.delete_session(session_id)
    return OperationResult(
        success=ok,
        message="Conversation deleted." if ok else "Conversation not found.",
    )


@router.delete(
    "/environments/{environment_id}/ai/sessions",
    response_model=OperationResult,
)
async def clear_env_ai_sessions(
    environment_id: UUID,
    user: CurrentUser,
    session: DbSession,
    settings: SettingsDep,
    surface: str | None = Query(default="portal"),
) -> OperationResult:
    _require_customer_user(user)
    customer = await CustomerService(settings, session).require_for_user(user.id)
    await TenantService(session).get_owned_environment(customer.id, environment_id)
    mem = _customer_ai_memory(settings, customer.id, environment_id)
    removed = mem.clear_sessions(surface=surface)
    return OperationResult(success=True, message=f"Deleted {removed} conversation(s).")


@router.post("/environments/{environment_id}/ai/chat", response_model=AiChatResponse)
async def env_ai_chat(
    environment_id: UUID,
    body: AiChatRequest,
    user: CurrentUser,
    session: DbSession,
    settings: SettingsDep,
) -> AiChatResponse:
    _require_customer_user(user)
    customer = await CustomerService(settings, session).require_for_user(user.id)
    tenant = TenantService(session)
    env = await tenant.get_owned_environment(customer.id, environment_id, allow_suspended=False)
    await tenant.require_capability(env, "ai", label="AI engineer")
    roots = await tenant.roots_for_environment(customer.id, environment_id)
    credits = AiCreditService(session)
    op = await credits.start_operation(
        customer_id=customer.id,
        environment_id=env.id,
        operation_type="chat",
        permission_level=1,
        request=body.message[:2000],
        risk="low",
        cost=1,
    )
    from app.services.platform.customer_ai import build_customer_agent
    from app.schemas.ai import AiUsageStats

    agent = build_customer_agent(
        settings, session, customer_id=customer.id, env=env, roots=roots
    )
    # Force portal surface so staff terminal tools stay irrelevant
    body = body.model_copy(update={"surface": "portal"})
    try:
        result = await agent.chat(user, body)
        usage = result.usage
        _op, _account, stats = await credits.settle_chat_usage(
            customer.id,
            op.id,
            prompt_tokens=int(usage.prompt_tokens if usage else 0),
            completion_tokens=int(usage.completion_tokens if usage else 0),
            success=True,
            result=(result.reply or "")[:2000],
        )
        return result.model_copy(
            update={
                "usage": AiUsageStats(
                    prompt_tokens=stats["prompt_tokens"],
                    completion_tokens=stats["completion_tokens"],
                    total_tokens=stats["total_tokens"],
                    weighted_tokens=stats["weighted_tokens"],
                    credits_charged=stats["credits_charged"],
                    credits_remaining=stats["credits_remaining"],
                    tokens_remaining=stats["tokens_remaining"],
                    tokens_per_credit=stats["tokens_per_credit"],
                )
            }
        )
    except Exception as exc:
        await credits.settle_chat_usage(
            customer.id,
            op.id,
            prompt_tokens=0,
            completion_tokens=0,
            success=False,
            result=str(exc)[:2000],
        )
        raise


@router.post("/environments/{environment_id}/ai/chat/stream")
async def env_ai_chat_stream(
    environment_id: UUID,
    body: AiChatRequest,
    user: CurrentUser,
    session: DbSession,
    settings: SettingsDep,
):
    _require_customer_user(user)
    customer = await CustomerService(settings, session).require_for_user(user.id)
    tenant = TenantService(session)
    env = await tenant.get_owned_environment(customer.id, environment_id, allow_suspended=False)
    await tenant.require_capability(env, "ai", label="AI engineer")
    roots = await tenant.roots_for_environment(customer.id, environment_id)
    credits = AiCreditService(session)
    op = await credits.start_operation(
        customer_id=customer.id,
        environment_id=env.id,
        operation_type="chat",
        permission_level=1,
        request=body.message[:2000],
        risk="low",
        cost=1,
    )
    from app.services.platform.customer_ai import build_customer_agent

    agent = build_customer_agent(
        settings, session, customer_id=customer.id, env=env, roots=roots
    )
    body = body.model_copy(update={"surface": "portal"})

    async def events():
        success = False
        settled = False
        last_reply = ""
        prompt_tokens = 0
        completion_tokens = 0
        try:
            async for event in agent.chat_stream(user, body):
                if event.get("type") == "delta" and event.get("text"):
                    last_reply += str(event.get("text") or "")
                if event.get("type") == "done":
                    success = bool(event.get("configured", True))
                    usage = event.get("usage") or {}
                    prompt_tokens = int(usage.get("prompt_tokens") or 0)
                    completion_tokens = int(usage.get("completion_tokens") or 0)
                    _op, _account, stats = await credits.settle_chat_usage(
                        customer.id,
                        op.id,
                        prompt_tokens=prompt_tokens,
                        completion_tokens=completion_tokens,
                        success=success,
                        result=last_reply[:2000] or ("ok" if success else "failed"),
                    )
                    settled = True
                    event = {
                        **event,
                        "usage": stats,
                        "credits_remaining": stats["credits_remaining"],
                        "tokens_remaining": stats["tokens_remaining"],
                        "credits_charged": stats["credits_charged"],
                    }
                yield event
        except Exception as exc:  # noqa: BLE001
            yield {"type": "error", "message": str(exc)}
            last_reply = str(exc)
        finally:
            if not settled:
                try:
                    _op, _account, stats = await credits.settle_chat_usage(
                        customer.id,
                        op.id,
                        prompt_tokens=prompt_tokens,
                        completion_tokens=completion_tokens,
                        success=False,
                        result=last_reply[:2000] or "failed",
                    )
                    yield {
                        "type": "done",
                        "configured": True,
                        "pending_actions": [],
                        "tool_traces": [],
                        "usage": stats,
                        "credits_remaining": stats["credits_remaining"],
                        "tokens_remaining": stats["tokens_remaining"],
                        "credits_charged": 0,
                    }
                except Exception:  # noqa: BLE001
                    pass

    async def gen():
        import json as _json

        try:
            async for event in events():
                yield f"data: {_json.dumps(event, default=str)}\n\n"
            yield "data: [DONE]\n\n"
        except Exception as exc:  # noqa: BLE001
            yield f"data: {_json.dumps({'type': 'error', 'message': str(exc)})}\n\n"
            yield "data: [DONE]\n\n"

    from fastapi.responses import StreamingResponse

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/environments/{environment_id}/ai/actions/apply", response_model=OperationResult)
async def env_ai_apply(
    environment_id: UUID,
    body: AiApplyActionRequest,
    user: CurrentUser,
    session: DbSession,
    settings: SettingsDep,
) -> OperationResult:
    _require_customer_user(user)
    customer = await CustomerService(settings, session).require_for_user(user.id)
    tenant = TenantService(session)
    env = await tenant.get_owned_environment(customer.id, environment_id, allow_suspended=False)
    await tenant.require_capability(env, "ai", label="AI engineer")
    plan = await tenant.plan_for_environment(env)
    from app.services.platform.plan_matrix import feature_included, ssh_allowed

    roots = await tenant.roots_for_environment(customer.id, environment_id)
    from app.services.platform.customer_ai import build_customer_agent

    agent = build_customer_agent(
        settings, session, customer_id=customer.id, env=env, roots=roots
    )
    return await agent.apply_action(
        user,
        body,
        can_write_files=feature_included(plan, "file_manager"),
        can_execute_terminal=ssh_allowed(plan) or feature_included(plan, "ai_server"),
        can_manage_databases=feature_included(plan, "db_manage") and bool(env.db_registry_id),
    )


@router.post("/environments/{environment_id}/ai/actions/apply/stream")
async def env_ai_apply_stream(
    environment_id: UUID,
    body: AiApplyActionRequest,
    user: CurrentUser,
    session: DbSession,
    settings: SettingsDep,
):
    _require_customer_user(user)
    customer = await CustomerService(settings, session).require_for_user(user.id)
    tenant = TenantService(session)
    env = await tenant.get_owned_environment(customer.id, environment_id, allow_suspended=False)
    await tenant.require_capability(env, "ai", label="AI engineer")
    plan = await tenant.plan_for_environment(env)
    from app.services.platform.plan_matrix import feature_included, ssh_allowed

    roots = await tenant.roots_for_environment(customer.id, environment_id)
    from app.services.platform.customer_ai import build_customer_agent

    agent = build_customer_agent(
        settings, session, customer_id=customer.id, env=env, roots=roots
    )

    async def gen():
        import json as _json

        try:
            async for event in agent.apply_action_stream(
                user,
                body,
                can_write_files=feature_included(plan, "file_manager"),
                can_execute_terminal=ssh_allowed(plan) or feature_included(plan, "ai_server"),
                can_manage_databases=feature_included(plan, "db_manage") and bool(env.db_registry_id),
            ):
                yield f"data: {_json.dumps(event, default=str)}\n\n"
            yield "data: [DONE]\n\n"
        except Exception as exc:  # noqa: BLE001
            yield f"data: {_json.dumps({'type': 'error', 'message': str(exc)})}\n\n"
            yield "data: [DONE]\n\n"

    from fastapi.responses import StreamingResponse

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/environments/{environment_id}/ai/actions/undo", response_model=OperationResult)
async def env_ai_undo(
    environment_id: UUID,
    user: CurrentUser,
    session: DbSession,
    settings: SettingsDep,
) -> OperationResult:
    _require_customer_user(user)
    customer = await CustomerService(settings, session).require_for_user(user.id)
    tenant = TenantService(session)
    env = await tenant.get_owned_environment(customer.id, environment_id, allow_suspended=False)
    roots = await tenant.roots_for_environment(customer.id, environment_id)
    from app.services.platform.customer_ai import build_customer_agent

    agent = build_customer_agent(
        settings, session, customer_id=customer.id, env=env, roots=roots
    )
    return await agent.undo_last(can_write_files=True)


@router.post("/tickets", response_model=SupportTicketResponse)
async def create_ticket(
    body: SupportTicketCreateRequest,
    user: CurrentUser,
    session: DbSession,
    settings: SettingsDep,
) -> SupportTicketResponse:
    _require_customer_user(user)
    customer = await CustomerService(settings, session).require_for_user(user.id)
    from app.services.platform.tickets import SupportTicketService

    svc = SupportTicketService(settings, session)
    ticket = await svc.create_ticket(
        customer_id=customer.id,
        author_user_id=user.id,
        subject=body.subject,
        body=body.body,
        priority=body.priority,
        environment_id=body.environment_id,
    )
    messages = await svc.list_messages(ticket.id)
    return SupportTicketResponse(
        id=ticket.id,
        customer_id=ticket.customer_id,
        environment_id=ticket.environment_id,
        subject=ticket.subject,
        status=ticket.status,
        priority=ticket.priority,
        created_at=ticket.created_at,
        updated_at=ticket.updated_at,
        messages=[SupportTicketMessageResponse.model_validate(m) for m in messages],
    )


@router.get("/tickets", response_model=list[SupportTicketResponse])
async def list_tickets(
    user: CurrentUser,
    session: DbSession,
    settings: SettingsDep,
) -> list[SupportTicketResponse]:
    _require_customer_user(user)
    customer = await CustomerService(settings, session).require_for_user(user.id)
    from app.services.platform.tickets import SupportTicketService

    rows = await SupportTicketService(settings, session).list_customer(customer.id)
    return [SupportTicketResponse.model_validate(r) for r in rows]


@router.get("/tickets/{ticket_id}", response_model=SupportTicketResponse)
async def get_ticket(
    ticket_id: UUID,
    user: CurrentUser,
    session: DbSession,
    settings: SettingsDep,
) -> SupportTicketResponse:
    _require_customer_user(user)
    customer = await CustomerService(settings, session).require_for_user(user.id)
    from app.services.platform.tickets import SupportTicketService

    svc = SupportTicketService(settings, session)
    ticket = await svc.get_customer(customer.id, ticket_id)
    messages = await svc.list_messages(ticket.id)
    return SupportTicketResponse(
        id=ticket.id,
        customer_id=ticket.customer_id,
        environment_id=ticket.environment_id,
        subject=ticket.subject,
        status=ticket.status,
        priority=ticket.priority,
        created_at=ticket.created_at,
        updated_at=ticket.updated_at,
        messages=[SupportTicketMessageResponse.model_validate(m) for m in messages],
    )


@router.post("/tickets/{ticket_id}/messages", response_model=SupportTicketMessageResponse)
async def reply_ticket(
    ticket_id: UUID,
    body: SupportTicketMessageCreateRequest,
    user: CurrentUser,
    session: DbSession,
    settings: SettingsDep,
) -> SupportTicketMessageResponse:
    _require_customer_user(user)
    customer = await CustomerService(settings, session).require_for_user(user.id)
    from app.services.platform.tickets import SupportTicketService

    msg = await SupportTicketService(settings, session).add_message(
        ticket_id=ticket_id,
        author_user_id=user.id,
        author_role="customer",
        body=body.body,
        customer_id=customer.id,
    )
    return SupportTicketMessageResponse.model_validate(msg)


@router.get("/notifications", response_model=list[NotificationResponse])
async def list_notifications(
    user: CurrentUser,
    session: DbSession,
    settings: SettingsDep,
) -> list[NotificationResponse]:
    _require_customer_user(user)
    customer = await CustomerService(settings, session).require_for_user(user.id)
    rows = await NotificationService(session, settings).list_for_customer(customer.id)
    return [NotificationResponse.model_validate(r) for r in rows]


@router.post("/notifications/{notification_id}/read", response_model=NotificationResponse)
async def mark_notification_read(
    notification_id: UUID,
    user: CurrentUser,
    session: DbSession,
    settings: SettingsDep,
) -> NotificationResponse:
    _require_customer_user(user)
    customer = await CustomerService(settings, session).require_for_user(user.id)
    row = await NotificationService(session, settings).mark_read(customer.id, notification_id)
    return NotificationResponse.model_validate(row)


@router.post("/domains/check", response_model=DomainAvailabilityResponse)
async def check_domain(
    body: DomainAvailabilityRequest,
    settings: SettingsDep,
) -> DomainAvailabilityResponse:
    result = await DomainRegistrar(settings).check(body.name, body.extension)
    return DomainAvailabilityResponse(
        domain=str(result["domain"]),
        available=bool(result["available"]),
        price_yearly=result["price_yearly"],
        currency=str(result.get("currency") or "GHS"),
        message=str(result["message"]),
        provider=str(result.get("provider") or "local"),
    )


@router.get("/domains", response_model=CustomerDomainListResponse)
async def list_customer_domains(
    user: CurrentUser,
    session: DbSession,
    settings: SettingsDep,
) -> CustomerDomainListResponse:
    """List all registered and assigned domains for the authenticated customer."""
    _require_customer_user(user)
    customer = await CustomerService(settings, session).require_for_user(user.id)
    from app.models.platform import CustomerDomain, CustomerEnvironment

    result = await session.execute(
        select(CustomerDomain)
        .where(CustomerDomain.customer_id == customer.id)
        .order_by(CustomerDomain.created_at.desc())
    )
    domains = list(result.scalars().all())
    existing_domain_names = {d.domain_name.strip().lower() for d in domains if d.domain_name}

    # Also discover all customer environments to ensure none are missing
    all_envs_res = await session.execute(
        select(CustomerEnvironment).where(
            CustomerEnvironment.customer_id == customer.id,
            CustomerEnvironment.status != "terminated",
        )
    )
    all_envs = list(all_envs_res.scalars().all())
    for env_row in all_envs:
        dom_name = (env_row.domain or "").strip().lower()
        if dom_name and dom_name not in existing_domain_names:
            is_sub = (
                dom_name.endswith(".ifnotus.space")
                or dom_name.endswith(".serverlabsttu.space")
                or dom_name.endswith(".customers.ifnotus.space")
            )
            new_cd = CustomerDomain(
                customer_id=customer.id,
                environment_id=env_row.id,
                domain_name=dom_name,
                registrar="ifnotus" if is_sub else "customer",
                status="active" if is_sub else "active",
                ssl_status=env_row.ssl_status or "active",
                registration_date=env_row.created_at,
                expiry_date=env_row.created_at + timedelta(days=365) if env_row.created_at else None,
            )
            session.add(new_cd)
            domains.append(new_cd)
            existing_domain_names.add(dom_name)
    await session.flush()

    env_ids = [d.environment_id for d in domains if d.environment_id]
    env_map: dict[UUID, str] = {}
    if env_ids:
        envs_res = await session.execute(
            select(CustomerEnvironment).where(CustomerEnvironment.id.in_(env_ids))
        )
        for e in envs_res.scalars().all():
            env_map[e.id] = e.domain or e.hosting_name or str(e.id)

    from app.services.platform.student_hostname import is_student_hostname

    items = []
    for d in domains:
        name_lower = (d.domain_name or "").strip().lower()
        is_subdomain = (
            name_lower.endswith(".ifnotus.space")
            or name_lower.endswith(".serverlabsttu.space")
            or name_lower.endswith(".customers.ifnotus.space")
            or d.registrar == "ifnotus"
            or is_student_hostname(name_lower, settings=settings)
        )
        effective_status = "active" if is_subdomain else d.status
        is_active = effective_status == "active"
        items.append(
            CustomerDomainItemResponse(
                id=d.id,
                domain_name=d.domain_name,
                status=effective_status,
                is_active=is_active,
                registrar="ifnotus" if is_subdomain else d.registrar,
                registration_date=d.registration_date,
                expiry_date=d.expiry_date,
                auto_renew=d.auto_renew,
                environment_id=d.environment_id,
                environment_domain=env_map.get(d.environment_id) if d.environment_id else None,
                propagation_notice=(
                    None
                    if is_subdomain
                    else (
                        "New domain registrations and DNS updates take 24 to 48 hours to fully propagate worldwide across all networks."
                    )
                ),
            )
        )

    return CustomerDomainListResponse(
        items=items,
        propagation_notice=(
            "New domain registrations and DNS updates take 24 to 48 hours to fully propagate worldwide across all networks."
        ),
    )


@router.post("/orders/domain", response_model=CreateOrderResponse)
async def create_domain_order(
    body: CreateDomainOrderRequest,
    user: CurrentUser,
    session: DbSession,
    settings: SettingsDep,
) -> CreateOrderResponse:
    """Buy a standalone domain without hosting or attach to an existing environment."""
    _require_customer_user(user)
    customer = await CustomerService(settings, session).require_for_user(user.id)
    result = await OrderService(settings, session).create_domain_order(
        customer,
        domain_name=body.domain_name,
        domain_extension=body.domain_extension,
        environment_id=body.environment_id,
    )
    return CreateOrderResponse.model_validate(result)


@router.post("/domains/student-preview", response_model=StudentHostnameResponse)
async def student_hostname_preview(
    body: StudentHostnameRequest,
    user: CurrentUser,
    session: DbSession,
    settings: SettingsDep,
) -> StudentHostnameResponse:
    _require_customer_user(user)
    from app.services.platform.student_hostname import StudentHostnameService

    result = await StudentHostnameService(session, settings).preview(body.surname)
    return StudentHostnameResponse.model_validate(result)


@router.post("/environments/{environment_id}/student-hostname", response_model=StudentHostnameResponse)
async def assign_student_hostname(
    environment_id: UUID,
    body: StudentHostnameRequest,
    user: CurrentUser,
    session: DbSession,
    settings: SettingsDep,
) -> StudentHostnameResponse:
    """Assign or claim student project surname address on an unassigned environment."""
    _require_customer_user(user)
    customer = await CustomerService(settings, session).require_for_user(user.id)
    env = await TenantService(session).get_owned_environment(customer.id, environment_id)

    from app.services.platform.student_hostname import StudentHostnameService
    from app.services.platform.staff import StaffPlatformService

    svc = StudentHostnameService(session, settings)
    allocated_hostname = await svc.allocate(body.surname)

    staff_svc = StaffPlatformService(settings, session)
    await staff_svc.update_environment_subdomain(env.id, allocated_hostname, actor_id=user.id)

    return StudentHostnameResponse(
        surname=body.surname,
        hostname=allocated_hostname,
        available=True,
        message=f"Student project is now live on {allocated_hostname}!",
        zone=svc._zone,
    )


@router.get("/panel-alias", response_model=PanelAliasResolveResponse)
async def resolve_panel_alias(
    user: CurrentUser,
    session: DbSession,
    settings: SettingsDep,
    host: str = Query(min_length=3, max_length=253),
) -> PanelAliasResolveResponse:
    """Map cpanel.<domain> / site hostname to the caller's environment. Never trust Host alone."""
    _require_customer_user(user)
    from app.core.exceptions import ValidationError
    from app.models.platform import CustomerDomain, CustomerEnvironment
    from app.services.platform.customers import CustomerService
    from app.services.platform.host_routing import (
        classify_host,
        panel_alias_apex,
        sanitize_panel_hostname,
    )
    from sqlalchemy import func

    safe = sanitize_panel_hostname(host)
    if not safe:
        raise ValidationError("Invalid hostname.")
    kind = classify_host(safe, settings=settings)
    if kind.kind == "platform":
        raise AppException("That hostname is reserved for IFNOTUS.", code="host_reserved")
    lookup = None
    if kind.kind == "custom_panel":
        lookup = panel_alias_apex(safe)
    elif kind.kind == "student":
        lookup = kind.hostname
    elif kind.kind == "custom_site":
        lookup = kind.apex or kind.hostname
    if not lookup:
        raise NotFoundError("Unknown hosting hostname.")
    lookup = lookup.lower().rstrip(".")
    if lookup.startswith("www."):
        lookup = lookup[4:]

    is_staff = _is_staff_user(user)
    customer = await CustomerService(settings, session).get_by_user_id(user.id)

    # 1. Match environment by domain
    env = (
        await session.execute(
            select(CustomerEnvironment).where(
                func.lower(CustomerEnvironment.domain) == lookup,
            )
        )
    ).scalar_one_or_none()

    # 2. Match environment by CustomerDomain
    if env is None:
        owned = (
            await session.execute(
                select(CustomerDomain).where(
                    func.lower(CustomerDomain.domain_name) == lookup,
                )
            )
        ).scalar_one_or_none()
        if owned is not None and owned.environment_id:
            env = await session.get(CustomerEnvironment, owned.environment_id)

    # 3. Match environment by Domain table
    if env is None:
        from app.models.hosting import Domain

        domain_row = (
            await session.execute(
                select(Domain).where(
                    func.lower(Domain.name) == lookup,
                )
            )
        ).scalar_one_or_none()
        if domain_row is not None:
            if domain_row.parent_domain_id:
                env = (
                    await session.execute(
                        select(CustomerEnvironment).where(
                            CustomerEnvironment.hosting_domain_id == domain_row.parent_domain_id,
                        )
                    )
                ).scalar_one_or_none()
            if env is None:
                env = (
                    await session.execute(
                        select(CustomerEnvironment).where(
                            CustomerEnvironment.hosting_domain_id == domain_row.id,
                        )
                    )
                ).scalar_one_or_none()

    if env is None:
        raise NotFoundError("No hosting environment for that hostname.")

    # Validate access
    if not is_staff and (customer is None or env.customer_id != customer.id):
        raise AuthorizationError("You do not have access to that site.")
    if env.status in {"terminated", "terminating"}:
        raise AppException("That hosting service is no longer available.", code="env_terminated")
    return PanelAliasResolveResponse(
        host=kind.hostname,
        kind=kind.kind,
        environment_id=env.id,
        domain=env.domain or lookup,
        status=env.status,
    )


@router.post("/sso-handoff", response_model=HostingSsoHandoffResponse)
async def create_hosting_sso_handoff(
    body: HostingSsoHandoffRequest,
    user: CurrentUser,
    session: DbSession,
    settings: SettingsDep,
) -> HostingSsoHandoffResponse:
    """Create a short-lived, single-use SSO token for cross-origin customer cPanel navigation."""
    from app.services.platform.sso import HostingSsoService

    service = HostingSsoService(settings, session)
    result = await service.create_handoff(
        user,
        environment_id=body.environment_id,
        domain=body.domain,
        tab=body.tab,
    )
    return HostingSsoHandoffResponse(
        handoff_url=result["handoff_url"],
        token=result["token"],
        target_host=result["target_host"],
        environment_id=result["environment_id"],
        domain=result["domain"],
        expires_in=result["expires_in"],
    )


@router.post("/subscriptions/{subscription_id}/renew", response_model=RenewPaymentResponse)
async def renew_subscription(
    subscription_id: UUID,
    user: CurrentUser,
    session: DbSession,
    settings: SettingsDep,
    body: RenewSubscriptionRequest | None = None,
) -> RenewPaymentResponse:
    _require_customer_user(user)
    customer = await CustomerService(settings, session).require_for_user(user.id)
    term = body.billing_term_months if body else None
    result = await OrderService(settings, session).create_renewal_payment(
        customer,
        subscription_id,
        billing_term_months=term,
    )
    order = result.get("order")
    return RenewPaymentResponse(
        reference=result["reference"],
        authorization_url=None,
        demo=False,
        amount=result["amount"],
        currency="GHS",
        subscription_id=subscription_id,
        invoice_number=getattr(order, "invoice_number", None) or result.get("invoice_number"),
        order_id=getattr(order, "id", None),
        message="Pay the IFNOTUS merchant Mobile Money number, then share the transaction ID on the invoice.",
    )


@router.post("/subscriptions/{subscription_id}/change-plan", response_model=RenewPaymentResponse)
async def change_subscription_plan(
    subscription_id: UUID,
    body: ChangePlanRequest,
    user: CurrentUser,
    session: DbSession,
    settings: SettingsDep,
) -> RenewPaymentResponse:
    _require_customer_user(user)
    customer = await CustomerService(settings, session).require_for_user(user.id)
    result = await OrderService(settings, session).create_upgrade_payment(
        customer, subscription_id, body.plan_id
    )
    if result.get("applied"):
        sub = await SubscriptionBillingService(settings, session).get_owned(customer.id, subscription_id)
        return RenewPaymentResponse(
            reference=str(result.get("reference") or "downgrade"),
            demo=True,
            amount=result.get("amount") or 0,
            currency="GHS",
            subscription_id=subscription_id,
            applied=True,
            subscription=SubscriptionResponse.model_validate(sub),
            message="Plan updated without a new charge.",
        )
    order = result.get("order")
    return RenewPaymentResponse(
        reference=result["reference"],
        authorization_url=None,
        demo=False,
        amount=result["amount"],
        currency="GHS",
        subscription_id=subscription_id,
        invoice_number=getattr(order, "invoice_number", None) or result.get("invoice_number"),
        order_id=getattr(order, "id", None),
        message="Pay the IFNOTUS merchant Mobile Money number, then share the transaction ID on the invoice.",
    )


@router.post("/credits/topup", response_model=CreditTopUpResponse)
async def topup_credits(
    body: CreditTopUpRequest,
    user: CurrentUser,
    session: DbSession,
    settings: SettingsDep,
) -> CreditTopUpResponse:
    _require_customer_user(user)
    customer = await CustomerService(settings, session).require_for_user(user.id)
    result = await OrderService(settings, session).create_credit_topup(customer, body.credits)
    order = result.get("order")
    return CreditTopUpResponse(
        reference=result["reference"],
        authorization_url=None,
        demo=False,
        credits=body.credits,
        amount=result["amount"],
        invoice_number=getattr(order, "invoice_number", None) or result.get("invoice_number"),
        order_id=getattr(order, "id", None),
    )


@router.post("/subscriptions/{subscription_id}/auto-renew", response_model=SubscriptionResponse)
async def set_auto_renew(
    subscription_id: UUID,
    body: AutoRenewRequest,
    user: CurrentUser,
    session: DbSession,
    settings: SettingsDep,
) -> SubscriptionResponse:
    _require_customer_user(user)
    customer = await CustomerService(settings, session).require_for_user(user.id)
    sub = await SubscriptionBillingService(settings, session).set_auto_renew(
        customer.id, subscription_id, body.enabled
    )
    return SubscriptionResponse.model_validate(sub)


@router.post("/environments/{environment_id}/hosting-password", response_model=HostingPasswordSetResponse)
async def set_hosting_password(
    environment_id: UUID,
    body: HostingPasswordSetRequest,
    user: CurrentUser,
    session: DbSession,
    settings: SettingsDep,
) -> HostingPasswordSetResponse:
    """Set or change the hosting panel password for an environment from the customer account."""
    _require_customer_user(user)
    customer = await CustomerService(settings, session).get_by_user_id(user.id)
    env = await session.get(CustomerEnvironment, environment_id)
    if env is None:
        raise NotFoundError("Hosting environment not found.")

    is_staff = bool(
        user.is_superuser
        or any(
            r in (user.roles or [])
            for r in (
                "admin",
                "superadmin",
                "platform_admin",
                "platform_owner",
                "hosting_operator",
                "operator",
                "support_agent",
            )
        )
    )
    if not is_staff and (customer is None or env.customer_id != customer.id):
        raise NotFoundError("Hosting environment not found.")

    pwd = (body.password or "").strip()
    if len(pwd) < 8:
        raise ValidationError("Password must be at least 8 characters.", code="password_too_short")

    env.panel_password_hash = hash_password(pwd)
    session.add(
        PlatformAuditLog(
            customer_id=env.customer_id,
            actor_id=user.id,
            action="hosting_panel_password_updated",
            target_type="environment",
            target_id=str(env.id),
            result="success",
            metadata_json={"hosting_name": env.hosting_name, "domain": env.domain},
        )
    )
    await session.flush()
    return HostingPasswordSetResponse(
        success=True,
        message="Hosting fPanel password updated successfully.",
        username=env.unix_username or env.hosting_name or "fpanel_user",
    )


@router.post("/subscriptions/{subscription_id}/cancel-request", response_model=SubscriptionCancelResponse)
async def request_cancel_subscription(
    subscription_id: UUID,
    body: SubscriptionCancelRequest,
    user: CurrentUser,
    session: DbSession,
    settings: SettingsDep,
) -> SubscriptionCancelResponse:
    """Submit a cancellation request for a hosting subscription."""
    _require_customer_user(user)
    customer = await CustomerService(settings, session).require_for_user(user.id)
    sub = await SubscriptionBillingService(settings, session).get_owned(customer.id, subscription_id)

    sub.auto_renew = False
    session.add(
        PlatformAuditLog(
            customer_id=customer.id,
            actor_id=user.id,
            action="subscription_cancellation_requested",
            target_type="subscription",
            target_id=str(sub.id),
            result="success",
            metadata_json={"reason": body.reason},
        )
    )
    await NotificationService(session, settings).notify(
        customer.id,
        title="Cancellation Request Received",
        body=f"Your cancellation request for subscription {str(sub.id)[:8]} has been recorded. Auto-renewal has been turned off.",
        kind="billing",
        deliver=False,
    )
    await session.flush()
    return SubscriptionCancelResponse(
        success=True,
        message="Cancellation request received. Auto-renew has been turned off.",
        subscription_id=sub.id,
    )


@router.post("/billing/tick")
async def run_billing_tick(
    user: CurrentUser,
    session: DbSession,
    settings: SettingsDep,
) -> dict:
    if not (user.is_superuser or Role.ADMIN.value in (user.roles or []) or Role.SUPERADMIN.value in (user.roles or [])):
        raise AuthorizationError("Staff only.")
    return await SubscriptionBillingService(settings, session).tick()


@router.get("/capacity", response_model=StaffCapacityDashboardResponse)
async def capacity(
    user: CurrentUser,
    session: DbSession,
    settings: SettingsDep,
) -> StaffCapacityDashboardResponse:
    """Legacy alias — prefer GET /platform/capacity."""
    from app.core.permissions import permissions_for_roles
    from app.services.platform.staff_capacity import StaffCapacityService

    roles = list(user.roles or [])
    role_enums = []
    for r in roles:
        try:
            role_enums.append(Role(r))
        except ValueError:
            continue
    perms = permissions_for_roles(role_enums, is_superuser=user.is_superuser)
    if Permission.PLATFORM_READ not in perms and not user.is_superuser:
        raise AuthorizationError("Staff only.")
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
