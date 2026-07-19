"""FastAPI dependency injection wiring."""

from collections.abc import AsyncGenerator
from typing import Annotated

from fastapi import Depends, Request, Security
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.exceptions import AuthenticationError, AuthorizationError
from app.core.permissions import Permission
from app.repositories.user import UserRepository
from app.schemas.auth import AuthenticatedUser
from app.services.access_control import AccessControlService
from app.services.auth import AuthService

security_scheme = HTTPBearer(auto_error=False)


async def get_db(request: Request) -> AsyncGenerator[AsyncSession]:
    """Provide a request-scoped database session."""
    session_factory = request.app.state.container.db_session_factory()
    async with session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


def get_settings(request: Request) -> Settings:
    """Return application settings from the DI container."""
    return request.app.state.container.config()


async def get_auth_service(
    session: Annotated[AsyncSession, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> AuthService:
    return AuthService(settings, UserRepository(session), AccessControlService(session))


async def get_access_control(
    session: Annotated[AsyncSession, Depends(get_db)],
) -> AccessControlService:
    return AccessControlService(session)


async def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Security(security_scheme)],
    auth_service: Annotated[AuthService, Depends(get_auth_service)],
) -> AuthenticatedUser:
    """Resolve the authenticated user from the Bearer token."""
    if credentials is None:
        raise AuthenticationError("Missing authentication credentials.")
    return await auth_service.get_current_user(credentials.credentials)


def require_permission(permission: Permission):
    """Factory for permission-checking dependencies."""

    async def _check(
        user: Annotated[AuthenticatedUser, Depends(get_current_user)],
        auth_service: Annotated[AuthService, Depends(get_auth_service)],
    ) -> AuthenticatedUser:
        if not auth_service.user_has_permission(user, permission.value):
            raise AuthorizationError(f"Permission '{permission.value}' required.")
        return user

    return _check


# Type aliases for cleaner router signatures
DbSession = Annotated[AsyncSession, Depends(get_db)]
SettingsDep = Annotated[Settings, Depends(get_settings)]
CurrentUser = Annotated[AuthenticatedUser, Depends(get_current_user)]
AccessControlDep = Annotated[AccessControlService, Depends(get_access_control)]
RequirePermission = require_permission  # usage: Depends(RequirePermission(Permission.X))
