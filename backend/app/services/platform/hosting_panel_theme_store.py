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
        "description": "Clean, compact pale-slate theme with muted borders — default standard.",
        "price_ghs": "0",
        "free": True,
        "compact": True,
        "colors": {
            "accent": "#2b4c7e",
            "accent_hover": "#213b63",
            "ink": "#1e293b",
            "paper": "#f8fafc",
            "surface": "#ffffff",
            "muted": "#64748b",
            "border": "#cbd5e1",
            "sidebar_start": "#141e2e",
            "sidebar_end": "#0f1724",
            "sidebar_text": "#cbd5e1",
            "sidebar_muted": "#64748b",
        },
    },
    "ember-panel": {
        "id": "ember-panel",
        "name": "Ember Studio",
        "description": "Volcanic obsidian and blazing amber-orange for high-energy creators.",
        "price_ghs": PANEL_THEME_PRICE_GHS,
        "free": False,
        "compact": True,
        "colors": {
            "accent": "#ff6c2c",
            "accent_hover": "#e85a1c",
            "ink": "#1c1511",
            "paper": "#f8fafc",
            "surface": "#ffffff",
            "muted": "#786c62",
            "border": "#eddcd0",
            "sidebar_start": "#231814",
            "sidebar_end": "#180f0b",
            "sidebar_text": "#fed7aa",
            "sidebar_muted": "#a88876",
        },
    },
    "ocean-panel": {
        "id": "ocean-panel",
        "name": "Arctic Cyan",
        "description": "Glacier cyan accents on crystalline sea-mist surfaces.",
        "price_ghs": PANEL_THEME_PRICE_GHS,
        "free": False,
        "compact": True,
        "colors": {
            "accent": "#0284c7",
            "accent_hover": "#0369a1",
            "ink": "#0c1b24",
            "paper": "#edf6fa",
            "surface": "#ffffff",
            "muted": "#516f80",
            "border": "#d0e4ee",
            "sidebar_start": "#0f2832",
            "sidebar_end": "#091b22",
            "sidebar_text": "#e0f2fe",
            "sidebar_muted": "#7ca3b5",
        },
    },
    "indigo-panel": {
        "id": "indigo-panel",
        "name": "Cyber Indigo",
        "description": "Ultra-clean violet developer aesthetic with neon indigo signals.",
        "price_ghs": PANEL_THEME_PRICE_GHS,
        "free": False,
        "compact": True,
        "colors": {
            "accent": "#6366f1",
            "accent_hover": "#4f46e5",
            "ink": "#18152e",
            "paper": "#f4f3fb",
            "surface": "#ffffff",
            "muted": "#656185",
            "border": "#dedbf1",
            "sidebar_start": "#1b1738",
            "sidebar_end": "#120e27",
            "sidebar_text": "#e0e7ff",
            "sidebar_muted": "#8f89b7",
        },
    },
    "palm-panel": {
        "id": "palm-panel",
        "name": "Emerald Grove",
        "description": "Lush tropical rainforest green on fresh celadon canvas.",
        "price_ghs": PANEL_THEME_PRICE_GHS,
        "free": False,
        "compact": True,
        "colors": {
            "accent": "#059669",
            "accent_hover": "#047857",
            "ink": "#0f2218",
            "paper": "#edf8f2",
            "surface": "#ffffff",
            "muted": "#547363",
            "border": "#cee6d8",
            "sidebar_start": "#10291d",
            "sidebar_end": "#0a1c13",
            "sidebar_text": "#d1fae5",
            "sidebar_muted": "#77a78e",
        },
    },
    "crimson-panel": {
        "id": "crimson-panel",
        "name": "Royal Crimson",
        "description": "Regal ruby crimson on champagne rose luxury surfaces.",
        "price_ghs": PANEL_THEME_PRICE_GHS,
        "free": False,
        "compact": True,
        "colors": {
            "accent": "#e11d48",
            "accent_hover": "#be123c",
            "ink": "#240e16",
            "paper": "#fdf2f5",
            "surface": "#ffffff",
            "muted": "#7a5260",
            "border": "#f3d0da",
            "sidebar_start": "#2d0f19",
            "sidebar_end": "#1c070e",
            "sidebar_text": "#ffe4e6",
            "sidebar_muted": "#aa7888",
        },
    },
    "solar-gold": {
        "id": "solar-gold",
        "name": "Obsidian Gold",
        "description": "Prestige champagne gold accents against deep obsidian darks.",
        "price_ghs": PANEL_THEME_PRICE_GHS,
        "free": False,
        "compact": True,
        "colors": {
            "accent": "#d97706",
            "accent_hover": "#b45309",
            "ink": "#1a160d",
            "paper": "#fcf8ef",
            "surface": "#ffffff",
            "muted": "#73674f",
            "border": "#ecdfc3",
            "sidebar_start": "#211d13",
            "sidebar_end": "#151209",
            "sidebar_text": "#fef3c7",
            "sidebar_muted": "#9e9071",
        },
    },
    "synthwave-neon": {
        "id": "synthwave-neon",
        "name": "Neon Horizon",
        "description": "Retro-futuristic magenta glow on iridescent mist.",
        "price_ghs": PANEL_THEME_PRICE_GHS,
        "free": False,
        "compact": True,
        "colors": {
            "accent": "#c026d3",
            "accent_hover": "#a21caf",
            "ink": "#240f28",
            "paper": "#fdf2fe",
            "surface": "#ffffff",
            "muted": "#7c5784",
            "border": "#f3d3f6",
            "sidebar_start": "#2c1032",
            "sidebar_end": "#19071e",
            "sidebar_text": "#fae8ff",
            "sidebar_muted": "#b280bd",
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
