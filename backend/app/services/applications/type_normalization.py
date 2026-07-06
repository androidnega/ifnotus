"""Normalize legacy application registry type values to canonical enums."""

from __future__ import annotations

import json
from typing import Any

from app.schemas.applications import ApplicationType

CANONICAL_TYPES = {member.value for member in ApplicationType}

TYPE_ALIASES: dict[str, str] = {
    "static": ApplicationType.STATIC_SITE.value,
    "staticsite": ApplicationType.STATIC_SITE.value,
    "static-site": ApplicationType.STATIC_SITE.value,
    "node": ApplicationType.NODEJS.value,
    "nodejs": ApplicationType.NODEJS.value,
    "python": ApplicationType.FASTAPI.value,
    "py": ApplicationType.FASTAPI.value,
    "django": ApplicationType.DJANGO.value,
    "fastapi": ApplicationType.FASTAPI.value,
    "flask": ApplicationType.FASTAPI.value,
    "laravel": ApplicationType.LARAVEL.value,
    "vue": ApplicationType.NODEJS.value,
    "react": ApplicationType.NODEJS.value,
    "nuxt": ApplicationType.NODEJS.value,
    "nextjs": ApplicationType.NODEJS.value,
    "next": ApplicationType.NODEJS.value,
}


def normalize_application_type(value: Any, raw: dict[str, Any] | None = None) -> str:
    """Map YAML `type` values to canonical ApplicationType strings."""
    if value is None:
        raise ValueError("Application type is required.")

    normalized_key = str(value).lower().strip().replace("-", "_")
    if normalized_key in TYPE_ALIASES:
        return TYPE_ALIASES[normalized_key]
    if normalized_key in CANONICAL_TYPES:
        return normalized_key
    if normalized_key == "php":
        return _normalize_php_type(raw)
    if normalized_key in {"html", "htm", "website", "web"}:
        return ApplicationType.STATIC_SITE.value

    # Unknown legacy values: prefer static_site for generic web assets.
    return ApplicationType.STATIC_SITE.value


def _normalize_php_type(raw: dict[str, Any] | None) -> str:
    """Map legacy `php` registry types — Laravel when hinted, else Laravel for VPS PHP stacks."""
    if not raw:
        return ApplicationType.LARAVEL.value

    blob = json.dumps(raw, default=str).lower()
    laravel_hints = ("laravel", "artisan", "composer.json", "livewire", "filament", "quizsnap")
    if any(hint in blob for hint in laravel_hints):
        return ApplicationType.LARAVEL.value
    return ApplicationType.LARAVEL.value


def prepare_registry_dict(raw: dict[str, Any]) -> dict[str, Any]:
    """Return a copy of registry YAML data with normalized type and preserved original."""
    prepared = dict(raw)
    if "type" in prepared:
        original = str(prepared["type"])
        prepared["type"] = normalize_application_type(prepared["type"], prepared)
        if original != prepared["type"]:
            prepared.setdefault("original_type", original)
    return prepared
