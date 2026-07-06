"""FastAPI application factory and entry point."""

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1 import api_v1_router
from app.core.config import Settings, get_settings
from app.core.container import Container, create_container
from app.core.events import lifespan
from app.core.exceptions import AppException, app_exception_handler, unhandled_exception_handler
from app.core.openapi import setup_openapi
from app.utils.middleware import RequestContextMiddleware


def create_app(settings: Settings | None = None) -> FastAPI:
    """Application factory — creates and configures the FastAPI instance."""
    settings = settings or get_settings()

    app = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        description="IFNOTUS — Infrastructure and Operations Platform",
        lifespan=lifespan,
        openapi_url=settings.openapi_url if not settings.is_production else None,
        docs_url=settings.docs_url if not settings.is_production else None,
        redoc_url=settings.redoc_url if not settings.is_production else None,
    )

    # Dependency injection container
    container = create_container()
    container.config.override(settings)
    app.state.container = container
    container.wire(
        modules=[
            "app.api.deps",
            "app.routers.v1.auth",
        ]
    )

    # Middleware
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=settings.cors_allow_credentials,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.add_middleware(RequestContextMiddleware)

    # Exception handlers
    app.add_exception_handler(AppException, app_exception_handler)
    app.add_exception_handler(Exception, unhandled_exception_handler)

    # API versioning
    app.include_router(api_v1_router, prefix=f"{settings.api_prefix}{settings.api_v1_prefix}")

    setup_openapi(app, settings)

    return app


def run() -> None:
    """Run the application with uvicorn."""
    settings = get_settings()
    uvicorn.run(
        "app.main:app",
        host=settings.host,
        port=settings.port,
        reload=settings.reload or settings.is_development,
        workers=settings.workers if not settings.is_development else 1,
    )


# ASGI application instance
app = create_app()
