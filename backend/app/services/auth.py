"""Authentication service."""

from datetime import UTC, datetime
from uuid import UUID

from app.core.config import Settings
from app.core.permissions import (
    PRIVILEGE_SWITCH_ROLES,
    Role,
    STAFF_ROLE_VALUES,
    roles_have_permission,
)
from app.core.security import TokenType, create_token_pair, decode_token, verify_password
from app.core.exceptions import AuthenticationError, AuthorizationError, ValidationError
from app.repositories.user import UserRepository
from app.schemas.auth import (
    AuthenticatedUser,
    LoginRequest,
    LoginResponse,
    TokenResponse,
    VerifyDeviceRequest,
)
from app.services.access_control import (
    AccessContext,
    AccessControlService,
    IpBlockedError,
)
from app.services import auth_challenges


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

    async def login(self, credentials: LoginRequest, ctx: AccessContext | None = None) -> LoginResponse:
        """Authenticate user; may require a one-time IP approval challenge."""
        identity = credentials.email.strip()
        fingerprint = credentials.device_fingerprint or (ctx.device_fingerprint if ctx else None)
        access_ctx = ctx or AccessContext(ip_address="unknown")
        if fingerprint and not access_ctx.device_fingerprint:
            access_ctx = AccessContext(
                ip_address=access_ctx.ip_address,
                user_agent=access_ctx.user_agent,
                device_fingerprint=fingerprint,
                request_id=access_ctx.request_id,
                source=access_ctx.source,
            )

        if self._access:
            # Login is reachable from any IP so a successful auth can trust the
            # caller. Brute-force blacklist still applies.
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

        if getattr(user, "totp_enabled", False) and not self._settings.debug:
            from app.services import totp as totp_svc

            if not totp_svc.verify_code(user.totp_secret or "", credentials.totp_code or ""):
                return LoginResponse(
                    status="totp_required",
                    message="Enter the 6-digit code from your authenticator app.",
                )

        # Universal login: customers and staff share /auth/login.
        # IP device challenges apply only to staff (WHM) accounts.
        roles = set(user.roles or [])
        is_staff = user.is_superuser or bool(roles.intersection(STAFF_ROLE_VALUES))
        is_customer_only = (not is_staff) and ("customer" in roles)

        needs_challenge = False
        if (
            not self._settings.debug
            and is_staff
            and not is_customer_only
            and self._access
            and self._settings.admin_lockdown_enabled
        ):
            trusted = await self._access._is_trusted_admin_ip(access_ctx.ip_address)
            needs_challenge = not trusted

        if needs_challenge:
            challenge = await auth_challenges.create_challenge(
                ip_address=access_ctx.ip_address,
                user_id=str(user.id),
                username_or_email=identity,
                device_fingerprint=access_ctx.device_fingerprint,
                user_agent=access_ctx.user_agent,
            )
            if self._access:
                await self._access._record(
                    access_ctx,
                    event_type="login_challenge",
                    success=False,
                    failure_reason="challenge_required",
                    username_or_email=identity,
                    user_id=user.id,
                )
            return LoginResponse(
                status="challenge_required",
                challenge_id=challenge.challenge_id,
                ip_address=access_ctx.ip_address,
                message=(
                    f"New IP {access_ctx.ip_address} needs approval. "
                    f"On the server run: ifnotus-unlock pending — then enter the code here. "
                    f"Challenge ID: {challenge.challenge_id}"
                ),
            )

        return await self._issue_session(user, access_ctx, identity=identity)

    async def verify_device(
        self,
        body: VerifyDeviceRequest,
        ctx: AccessContext | None = None,
    ) -> LoginResponse:
        """Complete a pending IP challenge and issue tokens."""
        access_ctx = ctx or AccessContext(ip_address="unknown")
        if body.device_fingerprint and not access_ctx.device_fingerprint:
            access_ctx = AccessContext(
                ip_address=access_ctx.ip_address,
                user_agent=access_ctx.user_agent,
                device_fingerprint=body.device_fingerprint,
                request_id=access_ctx.request_id,
                source=access_ctx.source,
            )

        if self._access:
            try:
                await self._access.assert_ip_allowed(access_ctx)
            except IpBlockedError:
                raise AuthenticationError("This IP is blacklisted.") from None

        if self._settings.debug:
            challenge = await auth_challenges.approve_challenge(body.challenge_id)
            if challenge is None:
                raise AuthenticationError("Invalid or expired approval code.")
        else:
            challenge = await auth_challenges.consume_challenge(body.challenge_id, body.code)
            if challenge is None:
                raise AuthenticationError("Invalid or expired approval code.")

        if challenge.ip_address != access_ctx.ip_address and access_ctx.ip_address not in {
            "unknown",
            "127.0.0.1",
            "::1",
        }:
            # Soft check: prefer same IP, but allow if proxy changed slightly only when equal.
            raise AuthenticationError(
                f"Approval code is for IP {challenge.ip_address}, but this request is from "
                f"{access_ctx.ip_address}."
            )

        user = await self._users.get_by_id(UUID(challenge.user_id))
        if user is None or not user.is_active:
            raise AuthenticationError("User not found or inactive.")

        return await self._issue_session(
            user,
            access_ctx,
            identity=challenge.username_or_email,
            trust_ip=challenge.ip_address,
        )

    async def _issue_session(
        self,
        user,
        access_ctx: AccessContext,
        *,
        identity: str,
        trust_ip: str | None = None,
    ) -> LoginResponse:
        user.last_login_at = datetime.now(UTC)
        if access_ctx.ip_address:
            user.last_login_ip = str(access_ctx.ip_address)[:45]
        await self._users.update(user)

        if self._access:
            roles_set = set(user.roles or [])
            is_staff = user.is_superuser or bool(roles_set.intersection(STAFF_ROLE_VALUES))
            # Only staff WHM logins join the admin IP allowlist / SSH trust.
            if is_staff:
                ip = trust_ip or access_ctx.ip_address
                await self._access.trust_authenticated_ip(ip, reason="login_success")
            await self._access.record_login_success(
                access_ctx,
                username_or_email=identity,
                user_id=user.id,
                trust_ip=False,
            )

        roles = user.get_roles()
        scopes = self._roles_to_scopes(roles)
        pair = create_token_pair(self._settings, subject=user.id, scopes=scopes)
        return LoginResponse(
            status="ok",
            access_token=pair.access_token,
            refresh_token=pair.refresh_token,
            expires_in=pair.expires_in,
            ip_address=access_ctx.ip_address,
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
        act_as = self._normalize_act_as(user, payload.act_as_role)
        pair = create_token_pair(
            self._settings,
            subject=user.id,
            scopes=scopes,
            act_as_role=act_as,
        )

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

        act_as = self._normalize_act_as(user, payload.act_as_role)
        return AuthenticatedUser(
            id=user.id,
            email=user.email,
            username=user.username,
            roles=user.roles,
            is_superuser=user.is_superuser,
            scopes=payload.scopes,
            act_as_role=act_as,
        )

    def user_has_permission(self, user: AuthenticatedUser, permission: str) -> bool:
        from app.core.permissions import Permission

        try:
            perm = Permission(permission)
        except ValueError:
            return False

        # Privilege overlay: enforce the lesser staff role only.
        if user.act_as_role:
            try:
                return roles_have_permission([Role(user.act_as_role)], perm)
            except ValueError:
                return False

        if user.is_superuser:
            return True
        roles: list[Role] = []
        for role_str in user.roles:
            try:
                roles.append(Role(role_str))
            except ValueError:
                continue
        return roles_have_permission(roles, perm)

    async def privilege_switch(self, user: AuthenticatedUser, role: str) -> TokenResponse:
        """Superadmin enters a lesser staff privilege view (not client accounts)."""
        db_user = await self._users.get_by_id(user.id)
        if db_user is None or not db_user.is_active:
            raise AuthenticationError("User not found or inactive.")
        if not self._can_privilege_switch(db_user):
            raise AuthorizationError("Only the super admin can switch privileges.")
        role_key = (role or "").strip().lower()
        if role_key not in PRIVILEGE_SWITCH_ROLES:
            raise ValidationError(
                "Choose a staff role: admin, operator, viewer, or customer_care. "
                "Client accounts cannot be used for privilege switch."
            )
        scopes = self._roles_to_scopes(db_user.get_roles())
        pair = create_token_pair(
            self._settings,
            subject=db_user.id,
            scopes=scopes,
            act_as_role=role_key,
        )
        return TokenResponse(
            access_token=pair.access_token,
            refresh_token=pair.refresh_token,
            expires_in=pair.expires_in,
        )

    async def privilege_restore(self, user: AuthenticatedUser) -> TokenResponse:
        """Exit privilege overlay and restore full superadmin powers."""
        db_user = await self._users.get_by_id(user.id)
        if db_user is None or not db_user.is_active:
            raise AuthenticationError("User not found or inactive.")
        if not self._can_privilege_switch(db_user):
            raise AuthorizationError("Only the super admin can restore privileges.")
        scopes = self._roles_to_scopes(db_user.get_roles())
        pair = create_token_pair(self._settings, subject=db_user.id, scopes=scopes)
        return TokenResponse(
            access_token=pair.access_token,
            refresh_token=pair.refresh_token,
            expires_in=pair.expires_in,
        )

    async def confirm_password(self, user: AuthenticatedUser, password: str) -> None:
        db_user = await self._users.get_by_id(user.id)
        if db_user is None or not verify_password(password, db_user.hashed_password):
            raise AuthenticationError("Invalid password.")

    @staticmethod
    def _can_privilege_switch(user) -> bool:
        if getattr(user, "is_superuser", False):
            return True
        roles = {str(r).lower() for r in (getattr(user, "roles", None) or [])}
        return Role.SUPERADMIN.value in roles

    @classmethod
    def _normalize_act_as(cls, user, act_as_role: str | None) -> str | None:
        if not act_as_role:
            return None
        role_key = str(act_as_role).strip().lower()
        if role_key not in PRIVILEGE_SWITCH_ROLES:
            return None
        if not cls._can_privilege_switch(user):
            return None
        return role_key

    @staticmethod
    def _roles_to_scopes(roles: list[str]) -> list[str]:
        scopes: list[str] = []
        for role in roles:
            try:
                scopes.append(Role(role).value)
            except ValueError:
                continue
        return scopes
