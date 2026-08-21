"""IFNOTUS customer portal + product APIs."""

from __future__ import annotations

import ipaddress
from uuid import UUID

from fastapi import APIRouter, File, Query, Request, UploadFile
from sqlalchemy import select

from app.api.deps import AccessControlDep, CurrentUser, DbSession, SettingsDep
from app.core.exceptions import AppException, AuthenticationError, AuthorizationError, NotFoundError
from app.core.permissions import Role
from app.core.security import create_token_pair
from app.models.platform import HostingPlan, Subscription
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
    FileDetailSchema,
    FileUploadCompleteRequest,
    FileUploadInitRequest,
    FileUploadInitResponse,
    MailboxCreate,
    MailDomainResponse,
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
    ChangePlanRequest,
    CreateOrderRequest,
    CreateOrderResponse,
    CreditTopUpRequest,
    CreditTopUpResponse,
    EnvironmentDnsRecordCreateRequest,
    EnvironmentGitCloneRequest,
    EnvironmentRedirectCreateRequest,
    HostingPlanSchema,
    CustomerCompleteProfileRequest,
    CustomerDashboardResponse,
    CustomerFileMkdirRequest,
    CustomerFileWriteRequest,
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
    TotpConfirmRequest,
    TotpSetupResponse,
    EnvironmentDatabaseResponse,
    EnvironmentDatabaseV2Response,
    ApplicationInstanceCreateRequest,
    ApplicationInstanceResponse,
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
    EnvironmentUsageResponse,
    EnvironmentHealthResponse,
    NotificationResponse,
    OrderResponse,
    RenewPaymentResponse,
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

router = APIRouter()


def _require_customer_user(user) -> None:
    roles = set(user.roles or [])
    if user.is_superuser or Role.CUSTOMER.value in roles or Role.ADMIN.value in roles or Role.SUPERADMIN.value in roles:
        return
    raise AuthorizationError("Customer account required.")


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
    unread_badge = await NotificationService(session, settings).unread_badge_count(customer.id)
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
    return await FileManagerService(
        settings, only_roots=roots, storage_limit_gb=env.storage_limit_gb
    ).list_files(path)


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
    return await FileManagerService(
        settings, only_roots=roots, storage_limit_gb=env.storage_limit_gb
    ).read_file(path)


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
    return await FileManagerService(
        settings, only_roots=roots, storage_limit_gb=env.storage_limit_gb
    ).write_file(body.path, body.content)


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
    return await FileManagerService(
        settings, only_roots=roots, storage_limit_gb=env.storage_limit_gb
    ).mkdir(body.path)


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
) -> OperationResult:
    _require_customer_user(user)
    customer = await CustomerService(settings, session).require_for_user(user.id)
    env = await TenantService(session).get_owned_environment(customer.id, environment_id)
    await TenantService(session).require_capability(env, "file_manager", label="File manager")
    roots = await TenantService(session).roots_for_environment(customer.id, environment_id)
    return await FileManagerService(
        settings, only_roots=roots, storage_limit_gb=env.storage_limit_gb
    ).delete(path)


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
    return await FileManagerService(
        settings, only_roots=roots, storage_limit_gb=env.storage_limit_gb
    ).upload(path, file)


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
    return await FileManagerService(
        settings, only_roots=roots, storage_limit_gb=env.storage_limit_gb
    ).init_chunked_upload(
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
    # Touch FileManagerService so only_roots/quota context matches init (meta stores path).
    _ = FileManagerService(settings, only_roots=roots, storage_limit_gb=env.storage_limit_gb)
    data = await file.read()
    return await FileManagerService(
        settings, only_roots=roots, storage_limit_gb=env.storage_limit_gb
    ).upload_chunk(upload_id, chunk_index, data)


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
    return await FileManagerService(
        settings, only_roots=roots, storage_limit_gb=env.storage_limit_gb
    ).complete_chunked_upload(body.upload_id)


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
) -> EnvironmentDatabaseResponse:
    _require_customer_user(user)
    customer = await CustomerService(settings, session).require_for_user(user.id)
    env = await TenantService(session).get_owned_environment(customer.id, environment_id)
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
async def list_env_databases_v2(
    environment_id: UUID,
    user: CurrentUser,
    session: DbSession,
    settings: SettingsDep,
) -> list[EnvironmentDatabaseV2Response]:
    """PHASE 11 stub: EnvironmentDatabase registry + legacy db_* as synthetic rows."""
    _require_customer_user(user)
    customer = await CustomerService(settings, session).require_for_user(user.id)
    env = await TenantService(session).get_owned_environment(customer.id, environment_id)
    rows: list[EnvironmentDatabaseV2Response] = []

    try:
        from app.models.platform import EnvironmentDatabase  # type: ignore[attr-defined]

        result = await session.execute(
            select(EnvironmentDatabase).where(EnvironmentDatabase.environment_id == env.id)
        )
        for item in result.scalars().all():
            rows.append(
                EnvironmentDatabaseV2Response(
                    id=str(getattr(item, "id", "")),
                    environment_id=env.id,
                    engine=getattr(item, "engine", None),
                    name=getattr(item, "name", None),
                    username=getattr(item, "username", None),
                    host=_customer_db_host(getattr(item, "host", None)),
                    port=getattr(item, "port", None),
                    password_set=bool(getattr(item, "password_encrypted", None)),
                    legacy=False,
                )
            )
    except ImportError:
        rows = []

    if env.db_name or env.db_engine:
        legacy_id = str(getattr(env, "db_registry_id", None) or f"legacy-{env.id}")
        if not any(r.id == legacy_id or (r.name == env.db_name and r.legacy) for r in rows):
            rows.append(
                EnvironmentDatabaseV2Response(
                    id=legacy_id,
                    environment_id=env.id,
                    engine=env.db_engine,
                    name=env.db_name,
                    username=env.db_username,
                    host=_customer_db_host(env.db_host),
                    port=env.db_port,
                    password_set=bool(env.db_password_encrypted),
                    legacy=True,
                    message="Migrated from environment db_* fields.",
                )
            )
    return rows


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
    """PHASE 10 stub: list ApplicationInstance rows (empty until model ships)."""
    _require_customer_user(user)
    customer = await CustomerService(settings, session).require_for_user(user.id)
    env = await TenantService(session).get_owned_environment(customer.id, environment_id)

    try:
        from app.models.platform import ApplicationInstance  # type: ignore[attr-defined]

        result = await session.execute(
            select(ApplicationInstance).where(ApplicationInstance.environment_id == env.id)
        )
        out: list[ApplicationInstanceResponse] = []
        for item in result.scalars().all():
            out.append(
                ApplicationInstanceResponse(
                    id=str(getattr(item, "id", "")),
                    environment_id=env.id,
                    name=str(getattr(item, "name", "") or "app"),
                    stack=str(getattr(item, "stack", "") or "static"),
                    status=str(getattr(item, "status", "pending") or "pending"),
                    port=getattr(item, "port", None),
                )
            )
        return out
    except ImportError:
        return []


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
    """PHASE 10 stub: entitlement-checked application create."""
    _require_customer_user(user)
    customer = await CustomerService(settings, session).require_for_user(user.id)
    tenant = TenantService(session)
    env = await tenant.get_owned_environment(customer.id, environment_id)
    plan = await tenant.plan_for_environment(env)

    from app.services.platform.plan_matrix import pack_denied_message, stack_allowed

    stack = body.stack.strip().lower()
    if not stack_allowed(plan, stack):
        raise AppException(pack_denied_message(f"Stack '{stack}'"), code="pack_feature")

    try:
        from uuid import uuid4

        from app.models.platform import ApplicationInstance  # type: ignore[attr-defined]

        item = ApplicationInstance(
            id=uuid4(),
            environment_id=env.id,
            name=body.name.strip(),
            stack=stack,
            status="pending",
            git_url=body.git_url,
        )
        session.add(item)
        await session.flush()
        return ApplicationInstanceResponse(
            id=str(item.id),
            environment_id=env.id,
            name=item.name,
            stack=item.stack,
            status=getattr(item, "status", "pending"),
            port=getattr(item, "port", None),
            message="Application registered.",
        )
    except ImportError:
        return ApplicationInstanceResponse(
            id=f"pending-{environment_id}-{stack}",
            environment_id=env.id,
            name=body.name.strip(),
            stack=stack,
            status="pending",
            message="Application runtime registry is not provisioned yet; entitlement check passed.",
        )
    except Exception as exc:  # noqa: BLE001
        raise AppException(
            f"Could not create application: {str(exc)[:240]}",
            code="application_create_failed",
        ) from exc


def _env_db_id(env) -> str:
    rid = getattr(env, "db_registry_id", None)
    if not rid:
        raise AppException(
            "No database on this site yet. Install WordPress or Laravel, or ask support to attach one.",
            code="no_database",
        )
    return str(rid)


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
) -> DbSchemaResponse:
    _require_customer_user(user)
    customer = await CustomerService(settings, session).require_for_user(user.id)
    env = await TenantService(session).get_owned_environment(customer.id, environment_id)
    await TenantService(session).require_capability(env, "db_manage", label="Database management")
    return await DatabaseStudioService(DatabaseManagerService(settings)).schema_managed(_env_db_id(env))


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
) -> DbQueryResponse:
    _require_customer_user(user)
    customer = await CustomerService(settings, session).require_for_user(user.id)
    env = await TenantService(session).get_owned_environment(customer.id, environment_id)
    await TenantService(session).require_capability(env, "db_manage", label="Database management")
    body = DbRowsRequest(
        table=table, collection=collection, schema_name=schema_name, limit=limit, offset=offset
    )
    return await DatabaseStudioService(DatabaseManagerService(settings)).rows_managed(_env_db_id(env), body)


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
) -> DbQueryResponse:
    _require_customer_user(user)
    customer = await CustomerService(settings, session).require_for_user(user.id)
    env = await TenantService(session).get_owned_environment(customer.id, environment_id)
    plan = await TenantService(session).require_capability(env, "db_manage", label="Database management")
    _require_db_write(plan)
    return await DatabaseStudioService(DatabaseManagerService(settings)).insert_row_managed(
        _env_db_id(env), body
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
) -> DbQueryResponse:
    _require_customer_user(user)
    customer = await CustomerService(settings, session).require_for_user(user.id)
    env = await TenantService(session).get_owned_environment(customer.id, environment_id)
    plan = await TenantService(session).require_capability(env, "db_manage", label="Database management")
    _require_db_write(plan)
    return await DatabaseStudioService(DatabaseManagerService(settings)).update_row_managed(
        _env_db_id(env), body
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
) -> DbQueryResponse:
    _require_customer_user(user)
    customer = await CustomerService(settings, session).require_for_user(user.id)
    env = await TenantService(session).get_owned_environment(customer.id, environment_id)
    plan = await TenantService(session).require_capability(env, "db_manage", label="Database management")
    _require_db_write(plan)
    return await DatabaseStudioService(DatabaseManagerService(settings)).delete_row_managed(
        _env_db_id(env), body
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
    from app.core.exceptions import ValidationError
    from app.services.hosting.mail import MailService
    from app.services.platform.dns import EnvironmentDnsService

    if not env.hosting_domain_id:
        if not env.domain:
            raise ValidationError("Email is not ready until the site has a hostname.")
        # Link / create the hosting Domain row so mailboxes can attach (cPanel-style per domain).
        await EnvironmentDnsService(settings, session).ensure_hosting_domain_for_mail(env)
        await session.refresh(env)
    if not env.hosting_domain_id:
        raise ValidationError("Email is not ready until the site is live.")
    return await MailService(settings, session).get_domain_mail(env.hosting_domain_id)


@router.post("/environments/{environment_id}/mail/mailboxes")
async def create_env_mailbox(
    environment_id: UUID,
    body: MailboxCreate,
    user: CurrentUser,
    session: DbSession,
    settings: SettingsDep,
):
    _require_customer_user(user)
    customer = await CustomerService(settings, session).require_for_user(user.id)
    env = await TenantService(session).get_owned_environment(customer.id, environment_id)
    from app.core.exceptions import ValidationError
    from app.models.platform import HostingPlan, Subscription
    from app.services.hosting.mail import MailService
    from app.services.platform.dns import EnvironmentDnsService
    from app.services.platform.plan_matrix import capabilities_for, features_for

    if not env.hosting_domain_id:
        if not env.domain:
            raise ValidationError("Email is not ready until the site has a hostname.")
        await EnvironmentDnsService(settings, session).ensure_hosting_domain_for_mail(env)
        await session.refresh(env)
    if not env.hosting_domain_id:
        raise ValidationError("Email is not ready until the site is live.")

    sub = await session.get(Subscription, env.subscription_id)
    plan = await session.get(HostingPlan, sub.plan_id) if sub else None
    # Prefer capabilities.mailboxes (plan_matrix); fall back to features key.
    caps = capabilities_for(plan)
    limit = caps.get("mailboxes")
    if limit is None:
        limit = features_for(plan).get("mailboxes")
    if limit is not None:
        try:
            cap = int(limit)
        except (TypeError, ValueError):
            cap = None
        if cap is not None:
            mail = MailService(settings, session)
            existing = await mail.list_mailboxes_for_domain(env.hosting_domain_id)
            if len(existing) >= cap:
                raise ValidationError(
                    f"This package allows {cap} mailbox{'es' if cap != 1 else ''}. Remove one or upgrade."
                )

    return await MailService(settings, session).create_mailbox(env.hosting_domain_id, body)


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
    from app.services.platform.ftp import EnvironmentFtpService
    from app.services.platform.ssh_access import EnvironmentSshService

    ftp = EnvironmentFtpService(settings, session)
    if not env.ftp_username:
        await ftp.ensure_account(env)
    ssh = EnvironmentSshService(settings, session)
    data = await ssh.ensure_access(env)
    if data.get("ssh_allowed"):
        data["message"] = (
            "Jailed SSH is ready. SSH password is separate from FTP "
            "(passwords_differ_from_ftp=true). This is not root and not the operator IP."
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

    from app.services.platform.fs_ownership import fix_web_ownership

    if not env.document_root:
        raise AppException("No site folder yet.")
    root = Path(env.document_root)
    fix_web_ownership(
        root,
        user=settings.web_run_user,
        uid=getattr(env, "unix_uid", None),
        gid=getattr(env, "unix_gid", None),
    )
    cfg = root / "wp-config.php"
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
            fix_web_ownership(
                cfg,
                user=settings.web_run_user,
                uid=getattr(env, "unix_uid", None),
                gid=getattr(env, "unix_gid", None),
            )
    return MessageResponse(message="Site folder permissions repaired. Try WordPress again.")


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
) -> DbQueryResponse:
    _require_customer_user(user)
    customer = await CustomerService(settings, session).require_for_user(user.id)
    env = await TenantService(session).get_owned_environment(customer.id, environment_id)
    plan = await TenantService(session).require_capability(env, "db_manage", label="Database management")
    _deny_limited_db_writes(plan, body.sql)
    return await DatabaseStudioService(DatabaseManagerService(settings)).query_managed(
        _env_db_id(env), body
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
    env = await TenantService(session).get_owned_environment(customer.id, environment_id)
    from app.services.platform.usage import usage_snapshot

    snap = usage_snapshot(env.document_root, env.storage_limit_gb)
    return EnvironmentUsageResponse(
        environment_id=env.id,
        domain=env.domain,
        cpu_limit=env.cpu_limit,
        ram_limit_gb=env.ram_limit_gb,
        storage_limit_gb=env.storage_limit_gb,
        storage_used_bytes=int(snap["storage_used_bytes"]),
        storage_used_gb=float(snap["storage_used_gb"]),
        storage_pct=float(snap["storage_pct"]),
        file_count=int(snap["file_count"]),
        isolation_type=env.isolation_type or "filesystem",
        soft_warning=bool(snap["soft_warning"]),
        hard_exceeded=bool(snap["hard_exceeded"]),
        storage_status=str(snap["storage_status"]),
        message=str(snap["message"]),
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
        current=svc.current_stack(env),
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
    env = await TenantService(session).get_owned_environment(customer.id, environment_id)
    from app.services.platform.env_cron import EnvironmentCronService

    jobs = EnvironmentCronService(settings, session).list_jobs(env)
    return EnvCronListResponse(
        environment_id=env.id,
        jobs=[EnvCronJobSchema.model_validate(j) for j in jobs],
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
    env = await TenantService(session).get_owned_environment(customer.id, environment_id)
    await TenantService(session).require_capability(env, "cron", label="Cron jobs")
    from app.services.platform.env_cron import EnvironmentCronService

    job = EnvironmentCronService(settings, session).add_job(
        env, schedule=body.schedule, command=body.command, enabled=body.enabled
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
    env = await TenantService(session).get_owned_environment(customer.id, environment_id)
    from app.services.platform.env_cron import EnvironmentCronService

    job = EnvironmentCronService(settings, session).update_job(
        env,
        job_id,
        schedule=body.schedule,
        command=body.command,
        enabled=body.enabled,
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
    """Publish the site on IFNOTUS nameservers (never returns the VPS IP)."""
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


@router.post("/subscriptions/{subscription_id}/renew", response_model=RenewPaymentResponse)
async def renew_subscription(
    subscription_id: UUID,
    user: CurrentUser,
    session: DbSession,
    settings: SettingsDep,
) -> RenewPaymentResponse:
    _require_customer_user(user)
    customer = await CustomerService(settings, session).require_for_user(user.id)
    result = await OrderService(settings, session).create_renewal_payment(customer, subscription_id)
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


@router.post("/billing/tick")
async def run_billing_tick(
    user: CurrentUser,
    session: DbSession,
    settings: SettingsDep,
) -> dict:
    if not (user.is_superuser or Role.ADMIN.value in (user.roles or []) or Role.SUPERADMIN.value in (user.roles or [])):
        raise AuthorizationError("Staff only.")
    return await SubscriptionBillingService(settings, session).tick()


@router.get("/capacity", response_model=list[CapacityNodeResponse])
async def capacity(
    user: CurrentUser,
    session: DbSession,
) -> list[CapacityNodeResponse]:
    if not (
        user.is_superuser
        or Role.ADMIN.value in (user.roles or [])
        or Role.SUPERADMIN.value in (user.roles or [])
    ):
        raise AuthorizationError("Staff only.")
    mgr = ResourceManager(session)
    out: list[CapacityNodeResponse] = []
    for node in await mgr.list_nodes():
        snap = await mgr.snapshot(node)
        out.append(
            CapacityNodeResponse(
                node_id=snap.node_id,
                hostname="ifnotus-1",
                cpu_total=snap.cpu_total,
                ram_total_gb=snap.ram_total_gb,
                storage_total_gb=snap.storage_total_gb,
                cpu_reserved_pct=snap.cpu_reserved_pct,
                cpu_used=snap.cpu_used,
                ram_used=snap.ram_used,
                storage_used=snap.storage_used,
                cpu_free=snap.cpu_free,
                ram_free=snap.ram_free,
                storage_free=snap.storage_free,
                status=snap.status,
            )
        )
    return out
