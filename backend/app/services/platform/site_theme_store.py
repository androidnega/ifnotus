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

THEMES: dict[str, dict[str, Any]] = {
    "studio-light": {
        "id": "studio-light",
        "name": "Studio Light",
        "description": "Warm paper + IFNOTUS orange — default brand look.",
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
        "name": "Ocean Clean",
        "description": "Cool teal accents on soft gray — crisp hosting console.",
        "home_scroll": False,
        "colors": {
            "primary": "#0e7490",
            "primary_hover": "#0f766e",
            "ink": "#0f172a",
            "paper": "#f1f5f9",
            "surface": "#ffffff",
            "muted": "#64748b",
            "border": "#e2e8f0",
        },
    },
    "graphite": {
        "id": "graphite",
        "name": "Graphite Ember",
        "description": "Charcoal UI with ember accent — focused operator feel.",
        "home_scroll": False,
        "colors": {
            "primary": "#ea580c",
            "primary_hover": "#c2410c",
            "ink": "#0f172a",
            "paper": "#eef2f6",
            "surface": "#ffffff",
            "muted": "#64748b",
            "border": "#dbe3ec",
        },
    },
    "server-dark": {
        "id": "server-dark",
        "name": "Server Dark",
        "description": "Dark cinematic surfaces for marketing + night ops.",
        "home_scroll": False,
        "colors": {
            "primary": "#fb923c",
            "primary_hover": "#f97316",
            "ink": "#f8fafc",
            "paper": "#0b1120",
            "surface": "#111827",
            "muted": "#94a3b8",
            "border": "#1e293b",
        },
    },
}

# Package tiers → accent (customers inherit from their active plan price).
DEFAULT_PLAN_COLORS: dict[str, dict[str, str]] = {
    "starter": {"id": "starter", "label": "Starter", "max_price": "40", "accent": "#0f766e"},
    "growth": {"id": "growth", "label": "Growth", "max_price": "80", "accent": "#0369a1"},
    "pro": {"id": "pro", "label": "Pro", "max_price": "160", "accent": "#c2410c"},
    "power": {"id": "power", "label": "Power", "max_price": "99999", "accent": "#1e3a5f"},
}

DEFAULT_THEME = "studio-light"


def _normalize_hex(value: str | None, fallback: str) -> str:
    raw = (value or "").strip()
    if not _HEX.match(raw):
        return fallback
    if len(raw) == 4:
        return "#" + "".join(ch * 2 for ch in raw[1:])
    return raw.lower()


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
        theme = str(raw.get("theme") or DEFAULT_THEME).strip().lower()
        return theme if theme in THEMES else DEFAULT_THEME

    def _merged_colors(self, theme_id: str, raw: dict[str, Any] | None = None) -> dict[str, str]:
        raw = raw if raw is not None else self._read_raw()
        base = dict(THEMES[theme_id]["colors"])
        custom = raw.get("colors") if isinstance(raw.get("colors"), dict) else {}
        out: dict[str, str] = {}
        for key in COLOR_KEYS:
            out[key] = _normalize_hex(str(custom.get(key) or ""), base[key])
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
        return {
            "theme": active,
            "themes": themes,
            "colors": colors,
            "plan_colors": plan_colors,
            "updated_at": raw.get("updated_at"),
        }

    def update(
        self,
        theme_id: str,
        *,
        colors: dict[str, str] | None = None,
        plan_colors: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        cleaned = (theme_id or "").strip().lower()
        if cleaned not in THEMES:
            raise AppException(
                f"Unknown theme '{theme_id}'. Choose: {', '.join(THEMES)}",
                code="unknown_site_theme",
            )
        raw = self._read_raw()
        raw["theme"] = cleaned

        if colors is not None:
            cleaned_colors: dict[str, str] = {}
            base = THEMES[cleaned]["colors"]
            for key in COLOR_KEYS:
                if key in colors and colors[key] is not None:
                    cleaned_colors[key] = _normalize_hex(str(colors[key]), base[key])
            # Keep previous custom keys not sent? Prefer replace subset merge.
            prev = raw.get("colors") if isinstance(raw.get("colors"), dict) else {}
            merged = {**prev, **cleaned_colors}
            raw["colors"] = {k: merged[k] for k in COLOR_KEYS if k in merged}

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

        raw["updated_at"] = datetime.now(UTC).isoformat()
        self._write_raw(raw)
        return self.status()
