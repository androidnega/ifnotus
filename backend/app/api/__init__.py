"""API layer — dependency injection and versioned routing."""

from app.api.deps import (
    CurrentUser,
    DbSession,
    RequirePermission,
    SettingsDep,
    get_current_user,
    get_db,
)

__all__ = [
    "CurrentUser",
    "DbSession",
    "RequirePermission",
    "SettingsDep",
    "get_current_user",
    "get_db",
]
