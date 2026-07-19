"""Authentication endpoints — skeleton."""

from fastapi import APIRouter, Depends

from app.api.deps import CurrentUser, DbSession, get_auth_service
from app.schemas.auth import LoginRequest, RefreshTokenRequest, TokenResponse
from app.schemas.common import MessageResponse
from app.schemas.user import UserResponse
from app.services.auth import AuthService

router = APIRouter()


@router.post("/login", response_model=TokenResponse, summary="Authenticate user")
async def login(
    body: LoginRequest,
    auth_service: AuthService = Depends(get_auth_service),
) -> TokenResponse:
    """Exchange credentials for JWT access and refresh tokens."""
    return await auth_service.login(body)


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
