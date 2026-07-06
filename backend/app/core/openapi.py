"""OpenAPI schema customization."""

from typing import Any

from fastapi import FastAPI
from fastapi.openapi.utils import get_openapi

from app.core.config import Settings


def custom_openapi(app: FastAPI, settings: Settings) -> dict[str, Any]:
    """Generate customized OpenAPI schema."""
    if app.openapi_schema:
        return app.openapi_schema

    schema = get_openapi(
        title=settings.app_name,
        version=settings.app_version,
        description=(
            "IFNOTUS — Infrastructure and Operations Platform API.\n\n"
            "Combines infrastructure monitoring, server management, deployment automation, "
            "application management, and email administration."
        ),
        routes=app.routes,
        tags=[
            {"name": "health", "description": "Health and readiness probes"},
            {"name": "monitoring", "description": "Platform monitoring endpoints"},
            {"name": "auth", "description": "Authentication and session management"},
            {"name": "system", "description": "System information and configuration"},
        ],
    )

    schema["info"]["x-logo"] = {
        "url": "https://ifnotus.io/logo.png",
        "altText": settings.app_name,
    }

    # Security scheme
    schema.setdefault("components", {}).setdefault("securitySchemes", {})["BearerAuth"] = {
        "type": "http",
        "scheme": "bearer",
        "bearerFormat": "JWT",
        "description": "JWT access token obtained via `/api/v1/auth/login`.",
    }

    schema["security"] = [{"BearerAuth": []}]

    app.openapi_schema = schema
    return app.openapi_schema


def setup_openapi(app: FastAPI, settings: Settings) -> None:
    """Attach custom OpenAPI generator to the app."""

    def openapi() -> dict[str, Any]:
        return custom_openapi(app, settings)

    app.openapi = openapi  # type: ignore[method-assign]
