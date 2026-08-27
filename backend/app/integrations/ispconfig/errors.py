"""Normalize ISPConfig errors into customer-safe AppExceptions.

Never forward raw SQL / PHP / remoting payloads to browsers.
"""

from __future__ import annotations

import re
from typing import Any

from app.core.exceptions import AppException, NotFoundError, ValidationError
from app.integrations.ispconfig.exceptions import ISPConfigAPIError, ISPConfigNotConfigured

_SAFE_PATTERNS: list[tuple[re.Pattern[str], type[AppException], str, str]] = [
    (
        re.compile(r"no user account|not found|unknown client|does not exist", re.I),
        NotFoundError,
        "provider_resource_not_found",
        "Hosting resource was not found.",
    ),
    (
        re.compile(r"unique|already exists|duplicate|error_unique", re.I),
        ValidationError,
        "provider_conflict",
        "That hosting name or identifier is already in use.",
    ),
    (
        re.compile(
            r"notempty|required|invalid|validation|weak_password|password_error|errmsg",
            re.I,
        ),
        ValidationError,
        "provider_validation_error",
        "Hosting request failed validation. Check the submitted details.",
    ),
    (
        re.compile(r"access denied|permission|not allowed|login_failed", re.I),
        AppException,
        "provider_permission_denied",
        "Hosting operation is not permitted.",
    ),
]


class ProviderOperationError(AppException):
    status_code = 502
    code = "provider_operation_failed"
    message = "Hosting operation failed. Please try again or contact support."


def customer_safe_provider_error(
    exc: BaseException,
    *,
    operation: str,
) -> AppException:
    """Map provider exceptions to API-safe AppExceptions (no raw payload)."""
    if isinstance(exc, ISPConfigNotConfigured):
        return AppException(
            "Hosting engine is not configured.",
            code="provider_not_configured",
            details={"operation": operation},
        )

    raw = str(exc)
    # Strip HTML and truncate for internal logging only (not returned).
    cleaned = re.sub(r"<[^>]+>", " ", raw)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()

    for pattern, exc_cls, code, message in _SAFE_PATTERNS:
        if pattern.search(cleaned):
            return exc_cls(
                message,
                code=code,
                details={"operation": operation},
            )

    if isinstance(exc, ISPConfigAPIError):
        return ProviderOperationError(
            details={"operation": operation},
        )

    return ProviderOperationError(
        details={"operation": operation},
    )


def provider_error_log_fields(exc: BaseException) -> dict[str, Any]:
    """Fields safe for structured server logs (still avoid secrets)."""
    payload: dict[str, Any] = {}
    if isinstance(exc, ISPConfigAPIError):
        payload["status_code"] = exc.status_code
        # Never log full SQL inserts; keep short code/message only.
        msg = str(exc)
        payload["provider_message"] = msg[:240]
    else:
        payload["error_type"] = type(exc).__name__
        payload["provider_message"] = str(exc)[:240]
    return payload
