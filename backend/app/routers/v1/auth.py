"""Authentication endpoints."""

from fastapi import APIRouter, Depends, Request

from app.api.deps import AccessControlDep, CurrentUser, DbSession, SettingsDep, get_auth_service
from app.schemas.auth import (
    AccessProbeRequest,
    ConfirmPasswordRequest,
    LoginRequest,
    LoginResponse,
    PasswordResetConfirmRequest,
    PasswordResetRequest,
    PrivilegeSwitchRequest,
    RefreshTokenRequest,
    TokenResponse,
    VerifyDeviceRequest,
)
from app.schemas.common import MessageResponse
from app.schemas.platform import TotpConfirmRequest, TotpSetupResponse
from app.schemas.user import UserResponse
from app.services.access_control import AccessContext
from app.services.auth import AuthService
from app.services.password_reset import PasswordResetService

router = APIRouter()


def _client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    real_ip = request.headers.get("x-real-ip")
    if real_ip:
        return real_ip.strip()
    if request.client and request.client.host:
        return request.client.host
    return "unknown"


def _access_context(request: Request, fingerprint: str | None = None) -> AccessContext:
    from app.services.security_actions import detect_source

    ua = request.headers.get("user-agent")
    return AccessContext(
        ip_address=_client_ip(request),
        user_agent=ua,
        device_fingerprint=fingerprint or request.headers.get("x-device-fingerprint"),
        request_id=request.headers.get("x-request-id"),
        source=detect_source(ua),
    )


@router.post("/login", response_model=LoginResponse, summary="Authenticate user")
async def login(
    body: LoginRequest,
    request: Request,
    auth_service: AuthService = Depends(get_auth_service),
) -> LoginResponse:
    """Exchange credentials for tokens, or return an IP approval challenge."""
    ctx = _access_context(request, body.device_fingerprint)
    return await auth_service.login(body, ctx)


@router.post(
    "/verify-device",
    response_model=LoginResponse,
    summary="Verify new-IP login challenge",
)
async def verify_device(
    body: VerifyDeviceRequest,
    request: Request,
    auth_service: AuthService = Depends(get_auth_service),
) -> LoginResponse:
    """Complete login after entering the one-time code from `ifnotus-unlock pending`."""
    ctx = _access_context(request, body.device_fingerprint)
    return await auth_service.verify_device(body, ctx)


@router.post("/confirm-password", response_model=MessageResponse, summary="Confirm dashboard password")
async def confirm_password(
    body: ConfirmPasswordRequest,
    user: CurrentUser,
    auth_service: AuthService = Depends(get_auth_service),
) -> MessageResponse:
    """Re-verify the signed-in user's password for sensitive areas."""
    await auth_service.confirm_password(user, body.password)
    return MessageResponse(message="Password confirmed.")


@router.post("/totp/setup", response_model=TotpSetupResponse)
async def staff_totp_setup(
    user: CurrentUser,
    session: DbSession,
    settings: SettingsDep,
) -> TotpSetupResponse:
    from app.models.user import User
    from app.services.platform.customers import CustomerService

    row = await session.get(User, user.id)
    if row is None:
        from app.core.exceptions import AuthorizationError

        raise AuthorizationError("Account not found.")
    data = await CustomerService(settings, session).totp_setup(row)
    return TotpSetupResponse.model_validate(data)


@router.post("/totp/confirm", response_model=MessageResponse)
async def staff_totp_confirm(
    body: TotpConfirmRequest,
    user: CurrentUser,
    session: DbSession,
    settings: SettingsDep,
) -> MessageResponse:
    from app.models.user import User
    from app.services.platform.customers import CustomerService

    row = await session.get(User, user.id)
    if row is None:
        from app.core.exceptions import AuthorizationError

        raise AuthorizationError("Account not found.")
    await CustomerService(settings, session).totp_confirm(row, body.code)
    return MessageResponse(message="Authenticator is on.")


@router.post(
    "/password-reset/request",
    response_model=MessageResponse,
    summary="Request password reset email",
)
async def password_reset_request(
    body: PasswordResetRequest,
    request: Request,
    session: DbSession,
    settings: SettingsDep,
) -> MessageResponse:
    """Always returns success to avoid account enumeration."""
    service = PasswordResetService(settings, session)
    message = await service.request_reset(body.email, ip=_client_ip(request))
    return MessageResponse(message=message)


@router.post(
    "/password-reset/confirm",
    response_model=MessageResponse,
    summary="Confirm password reset with token",
)
async def password_reset_confirm(
    body: PasswordResetConfirmRequest,
    session: DbSession,
    settings: SettingsDep,
) -> MessageResponse:
    service = PasswordResetService(settings, session)
    message = await service.confirm_reset(body.token, body.new_password)
    return MessageResponse(message=message)


@router.post("/probe", response_model=MessageResponse, summary="Record anonymous access probe")
async def access_probe(
    body: AccessProbeRequest,
    request: Request,
    access: AccessControlDep,
) -> MessageResponse:
    """Trace visitors hitting the login page (device fingerprint + IP)."""
    ctx = _access_context(request, body.device_fingerprint)
    await access.record_probe(ctx)
    return MessageResponse(message="Access recorded.")


@router.post("/refresh", response_model=TokenResponse, summary="Refresh tokens")
async def refresh_token(
    body: RefreshTokenRequest,
    auth_service: AuthService = Depends(get_auth_service),
) -> TokenResponse:
    """Issue a new token pair using a valid refresh token."""
    return await auth_service.refresh(body.refresh_token)


@router.get("/me", response_model=UserResponse, summary="Current user profile")
async def me(user: CurrentUser, session: DbSession, settings: SettingsDep) -> UserResponse:
    """Return the authenticated user's profile."""
    from app.repositories.user import UserRepository

    repo = UserRepository(session)
    db_user = await repo.get_by_id(user.id)
    if db_user is None:
        from app.core.exceptions import NotFoundError

        raise NotFoundError("User not found.")
    from app.core.permissions import Role, permissions_for_roles
    from app.services.auth import AuthService
    from app.services.platform.customers import CustomerService

    if not db_user.last_login_ip:
        await CustomerService(settings, session).last_login_ip_for(db_user)
    data = UserResponse.model_validate(db_user)
    can_switch = AuthService._can_privilege_switch(db_user)
    act_as = user.act_as_role
    if act_as:
        try:
            effective_roles = [Role(act_as)]
        except ValueError:
            effective_roles = db_user.get_roles()
            act_as = None
        perms = permissions_for_roles(effective_roles, is_superuser=False)
    else:
        perms = permissions_for_roles(
            db_user.get_roles(),
            is_superuser=db_user.is_superuser,
        )
    return data.model_copy(
        update={
            "permissions": perms,
            "privilege_viewing_as": act_as,
            "can_privilege_switch": can_switch,
        }
    )


@router.post(
    "/privilege-switch",
    response_model=TokenResponse,
    summary="View panel as a lesser staff role",
)
async def privilege_switch(
    body: PrivilegeSwitchRequest,
    user: CurrentUser,
    auth_service: AuthService = Depends(get_auth_service),
) -> TokenResponse:
    """Super admin temporarily uses admin/operator/viewer/customer_care powers (not clients)."""
    return await auth_service.privilege_switch(user, body.role)


@router.post(
    "/privilege-restore",
    response_model=TokenResponse,
    summary="Restore full super admin privileges",
)
async def privilege_restore(
    user: CurrentUser,
    auth_service: AuthService = Depends(get_auth_service),
) -> TokenResponse:
    return await auth_service.privilege_restore(user)


@router.post("/logout", response_model=MessageResponse, summary="Logout")
async def logout() -> MessageResponse:
    """Client-side logout — JWT is discarded by the client; no server session store yet."""
    return MessageResponse(message="Logged out successfully.")
