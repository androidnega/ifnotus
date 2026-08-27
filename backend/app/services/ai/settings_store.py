"""Persist DeepSeek AI settings on disk (encrypted API key)."""

from __future__ import annotations

import base64
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken

from app.core.config import Settings
from app.core.exceptions import AppException
from app.schemas.ai import AiSettingsResponse, AiSettingsUpdateRequest


class AiSettingsStore:
    """File-backed AI settings under `.ifnotus/settings/ai.json`."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._path = Path(settings.ai_settings_path).resolve()

    def _fernet(self) -> Fernet:
        digest = hashlib.sha256(self._settings.secret_key.encode("utf-8")).digest()
        return Fernet(base64.urlsafe_b64encode(digest))

    def _read_raw(self) -> dict:
        if not self._path.exists():
            return {}
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except (OSError, json.JSONDecodeError):
            return {}

    def _write_raw(self, data: dict) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
        tmp.replace(self._path)

    def get_api_key(self) -> str | None:
        raw = self._read_raw()
        encrypted = raw.get("api_key_encrypted")
        if not encrypted:
            # Fallback to env for bootstrap / ops
            return self._settings.deepseek_api_key
        try:
            return self._fernet().decrypt(encrypted.encode("utf-8")).decode("utf-8")
        except (InvalidToken, ValueError):
            return self._settings.deepseek_api_key

    def get_model(self) -> str:
        raw = self._read_raw()
        return str(raw.get("model") or self._settings.deepseek_model)

    def get_agent_name(self) -> str:
        raw = self._read_raw()
        name = str(raw.get("agent_name") or "").strip()
        return name or "SNR Dev"

    def get_base_url(self) -> str:
        return self._settings.deepseek_base_url.rstrip("/")

    def status(self) -> AiSettingsResponse:
        raw = self._read_raw()
        key = self.get_api_key()
        masked = None
        if key:
            if len(key) <= 8:
                masked = "••••••••"
            else:
                masked = f"{key[:4]}…{key[-4:]}"
        return AiSettingsResponse(
            configured=bool(key),
            model=self.get_model(),
            base_url=self.get_base_url(),
            api_key_masked=masked,
            agent_name=self.get_agent_name(),
            updated_at=raw.get("updated_at"),
        )

    def update(self, body: AiSettingsUpdateRequest) -> AiSettingsResponse:
        raw = self._read_raw()
        if body.clear:
            raw.pop("api_key_encrypted", None)
        elif body.api_key is not None:
            key = body.api_key.strip()
            if not key:
                raise AppException("API key cannot be empty.", code="ai_key_empty")
            raw["api_key_encrypted"] = self._fernet().encrypt(key.encode("utf-8")).decode("utf-8")
        if body.model:
            raw["model"] = body.model.strip()
        if body.agent_name is not None:
            name = body.agent_name.strip()
            if not name:
                raise AppException("Agent name cannot be empty.", code="ai_name_empty")
            if len(name) > 64:
                raise AppException("Agent name is too long.", code="ai_name_too_long")
            raw["agent_name"] = name
        raw["updated_at"] = datetime.now(UTC).isoformat()
        self._write_raw(raw)
        return self.status()
