"""Per-environment hosting panel color themes (not account / marketing).

Default compact navy is free. Extra packs are sold for a fixed GHS price.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID

from app.core.config import Settings
from app.core.exceptions import AppException, NotFoundError, ValidationError

PANEL_THEME_PRICE_GHS = "2.00"
DEFAULT_PANEL_THEME = "compact-navy"

PANEL_THEMES: dict[str, dict[str, Any]] = {
    "compact-navy": {
        "id": "compact-navy",
        "name": "Compact Navy",
        "description": "Tight spacing with a calm navy accent — included free.",
        "price_ghs": "0",
        "free": True,
        "compact": True,
        "colors": {
            "accent": "#1e3a5f",
            "accent_hover": "#16304d",
            "ink": "#15202b",
            "paper": "#eef1f4",
            "surface": "#ffffff",
            "muted": "#5c6670",
            "border": "#d7dde4",
        },
    },
    "ember-panel": {
        "id": "ember-panel",
        "name": "Ember Panel",
        "description": "Warm orange signal for a brighter hosting workspace.",
        "price_ghs": PANEL_THEME_PRICE_GHS,
        "free": False,
        "compact": True,
        "colors": {
            "accent": "#ff6c2c",
            "accent_hover": "#e85a1c",
            "ink": "#161a1d",
            "paper": "#f4f1ec",
            "surface": "#ffffff",
            "muted": "#6b7280",
            "border": "#e7e2db",
        },
    },
    "ocean-panel": {
        "id": "ocean-panel",
        "name": "Ocean Panel",
        "description": "Cool cyan accents on mist surfaces.",
        "price_ghs": PANEL_THEME_PRICE_GHS,
        "free": False,
        "compact": True,
        "colors": {
            "accent": "#0e7490",
            "accent_hover": "#0f766e",
            "ink": "#0c1b24",
            "paper": "#eef5f7",
            "surface": "#ffffff",
            "muted": "#5b6f7a",
            "border": "#d5e2e8",
        },
    },
    "indigo-panel": {
        "id": "indigo-panel",
        "name": "Indigo Panel",
        "description": "Precise indigo on chalk-white panels.",
        "price_ghs": PANEL_THEME_PRICE_GHS,
        "free": False,
        "compact": True,
        "colors": {
            "accent": "#3730a3",
            "accent_hover": "#312e81",
            "ink": "#1e1b4b",
            "paper": "#f3f2f8",
            "surface": "#ffffff",
            "muted": "#64607a",
            "border": "#ddd9ea",
        },
    },
    "palm-panel": {
        "id": "palm-panel",
        "name": "Palm Panel",
        "description": "Deep green on soft celadon — Accra energy.",
        "price_ghs": PANEL_THEME_PRICE_GHS,
        "free": False,
        "compact": True,
        "colors": {
            "accent": "#047857",
            "accent_hover": "#065f46",
            "ink": "#12241c",
            "paper": "#eef6f1",
            "surface": "#ffffff",
            "muted": "#5c7266",
            "border": "#d5e5db",
        },
    },
}


class HostingPanelThemeStore:
    """File-backed unlocks + active theme per environment."""

    def __init__(self, settings: Settings) -> None:
        path = getattr(settings, "hosting_panel_theme_path", None) or ".ifnotus/settings/hosting_panel_themes.json"
        self._path = Path(path).resolve()

    def _read(self) -> dict[str, Any]:
        if not self._path.exists():
            return {"environments": {}}
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {"environments": {}}
        except (OSError, json.JSONDecodeError):
            return {"environments": {}}

    def _write(self, data: dict[str, Any]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
        tmp.replace(self._path)

    def catalog(self) -> list[dict[str, Any]]:
        return [dict(v) for v in PANEL_THEMES.values()]

    def _env_bucket(self, raw: dict[str, Any], env_id: str) -> dict[str, Any]:
        envs = raw.setdefault("environments", {})
        if not isinstance(envs, dict):
            envs = {}
            raw["environments"] = envs
        bucket = envs.get(env_id)
        if not isinstance(bucket, dict):
            bucket = {"active": DEFAULT_PANEL_THEME, "owned": [DEFAULT_PANEL_THEME]}
            envs[env_id] = bucket
        owned = bucket.get("owned")
        if not isinstance(owned, list):
            owned = [DEFAULT_PANEL_THEME]
        if DEFAULT_PANEL_THEME not in owned:
            owned = [DEFAULT_PANEL_THEME, *owned]
        bucket["owned"] = owned
        active = str(bucket.get("active") or DEFAULT_PANEL_THEME)
        if active not in PANEL_THEMES or active not in owned:
            active = DEFAULT_PANEL_THEME
            bucket["active"] = active
        return bucket

    def status_for(self, environment_id: UUID) -> dict[str, Any]:
        raw = self._read()
        bucket = self._env_bucket(raw, str(environment_id))
        # Persist default bucket so first visit is consistent.
        self._write(raw)
        active = str(bucket["active"])
        theme = PANEL_THEMES[active]
        return {
            "environment_id": str(environment_id),
            "active": active,
            "owned": list(bucket["owned"]),
            "price_ghs": PANEL_THEME_PRICE_GHS,
            "theme": theme,
            "catalog": self.catalog(),
        }

    def set_active(self, environment_id: UUID, theme_id: str) -> dict[str, Any]:
        tid = (theme_id or "").strip().lower()
        if tid not in PANEL_THEMES:
            raise ValidationError("Unknown hosting theme.", code="unknown_panel_theme")
        raw = self._read()
        bucket = self._env_bucket(raw, str(environment_id))
        if tid not in bucket["owned"]:
            raise AppException("Purchase that theme first.", code="panel_theme_locked")
        bucket["active"] = tid
        raw["updated_at"] = datetime.now(UTC).isoformat()
        self._write(raw)
        return self.status_for(environment_id)

    def unlock(self, environment_id: UUID, theme_id: str, *, activate: bool = True) -> dict[str, Any]:
        tid = (theme_id or "").strip().lower()
        if tid not in PANEL_THEMES:
            raise ValidationError("Unknown hosting theme.", code="unknown_panel_theme")
        raw = self._read()
        bucket = self._env_bucket(raw, str(environment_id))
        owned = list(bucket["owned"])
        if tid not in owned:
            owned.append(tid)
        bucket["owned"] = owned
        if activate:
            bucket["active"] = tid
        raw["updated_at"] = datetime.now(UTC).isoformat()
        self._write(raw)
        return self.status_for(environment_id)

    def require_purchasable(self, theme_id: str) -> dict[str, Any]:
        tid = (theme_id or "").strip().lower()
        theme = PANEL_THEMES.get(tid)
        if theme is None:
            raise ValidationError("Unknown hosting theme.", code="unknown_panel_theme")
        if theme.get("free"):
            raise ValidationError("That theme is already free.", code="panel_theme_free")
        return theme
