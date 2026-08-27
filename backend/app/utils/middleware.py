"""HTTP middleware — request context, firewall, action audit."""

from __future__ import annotations

import asyncio
import time
import uuid

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import JSONResponse

from app.core.logging import bind_request_context, get_logger
from app.models.access import SystemActionLog
from app.services.access_control import (
    AccessContext,
    AccessControlService,
    ActionBlockedError,
    DeviceDeniedError,
    IpBlockedError,
    NetworkDeniedError,
)
from app.services.security_actions import (
    client_ip,
    detect_source,
    resolve_action_key,
    should_audit,
)

logger = get_logger(__name__)

_FIREWALL_EXEMPT_PREFIXES = (
    "/api/v1/health",
    "/api/v1/catalog",
    "/api/v1/public",
    # Customer product APIs are not behind staff IP lockdown.
    "/api/v1/customers",
    "/api/v1/auth/login",
    "/api/v1/auth/probe",
    "/api/v1/auth/verify-device",
    "/api/v1/auth/password-reset",
    "/api/v1/auth/me",
    "/api/v1/auth/refresh",
    "/api/v1/auth/logout",
    "/docs",
    "/redoc",
    "/openapi.json",
)


class RequestContextMiddleware(BaseHTTPMiddleware):
    """Attach request ID, enforce network policy, and audit mutating actions."""

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        request_id = request.headers.get("X-Request-ID", str(uuid.uuid4()))
        bind_request_context(
            request_id=request_id,
            method=request.method,
            path=request.url.path,
        )

        start = time.perf_counter()
        path = request.url.path
        method = request.method.upper()
        ip = client_ip(request)
        ua = request.headers.get("user-agent")
        fingerprint = request.headers.get("x-device-fingerprint")
        source = detect_source(ua)
        action_key = resolve_action_key(method, path)

        # Application firewall (allow / deny networks + login blacklist)
        if path.startswith("/api/") and not any(path.startswith(p) for p in _FIREWALL_EXEMPT_PREFIXES):
            try:
                session_factory = request.app.state.container.db_session_factory()
                async with session_factory() as session:
                    access = AccessControlService(session)
                    ctx = AccessContext(
                        ip_address=ip,
                        user_agent=ua,
                        device_fingerprint=fingerprint,
                        request_id=request_id,
                        source=source,
                    )
                    await access.assert_network_allowed(ctx)
                    if method not in {"GET", "HEAD", "OPTIONS"}:
                        await access.assert_action_allowed(action_key)
            except (NetworkDeniedError, DeviceDeniedError, ActionBlockedError, IpBlockedError) as exc:
                await self._audit_denial(
                    request,
                    method=method,
                    path=path,
                    action_key=action_key,
                    ip=ip,
                    ua=ua,
                    source=source,
                    request_id=request_id,
                    exc=exc,
                )
                return JSONResponse(
                    status_code=exc.status_code,
                    content={
                        "error": {
                            "code": exc.code,
                            "message": exc.message,
                            "details": exc.details,
                        }
                    },
                    headers={"X-Request-ID": request_id},
                )
            except Exception:
                # Never block the panel if firewall lookup fails unexpectedly.
                logger.exception("firewall_check_failed", path=path, ip=ip)

        response = await call_next(request)
        duration_ms = (time.perf_counter() - start) * 1000

        logger.info(
            "http_request",
            status_code=response.status_code,
            duration_ms=round(duration_ms, 2),
        )

        # Never open a second DB session here before returning the response.
        # With nested BaseHTTPMiddleware the request session stays checked out
        # until the body is fully streamed; auditing here can deadlock the pool
        # (client hangs forever while we already logged HTTP 200).
        if should_audit(method, path):
            actor_id = None
            actor_name = None
            auth = request.headers.get("authorization") or ""
            if auth.lower().startswith("bearer "):
                try:
                    from app.core.security import decode_token

                    settings = request.app.state.container.config()
                    payload = decode_token(settings, auth.split(" ", 1)[1].strip())
                    actor_id = payload.sub
                    actor_name = getattr(payload, "username", None) or getattr(payload, "email", None)
                except Exception:
                    actor_id = None
            asyncio.create_task(
                self._audit_success(
                    request,
                    method=method,
                    path=path,
                    action_key=action_key,
                    ip=ip,
                    ua=ua,
                    source=source,
                    request_id=request_id,
                    status_code=response.status_code,
                    actor_id=actor_id,
                    actor_name=actor_name,
                )
            )

        response.headers["X-Request-ID"] = request_id
        response.headers["X-Robots-Tag"] = "noindex, nofollow, noarchive"
        return response

    async def _audit_success(
        self,
        request: Request,
        *,
        method: str,
        path: str,
        action_key: str | None,
        ip: str,
        ua: str | None,
        source: str,
        request_id: str,
        status_code: int,
        actor_id: str | None,
        actor_name: str | None,
    ) -> None:
        """Background audit so response delivery is never blocked on DB I/O."""
        try:
            session_factory = request.app.state.container.db_session_factory()
            async with session_factory() as session:
                access = AccessControlService(session)
                if actor_id and not actor_name:
                    try:
                        from app.repositories.user import UserRepository

                        user = await UserRepository(session).get_by_id(actor_id)
                        if user is not None:
                            actor_name = user.username or user.email
                    except Exception:
                        pass
                await access.record_action_log(
                    SystemActionLog(
                        actor_user_id=actor_id,
                        actor_username=actor_name,
                        source=source,
                        method=method,
                        path=path[:512],
                        action_key=action_key,
                        status_code=status_code,
                        ip_address=ip,
                        user_agent=(ua or "")[:512] or None,
                        request_id=request_id,
                        summary=f"{method} {path} → {status_code}",
                        success=200 <= status_code < 400,
                    )
                )
        except Exception:
            logger.exception("action_audit_failed", path=path)

    async def _audit_denial(
        self,
        request: Request,
        *,
        method: str,
        path: str,
        action_key: str | None,
        ip: str,
        ua: str | None,
        source: str,
        request_id: str,
        exc: NetworkDeniedError | ActionBlockedError | IpBlockedError,
    ) -> None:
        """Record refused requests — they never reach the handler otherwise."""
        if not should_audit(method, path):
            return
        try:
            session_factory = request.app.state.container.db_session_factory()
            async with session_factory() as session:
                await AccessControlService(session).record_action_log(
                    SystemActionLog(
                        source=source,
                        method=method,
                        path=path[:512],
                        action_key=action_key,
                        status_code=exc.status_code,
                        ip_address=ip,
                        user_agent=(ua or "")[:512] or None,
                        request_id=request_id,
                        summary=f"{method} {path} → {exc.status_code} ({exc.code})",
                        success=False,
                    )
                )
        except Exception:
            logger.exception("denial_audit_failed", path=path)


class CustomerSafeResponseMiddleware(BaseHTTPMiddleware):
    """Never leak host filesystem layout on customer portal API responses."""

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        response = await call_next(request)
        path = request.url.path
        if not path.startswith("/api/v1/customers"):
            return response

        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["X-Content-Type-Options"] = "nosniff"
        if "cache-control" not in {k.lower() for k in response.headers.keys()}:
            response.headers["Cache-Control"] = "no-store"

        # Do not re-read response.body_iterator here. Nested BaseHTTPMiddleware
        # can deadlock when an outer middleware consumes the body while an inner
        # middleware still holds the request (DB session commit deferred until
        # the body finishes streaming). Path scrubbing still runs in exception
        # handlers via scrub_obj / scrub_host_paths.
        return response
