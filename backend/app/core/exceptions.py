"""Application exception hierarchy and HTTP error mapping."""

from typing import Any

from fastapi import Request, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel


class ErrorDetail(BaseModel):
    """Structured error detail for API responses."""

    code: str
    message: str
    details: dict[str, Any] | None = None


class ErrorResponse(BaseModel):
    """Standard API error envelope."""

    error: ErrorDetail


class AppException(Exception):
    """Base application exception."""

    status_code: int = status.HTTP_500_INTERNAL_SERVER_ERROR
    code: str = "internal_error"
    message: str = "An unexpected error occurred."

    def __init__(
        self,
        message: str | None = None,
        *,
        code: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        self.message = message or self.__class__.message
        self.code = code or self.__class__.code
        self.details = details
        super().__init__(self.message)


class NotFoundError(AppException):
    status_code = status.HTTP_404_NOT_FOUND
    code = "not_found"
    message = "Resource not found."


class ValidationError(AppException):
    status_code = status.HTTP_422_UNPROCESSABLE_CONTENT
    code = "validation_error"
    message = "Validation failed."


class AuthenticationError(AppException):
    status_code = status.HTTP_401_UNAUTHORIZED
    code = "authentication_failed"
    message = "Authentication failed."


class AuthorizationError(AppException):
    status_code = status.HTTP_403_FORBIDDEN
    code = "forbidden"
    message = "Insufficient permissions."


class ConflictError(AppException):
    status_code = status.HTTP_409_CONFLICT
    code = "conflict"
    message = "Resource conflict."


class ServiceUnavailableError(AppException):
    status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    code = "service_unavailable"
    message = "Service temporarily unavailable."


class IntegrationError(AppException):
    status_code = status.HTTP_502_BAD_GATEWAY
    code = "integration_error"
    message = "External integration failed."


def app_exception_handler(_request: Request, exc: AppException) -> JSONResponse:
    """Map AppException to JSON error response."""
    return JSONResponse(
        status_code=exc.status_code,
        content=ErrorResponse(
            error=ErrorDetail(
                code=exc.code,
                message=exc.message,
                details=exc.details,
            )
        ).model_dump(),
    )


def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Catch-all handler for unhandled exceptions."""
    from app.core.logging import get_logger

    logger = get_logger(__name__)
    logger.exception("unhandled_exception", path=request.url.path, exc_type=type(exc).__name__)

    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content=ErrorResponse(
            error=ErrorDetail(
                code="internal_error",
                message="An unexpected error occurred.",
            )
        ).model_dump(),
    )
