"""Authentication endpoints."""

from fastapi import APIRouter, Depends, Request

from app.api.deps import AccessControlDep, CurrentUser, DbSession, get_auth_service
from app.schemas.auth import AccessProbeRequest, LoginRequest, RefreshTokenRequest, TokenResponse
from app.schemas.common import MessageResponse
from app.schemas.user import UserResponse
from app.services.access_control import AccessContext
from app.services.auth import AuthService

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
    return AccessContext(
        ip_address=_client_ip(request),
        user_agent=request.headers.get("user-agent"),
        device_fingerprint=fingerprint or request.headers.get("x-device-fingerprint"),
        request_id=request.headers.get("x-request-id"),
    )


@router.post("/login", response_model=TokenResponse, summary="Authenticate user")
async def login(
    body: LoginRequest,
    request: Request,
    auth_service: AuthService = Depends(get_auth_service),
) -> TokenResponse:
    """Exchange credentials for JWT access and refresh tokens."""
    ctx = _access_context(request, body.device_fingerprint)
    return await auth_service.login(body, ctx)


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
async def me(user: CurrentUser, session: DbSession) -> UserResponse:
    """Return the authenticated user's profile."""
    from app.repositories.user import UserRepository

    repo = UserRepository(session)
    db_user = await repo.get_by_id(user.id)
    if db_user is None:
        from app.core.exceptions import NotFoundError

        raise NotFoundError("User not found.")
    from app.core.permissions import permissions_for_roles

    data = UserResponse.model_validate(db_user)
    return data.model_copy(
        update={
            "permissions": permissions_for_roles(
                db_user.get_roles(),
                is_superuser=db_user.is_superuser,
            )
        }
    )


@router.post("/logout", response_model=MessageResponse, summary="Logout")
async def logout() -> MessageResponse:
    """Client-side logout — JWT is discarded by the client; no server session store yet."""
    return MessageResponse(message="Logged out successfully.")
