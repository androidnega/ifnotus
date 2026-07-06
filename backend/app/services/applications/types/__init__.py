"""Application type adapters."""

from app.services.applications.types.base import (
    ADAPTERS,
    BaseApplicationAdapter,
    DjangoAdapter,
    FastAPIAdapter,
    LaravelAdapter,
    NodeJSAdapter,
    StaticSiteAdapter,
    get_adapter,
)

__all__ = [
    "ADAPTERS",
    "BaseApplicationAdapter",
    "DjangoAdapter",
    "FastAPIAdapter",
    "LaravelAdapter",
    "NodeJSAdapter",
    "StaticSiteAdapter",
    "get_adapter",
]
