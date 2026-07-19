"""Authentication service."""

from datetime import UTC, datetime
from uuid import UUID

from app.core.config import Settings
from app.core.exceptions import AuthenticationError
from app.core.permissions import Role, roles_have_permission
from app.core.security import TokenType, create_token_pair, decode_token, verify_password
from app.repositories.user import UserRepository
from app.schemas.auth import AuthenticatedUser, LoginRequest, TokenResponse
from app.services.access_control import AccessContext, AccessControlService, IpBlockedError


class AuthService:
    """Handles authentication and token lifecycle."""

    def __init__(
        self,
        settings: Settings,
        user_repository: UserRepository,
        access_control: AccessControlService | None = None,
    ) -> None:
        self._settings = settings
        self._users = user_repository
        self._access = access_control

    async def login(self, credentials: LoginRequest, ctx: AccessContext | None = None) -> TokenResponse:
        """Authenticate user and return token pair."""
        identity = credentials.email.strip()
        fingerprint = credentials.device_fingerprint or (ctx.device_fingerprint if ctx else None)
        access_ctx = ctx or AccessContext(ip_address="unknown")
        if fingerprint and not access_ctx.device_fingerprint:
            access_ctx = AccessContext(
                ip_address=access_ctx.ip_address,
                user_agent=access_ctx.user_agent,
                device_fingerprint=fingerprint,
                request_id=access_ctx.request_id,
            )

        if self._access:
            try:
                await self._access.assert_ip_allowed(access_ctx)
            except IpBlockedError:
                await self._access.record_login_failure(
                    access_ctx,
                    username_or_email=identity,
                    reason="ip_blocked",
                )
                raise

        user = await self._users.get_by_email(identity)
        if user is None:
            user = await self._users.get_by_username(identity)

        if user is None:
            if self._access:
                await self._access.record_login_failure(
                    access_ctx,
                    username_or_email=identity,
                    reason="invalid_credentials",
                )
            raise AuthenticationError("Invalid credentials.")

        if not user.is_active:
            if self._access:
                await self._access.record_login_failure(
                    access_ctx,
                    username_or_email=identity,
                    reason="inactive",
                    user_id=user.id,
                )
            raise AuthenticationError("Invalid credentials.")

        if not verify_password(credentials.password, user.hashed_password):
            if self._access:
                await self._access.record_login_failure(
                    access_ctx,
                    username_or_email=identity,
                    reason="invalid_credentials",
                    user_id=user.id,
                )
            raise AuthenticationError("Invalid credentials.")

        user.last_login_at = datetime.now(UTC)
        await self._users.update(user)

        if self._access:
            await self._access.record_login_success(
                access_ctx,
                username_or_email=identity,
                user_id=user.id,
            )

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
