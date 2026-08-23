"""Redis-backed HTTP rate limiting middleware."""

from __future__ import annotations

import time

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import JSONResponse

from app.core.config import Environment
from app.core.logging import get_logger
from app.services.security_actions import client_ip
from app.utils import limit_store

logger = get_logger(__name__)


# (path_prefix, methods|None=all, limit, window_seconds)
_AUTH_RULES: list[tuple[str, set[str] | None, int, int]] = [
    ("/api/v1/auth/login", {"POST"}, 20, 60),
    ("/api/v1/auth/verify-device", {"POST"}, 20, 60),
    ("/api/v1/auth/probe", {"POST"}, 40, 60),
    ("/api/v1/auth/refresh", {"POST"}, 40, 60),
    ("/api/v1/auth/password-reset", {"POST"}, 8, 60),
    ("/api/v1/customers/login", {"POST"}, 20, 60),
    ("/api/v1/customers/register", {"POST"}, 10, 60),
    ("/api/v1/customers/verify-email", {"POST"}, 15, 60),
    ("/api/v1/customers/phone/request-otp", {"POST"}, 8, 60),
    ("/api/v1/customers/phone/verify-otp", {"POST"}, 20, 60),
]

_SENSITIVE_BUCKETS = {prefix for prefix, _, _, _ in _AUTH_RULES}


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Fixed-window counters in Redis with file fallback; auth/OTP fail closed if both stores fail."""

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        path = request.url.path
        if not path.startswith("/api/"):
            return await call_next(request)

        try:
            settings = request.app.state.container.config()
        except Exception:  # noqa: BLE001
            return await call_next(request)

        if not getattr(settings, "rate_limit_enabled", True):
            return await call_next(request)

        method = request.method.upper()
        ip = client_ip(request) or "unknown"
        limit, window, bucket = self._match_rule(path, method, settings)
        if limit <= 0:
            return await call_next(request)

        allowed = await self._consume(request, settings, ip=ip, bucket=bucket, limit=limit, window=window)
        if not allowed:
            return JSONResponse(
                status_code=429,
                content={
                    "error": {
                        "code": "rate_limited",
                        "message": "Too many requests. Please wait a moment and try again.",
                    }
                },
                headers={"Retry-After": str(window)},
            )
        return await call_next(request)

    def _match_rule(
        self, path: str, method: str, settings
    ) -> tuple[int, int, str]:
        for prefix, methods, limit, window in _AUTH_RULES:
            if path.startswith(prefix) and (methods is None or method in methods):
                # Allow config override for auth bucket size
                if "password-reset" in prefix:
                    limit = int(getattr(settings, "rate_limit_password_reset_per_minute", limit) or limit)
                elif "login" in prefix or "register" in prefix:
                    limit = int(getattr(settings, "rate_limit_auth_per_minute", limit) or limit)
                return limit, window, prefix
        # General API limit
        default = int(getattr(settings, "rate_limit_default_per_minute", 180) or 180)
        return default, 60, "api"

    async def _consume(
        self,
        request: Request,
        settings,
        *,
        ip: str,
        bucket: str,
        limit: int,
        window: int,
    ) -> bool:
        try:
            redis = request.app.state.container.redis_client()
        except Exception:  # noqa: BLE001
            return self._consume_via_file(settings, ip=ip, bucket=bucket, limit=limit, window=window)

        key = f"ifnotus:rl:{bucket}:{ip}:{int(time.time() // window)}"
        try:
            count = await redis.incr(key)
            if count == 1:
                await redis.expire(key, window + 5)
            return int(count) <= limit
        except Exception as exc:  # noqa: BLE001
            logger.warning("rate_limit_redis_failed", error=str(exc))
            return self._consume_via_file(settings, ip=ip, bucket=bucket, limit=limit, window=window)

    def _consume_via_file(
        self,
        settings,
        *,
        ip: str,
        bucket: str,
        limit: int,
        window: int,
    ) -> bool:
        store_key = f"ifnotus:rl:{bucket}:{ip}"
        allowed, _count = limit_store.incr(store_key, window_seconds=window, limit=limit)
        if allowed:
            return True
        if _count > limit:
            return False
        return self._fail_closed_when_store_unavailable(settings, bucket)

    @staticmethod
    def _fail_closed_when_store_unavailable(settings, bucket: str) -> bool:
        env = getattr(settings, "environment", None)
        is_prod = env == Environment.PRODUCTION or str(env) == "production"
        if is_prod and bucket in _SENSITIVE_BUCKETS:
            logger.warning("rate_limit_fail_closed", bucket=bucket)
            return False
        return True
