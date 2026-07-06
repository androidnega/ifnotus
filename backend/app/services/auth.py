"""Authentication service — skeleton only."""

from datetime import UTC, datetime
from uuid import UUID

from app.core.config import Settings
from app.core.exceptions import AuthenticationError
from app.core.permissions import Role, roles_have_permission
from app.core.security import TokenType, create_token_pair, decode_token, verify_password
from app.repositories.user import UserRepository
from app.schemas.auth import AuthenticatedUser, LoginRequest, TokenResponse


class AuthService:
    """Handles authentication and token lifecycle."""

    def __init__(self, settings: Settings, user_repository: UserRepository) -> None:
        self._settings = settings
        self._users = user_repository

    async def login(self, credentials: LoginRequest) -> TokenResponse:
        """Authenticate user and return token pair."""
        user = await self._users.get_by_email(credentials.email)
        if user is None:
            user = await self._users.get_by_username(credentials.email)
        if user is None or not user.is_active:
            raise AuthenticationError("Invalid credentials.")

        if not verify_password(credentials.password, user.hashed_password):
            raise AuthenticationError("Invalid credentials.")

        user.last_login_at = datetime.now(UTC)
        await self._users.update(user)

        roles = user.get_roles()
        scopes = self._roles_to_scopes(roles)
        pair = create_token_pair(self._settings, subject=user.id, scopes=scopes)

        return TokenResponse(
            access_token=pair.access_token,
            refresh_token=pair.refresh_token,
            expires_in=pair.expires_in,
        )

    async def refresh(self, refresh_token: str) -> TokenResponse:
        """Issue new token pair from a valid refresh token."""
        payload = decode_token(self._settings, refresh_token)
        if payload.type != TokenType.REFRESH:
            raise AuthenticationError("Invalid token type.")

        user = await self._users.get_by_id(payload.sub)
        if user is None or not user.is_active:
            raise AuthenticationError("User not found or inactive.")

        scopes = self._roles_to_scopes(user.get_roles())
        pair = create_token_pair(self._settings, subject=user.id, scopes=scopes)

        return TokenResponse(
            access_token=pair.access_token,
            refresh_token=pair.refresh_token,
            expires_in=pair.expires_in,
        )

    async def get_current_user(self, token: str) -> AuthenticatedUser:
        """Resolve authenticated user from access token."""
        payload = decode_token(self._settings, token)
        if payload.type != TokenType.ACCESS:
            raise AuthenticationError("Invalid token type.")

        user = await self._users.get_by_id(payload.sub)
        if user is None or not user.is_active:
            raise AuthenticationError("User not found or inactive.")

        return AuthenticatedUser(
            id=user.id,
            email=user.email,
            username=user.username,
            roles=user.roles,
            is_superuser=user.is_superuser,
            scopes=payload.scopes,
        )

    def user_has_permission(self, user: AuthenticatedUser, permission: str) -> bool:
        """Check if authenticated user has a permission."""
        if user.is_superuser:
            return True
        roles = [Role(r) for r in user.roles if r in Role._value2member_map_]
        from app.core.permissions import Permission

        try:
            perm = Permission(permission)
        except ValueError:
            return False
        return roles_have_permission(roles, perm)

    @staticmethod
    def _roles_to_scopes(roles: list[Role]) -> list[str]:
        from app.core.permissions import ROLE_PERMISSIONS

        scopes: set[str] = set()
        for role in roles:
            for perm in ROLE_PERMISSIONS.get(role, frozenset()):
                scopes.add(perm.value)
        return sorted(scopes)
