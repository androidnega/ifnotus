"""Single-use SSO handoff service between ifnotus.space and customer cPanel origins."""

from __future__ import annotations

import asyncio
import json
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from jose import JWTError, jwt
from redis.asyncio import Redis

from app.core.config import Settings
from app.core.exceptions import AppException, AuthenticationError, AuthorizationError, NotFoundError
from app.core.logging import get_logger
from app.core.security import TokenType, create_token_pair
from app.models.auth import User
from app.models.platform import Customer, CustomerDomain, CustomerEnvironment
from app.services.platform.host_routing import classify_host, normalize_host, sanitize_panel_hostname
from app.services.platform.panel_access import control_panel_hostname, site_cpanel_url

logger = get_logger(__name__)

SSO_TOKEN_EXPIRY_SECONDS = 120
_IN_MEMORY_CONSUMED_JTIS: dict[str, float] = {}
_MEMORY_LOCK = asyncio.Lock()


class HostingSsoService:
    def __init__(self, settings: Settings, session: Any) -> None:
        self._settings = settings
        self._session = session

    async def _redis(self) -> Redis | None:
        try:
            client = Redis.from_url(str(self._settings.redis_url), decode_responses=True)
            await client.ping()
            return client
        except Exception as exc:  # noqa: BLE001
            logger.debug("sso_redis_unavailable", error=str(exc))
            return None

    async def _mark_jti_consumed(self, jti: str) -> bool:
        """Atomically mark JTI consumed. Returns True if successfully claimed, False if already used."""
        redis = await self._redis()
        if redis is not None:
            try:
                key = f"sso_jti:{jti}"
                # set nx with ex: returns True only if key was NOT present
                res = await redis.set(key, "1", ex=SSO_TOKEN_EXPIRY_SECONDS * 2, nx=True)
                await redis.aclose()
                return bool(res)
            except Exception as exc:  # noqa: BLE001
                logger.warning("sso_redis_jti_failed", error=str(exc))
                if redis is not None:
                    await redis.aclose()

        # In-memory single-use fallback
        async with _MEMORY_LOCK:
            now = datetime.now(UTC).timestamp()
            # Clean expired
            expired = [k for k, exp in _IN_MEMORY_CONSUMED_JTIS.items() if exp < now]
            for k in expired:
                _IN_MEMORY_CONSUMED_JTIS.pop(k, None)

            if jti in _IN_MEMORY_CONSUMED_JTIS:
                return False
            _IN_MEMORY_CONSUMED_JTIS[jti] = now + (SSO_TOKEN_EXPIRY_SECONDS * 2)
            return True

    async def create_handoff(
        self,
        user: User,
        *,
        environment_id: UUID | None = None,
        domain: str | None = None,
        tab: str | None = None,
    ) -> dict[str, Any]:
        """Create a single-use signed SSO token for cross-origin customer cPanel login."""
        from sqlalchemy import func, select
        from app.services.platform.customers import CustomerService

        customer = await CustomerService(self._settings, self._session).require_for_user(user.id)
        env: CustomerEnvironment | None = None

        if environment_id:
            env = await self._session.get(CustomerEnvironment, environment_id)
            if env is None or env.customer_id != customer.id:
                raise NotFoundError("Hosting environment not found.")
        elif domain:
            safe = sanitize_panel_hostname(domain)
            if not safe:
                raise AppException("Invalid domain name.", code="domain_invalid")
            lookup = safe.lower().rstrip(".")
            if lookup.startswith("cpanel."):
                lookup = lookup[len("cpanel.") :]
            if lookup.startswith("www."):
                lookup = lookup[4:]

            env = (
                await self._session.execute(
                    select(CustomerEnvironment).where(
                        CustomerEnvironment.customer_id == customer.id,
                        func.lower(CustomerEnvironment.domain) == lookup,
                    )
                )
            ).scalar_one_or_none()
            if env is None:
                owned = (
                    await self._session.execute(
                        select(CustomerDomain).where(
                            CustomerDomain.customer_id == customer.id,
                            func.lower(CustomerDomain.domain_name) == lookup,
                        )
                    )
                ).scalar_one_or_none()
                if owned is not None and owned.environment_id:
                    env = await self._session.get(CustomerEnvironment, owned.environment_id)

        if env is None:
            # Fall back to customer's active environment
            env = (
                await self._session.execute(
                    select(CustomerEnvironment)
                    .where(
                        CustomerEnvironment.customer_id == customer.id,
                        CustomerEnvironment.status.in_(["active", "ready", "provisioned", "pending"]),
                    )
                    .order_by(CustomerEnvironment.created_at.desc())
                )
            ).scalars().first()

        if env is None:
            raise NotFoundError("No active hosting environment found for this account.")

        if env.status in {"terminated", "terminating"}:
            raise AppException("This hosting service is no longer active.", code="env_terminated")

        domain_name = (env.domain or domain or "").strip().lower()
        if not domain_name:
            raise AppException("Hosting environment has no associated domain.", code="env_no_domain")

        cpanel_host = control_panel_hostname(domain_name) or domain_name
        jti = str(uuid.uuid4())
        now = datetime.now(UTC)
        expire = now + timedelta(seconds=SSO_TOKEN_EXPIRY_SECONDS)

        payload = {
            "sub": str(user.id),
            "type": "sso_handoff",
            "jti": jti,
            "environment_id": str(env.id),
            "customer_id": str(customer.id),
            "domain": domain_name,
            "cpanel_host": cpanel_host,
            "tab": tab or "",
            "iat": now,
            "exp": expire,
        }

        sso_token = jwt.encode(payload, self._settings.secret_key, algorithm=self._settings.jwt_algorithm)

        handoff_url = f"https://{cpanel_host}/sso?token={sso_token}"
        if tab:
            handoff_url += f"&tab={tab}"

        return {
            "handoff_url": handoff_url,
            "token": sso_token,
            "target_host": cpanel_host,
            "environment_id": env.id,
            "domain": domain_name,
            "expires_in": SSO_TOKEN_EXPIRY_SECONDS,
        }

    async def consume_handoff(
        self,
        token: str,
        *,
        requested_host: str | None = None,
    ) -> dict[str, Any]:
        """Validate and atomically consume a single-use SSO handoff token."""
        from sqlalchemy import select

        if not token:
            raise AuthenticationError("SSO token is required.")

        try:
            data = jwt.decode(
                token,
                self._settings.secret_key,
                algorithms=[self._settings.jwt_algorithm],
            )
        except (JWTError, KeyError, ValueError) as exc:
            raise AuthenticationError("Invalid or expired SSO token.") from exc

        if data.get("type") != "sso_handoff":
            raise AuthenticationError("Invalid token type.")

        jti = data.get("jti")
        if not jti:
            raise AuthenticationError("Malformed SSO token.")

        # Atomic single-use claim
        claimed = await self._mark_jti_consumed(jti)
        if not claimed:
            raise AuthenticationError("SSO token has already been used.")

        user_id = UUID(data["sub"])
        env_id = UUID(data["environment_id"])
        token_domain = str(data.get("domain") or "").strip().lower()
        token_cpanel = str(data.get("cpanel_host") or "").strip().lower()

        # Host matching validation
        if requested_host:
            host_clean = normalize_host(requested_host)
            apex = host_clean
            if apex.startswith("cpanel."):
                apex = apex[len("cpanel.") :]
            if apex.startswith("www."):
                apex = apex[4:]

            if token_domain != apex and token_cpanel != host_clean and host_clean != "localhost" and not host_clean.startswith("127.0.0.1"):
                logger.warning(
                    "sso_host_mismatch",
                    token_domain=token_domain,
                    requested_host=requested_host,
                )

        user = await self._session.get(User, user_id)
        if user is None or not user.is_active:
            raise AuthenticationError("Account is inactive or not found.")

        env = await self._session.get(CustomerEnvironment, env_id)
        if env is None or env.status in {"terminated", "terminating"}:
            raise NotFoundError("Hosting environment is no longer available.")

        # Mint regular session tokens
        tokens = create_token_pair(self._settings, subject=user.id)

        return {
            "access_token": tokens.access_token,
            "refresh_token": tokens.refresh_token,
            "token_type": tokens.token_type,
            "expires_in": tokens.expires_in,
            "environment_id": env.id,
            "domain": env.domain or token_domain,
            "username": env.hosting_name or user.email,
        }
