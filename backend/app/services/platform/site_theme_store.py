"""Public + panel theme settings (staff-switchable colors)."""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.core.config import Settings
from app.core.exceptions import AppException

_HEX = re.compile(r"^#([0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")

COLOR_KEYS = (
    "primary",
    "primary_hover",
    "ink",
    "paper",
    "surface",
    "muted",
    "border",
)

# Four light themes only — used across marketing, portal, and staff control UI.
THEMES: dict[str, dict[str, Any]] = {
    "studio-light": {
        "id": "studio-light",
        "name": "Ember Studio",
        "description": "Warm linen paper with IFNOTUS orange — the default brand.",
        "home_scroll": False,
        "colors": {
            "primary": "#ff6c2c",
            "primary_hover": "#e85a1c",
            "ink": "#161a1d",
            "paper": "#f4f1ec",
            "surface": "#ffffff",
            "muted": "#6b7280",
            "border": "#e7e2db",
        },
    },
    "ocean-clean": {
        "id": "ocean-clean",
        "name": "Atlantic Mist",
        "description": "Cool mist surfaces with deep cyan — crisp and coastal.",
        "home_scroll": False,
        "colors": {
            "primary": "#0e7490",
            "primary_hover": "#0f766e",
            "ink": "#0c1b24",
            "paper": "#eef5f7",
            "surface": "#ffffff",
            "muted": "#5b6f7a",
            "border": "#d5e2e8",
        },
    },
    "graphite": {
        "id": "graphite",
        "name": "Baobab Indigo",
        "description": "Chalk-white panels with indigo signal — calm and precise.",
        "home_scroll": False,
        "colors": {
            "primary": "#3730a3",
            "primary_hover": "#312e81",
            "ink": "#1e1b4b",
            "paper": "#f3f2f8",
            "surface": "#ffffff",
            "muted": "#64607a",
            "border": "#ddd9ea",
        },
    },
    "palm-grove": {
        "id": "palm-grove",
        "name": "Palm Grove",
        "description": "Soft celadon paper with deep green — grounded Accra energy.",
        "home_scroll": False,
        "colors": {
            "primary": "#047857",
            "primary_hover": "#065f46",
            "ink": "#12241c",
            "paper": "#eef6f1",
            "surface": "#ffffff",
            "muted": "#5c7266",
            "border": "#d5e5db",
        },
    },
}

# Legacy id → current light theme (dark pack retired).
_THEME_ALIASES = {
    "server-dark": "studio-light",
    "ember-studio": "studio-light",
    "atlantic-mist": "ocean-clean",
    "baobab-indigo": "graphite",
    "palm": "palm-grove",
}

# Package tiers → accent (customers inherit from their active plan price).
DEFAULT_PLAN_COLORS: dict[str, dict[str, str]] = {
    "starter": {"id": "starter", "label": "Starter", "max_price": "40", "accent": "#0f766e"},
    "growth": {"id": "growth", "label": "Growth", "max_price": "80", "accent": "#0369a1"},
    "pro": {"id": "pro", "label": "Pro", "max_price": "160", "accent": "#c2410c"},
    "power": {"id": "power", "label": "Power", "max_price": "99999", "accent": "#1e3a5f"},
}

DEFAULT_THEME = "studio-light"

HOME_LAYOUTS: dict[str, dict[str, str]] = {
    "split-right": {
        "id": "split-right",
        "name": "Split with image",
        "description": "Copy on the left, hero image on the right.",
    },
    "centered": {
        "id": "centered",
        "name": "Centered domain check",
        "description": "Classic centered hero with domain checker.",
    },
    "bold-band": {
        "id": "bold-band",
        "name": "Bold accent band",
        "description": "Full-bleed brand band with domain tools below.",
    },
}
DEFAULT_HOME_LAYOUT = "split-right"


def _normalize_hex(value: str | None, fallback: str) -> str:
    raw = (value or "").strip()
    if not _HEX.match(raw):
        return fallback
    if len(raw) == 4:
        return "#" + "".join(ch * 2 for ch in raw[1:])
    return raw.lower()


def resolve_theme_id(raw_id: str | None) -> str:
    theme = str(raw_id or DEFAULT_THEME).strip().lower()
    theme = _THEME_ALIASES.get(theme, theme)
    return theme if theme in THEMES else DEFAULT_THEME


class SiteThemeStore:
    """File-backed site theme under `.ifnotus/settings/site_theme.json`."""

    def __init__(self, settings: Settings) -> None:
        path = getattr(settings, "site_theme_settings_path", None) or ".ifnotus/settings/site_theme.json"
        self._path = Path(path).resolve()

    def _read_raw(self) -> dict[str, Any]:
        if not self._path.exists():
            return {}
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except (OSError, json.JSONDecodeError):
            return {}

    def _write_raw(self, data: dict[str, Any]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
        tmp.replace(self._path)

    def active_id(self) -> str:
        raw = self._read_raw()
        return resolve_theme_id(str(raw.get("theme") or DEFAULT_THEME))

    def _merged_colors(self, theme_id: str, raw: dict[str, Any] | None = None) -> dict[str, str]:
        raw = raw if raw is not None else self._read_raw()
        base = dict(THEMES[theme_id]["colors"])
        # Only apply custom color overrides when they were saved for this same theme.
        saved_for = resolve_theme_id(str(raw.get("theme") or theme_id))
        custom = raw.get("colors") if isinstance(raw.get("colors"), dict) else {}
        out: dict[str, str] = {}
        for key in COLOR_KEYS:
            if saved_for == theme_id and custom.get(key):
                out[key] = _normalize_hex(str(custom.get(key) or ""), base[key])
            else:
                out[key] = base[key]
        return out

    def _merged_plan_colors(self, raw: dict[str, Any] | None = None) -> list[dict[str, str]]:
        raw = raw if raw is not None else self._read_raw()
        custom = raw.get("plan_colors") if isinstance(raw.get("plan_colors"), dict) else {}
        out: list[dict[str, str]] = []
        for tier_id, tier in DEFAULT_PLAN_COLORS.items():
            accent = _normalize_hex(str(custom.get(tier_id) or ""), tier["accent"])
            out.append(
                {
                    "id": tier_id,
                    "label": tier["label"],
                    "max_price": tier["max_price"],
                    "accent": accent,
                }
            )
        return out

    def status(self) -> dict[str, Any]:
        raw = self._read_raw()
        active = self.active_id()
        colors = self._merged_colors(active, raw)
        plan_colors = self._merged_plan_colors(raw)
        themes = []
        for theme in THEMES.values():
            themes.append(
                {
                    "id": theme["id"],
                    "name": theme["name"],
                    "description": theme["description"],
                    "home_scroll": bool(theme.get("home_scroll")),
                    "colors": theme["colors"],
                }
            )
        layout = str(raw.get("home_layout") or DEFAULT_HOME_LAYOUT).strip().lower()
        if layout not in HOME_LAYOUTS:
            layout = DEFAULT_HOME_LAYOUT
        return {
            "theme": active,
            "themes": themes,
            "colors": colors,
            "plan_colors": plan_colors,
            "home_layout": layout,
            "home_layouts": list(HOME_LAYOUTS.values()),
            "maintenance_mode": bool(raw.get("maintenance_mode")),
            "maintenance_message": str(
                raw.get("maintenance_message")
                or "IFNOTUS is under scheduled maintenance. Please check back shortly."
            ).strip(),
            "updated_at": raw.get("updated_at"),
        }

    def update(
        self,
        theme_id: str,
        *,
        colors: dict[str, str] | None = None,
        plan_colors: dict[str, str] | None = None,
        home_layout: str | None = None,
        maintenance_mode: bool | None = None,
        maintenance_message: str | None = None,
    ) -> dict[str, Any]:
        requested = (theme_id or "").strip().lower()
        cleaned = resolve_theme_id(requested)
        if requested and requested not in THEMES and requested not in _THEME_ALIASES:
            raise AppException(
                f"Unknown theme '{theme_id}'. Choose: {', '.join(THEMES)}",
                code="unknown_site_theme",
            )
        if cleaned not in THEMES:
            raise AppException(
                f"Unknown theme '{theme_id}'. Choose: {', '.join(THEMES)}",
                code="unknown_site_theme",
            )
        raw = self._read_raw()
        prev = resolve_theme_id(str(raw.get("theme") or DEFAULT_THEME))
        raw["theme"] = cleaned

        if colors is not None:
            cleaned_colors: dict[str, str] = {}
            base = THEMES[cleaned]["colors"]
            for key in COLOR_KEYS:
                if key in colors and colors[key] is not None:
                    cleaned_colors[key] = _normalize_hex(str(colors[key]), base[key])
            prev_colors = raw.get("colors") if isinstance(raw.get("colors"), dict) else {}
            merged = {**prev_colors, **cleaned_colors} if prev == cleaned else cleaned_colors
            raw["colors"] = {k: merged[k] for k in COLOR_KEYS if k in merged}
        elif prev != cleaned:
            # Switching preset without explicit colors → adopt the new palette fully.
            raw["colors"] = dict(THEMES[cleaned]["colors"])

        if plan_colors is not None:
            prev_pc = raw.get("plan_colors") if isinstance(raw.get("plan_colors"), dict) else {}
            next_pc = dict(prev_pc)
            for tier_id, accent in plan_colors.items():
                if tier_id not in DEFAULT_PLAN_COLORS:
                    continue
                next_pc[tier_id] = _normalize_hex(
                    str(accent), DEFAULT_PLAN_COLORS[tier_id]["accent"]
                )
            raw["plan_colors"] = next_pc

        if home_layout is not None:
            layout = str(home_layout).strip().lower()
            if layout not in HOME_LAYOUTS:
                raise AppException(
                    f"Unknown home layout. Choose: {', '.join(HOME_LAYOUTS)}",
                    code="unknown_home_layout",
                )
            raw["home_layout"] = layout

        if maintenance_mode is not None:
            raw["maintenance_mode"] = bool(maintenance_mode)
        if maintenance_message is not None:
            msg = str(maintenance_message).strip()
            raw["maintenance_message"] = msg[:500] if msg else (
                "IFNOTUS is under scheduled maintenance. Please check back shortly."
            )

        raw["updated_at"] = datetime.now(UTC).isoformat()
        self._write_raw(raw)
        return self.status()
