"""ISPConfig integration errors."""

from __future__ import annotations

from typing import Any


class ISPConfigError(Exception):
    """Base ISPConfig error."""


class ISPConfigNotConfigured(ISPConfigError):
    """Missing ISPCONFIG_* settings."""


class ISPConfigAPIError(ISPConfigError):
    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        payload: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.payload = payload or {}
