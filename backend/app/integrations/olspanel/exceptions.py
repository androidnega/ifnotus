"""OLSPanel integration errors."""

from __future__ import annotations

from typing import Any

from fastapi import status

from app.core.exceptions import IntegrationError, ServiceUnavailableError


class OLSPanelNotConfigured(ServiceUnavailableError):
    code = "olspanel_not_configured"
    message = "OLSPanel is not configured."


class OLSPanelAPIError(IntegrationError):
    code = "olspanel_api_error"
    message = "OLSPanel API request failed."
    status_code = status.HTTP_502_BAD_GATEWAY

    def __init__(
        self,
        message: str | None = None,
        *,
        code: str | None = None,
        details: dict[str, Any] | None = None,
        payload: dict[str, Any] | None = None,
        status_code: int | None = None,
    ) -> None:
        merged = dict(details or {})
        if payload:
            merged["olspanel"] = payload
        super().__init__(message, code=code, details=merged or None)
        if status_code is not None:
            self.status_code = status_code
        self.payload = payload or {}
