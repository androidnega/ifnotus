"""Persist third-party integration credentials (encrypted secrets on disk).

Staff manage these from Settings — env vars remain a bootstrap fallback only.
"""

from __future__ import annotations

import base64
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from cryptography.fernet import Fernet, InvalidToken

from app.core.config import Settings
from app.core.exceptions import AppException

# Secrets are Fernet-encrypted; everything else stored plaintext in JSON.
SECRET_FIELDS = frozenset(
    {
        "namecheap_api_key",
        "paystack_secret_key",
        "smtp_password",
        "sms_api_key",
        "sms_api_secret",
    }
)

PLAIN_FIELDS = frozenset(
    {
        "namecheap_api_user",
        "namecheap_client_ip",
        "namecheap_api_url",
        "paystack_public_key",
        "paystack_base_url",
        "smtp_host",
        "smtp_port",
        "smtp_username",
        "smtp_from",
        "smtp_use_tls",
        "sms_provider",
        "sms_api_url",
        "sms_sender_id",
        "momo_network",
        "momo_number",
        "momo_account_name",
    }
)

ALL_FIELDS = SECRET_FIELDS | PLAIN_FIELDS


def mask_secret(value: str | None) -> str | None:
    if not value:
        return None
    if len(value) <= 8:
        return "••••••••"
    return f"{value[:4]}…{value[-4:]}"


class IntegrationsSettingsStore:
    """File-backed integrations under `.ifnotus/settings/integrations.json`."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        path = getattr(settings, "integrations_settings_path", None) or ".ifnotus/settings/integrations.json"
        self._path = Path(path).resolve()

    def _fernet(self) -> Fernet:
        digest = hashlib.sha256(self._settings.secret_key.encode("utf-8")).digest()
        return Fernet(base64.urlsafe_b64encode(digest))

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

    def _decrypt(self, token: str | None) -> str | None:
        if not token:
            return None
        try:
            return self._fernet().decrypt(token.encode("utf-8")).decode("utf-8")
        except (InvalidToken, ValueError):
            return None

    def _encrypt(self, value: str) -> str:
        return self._fernet().encrypt(value.encode("utf-8")).decode("utf-8")

    def _env_fallback(self, field: str) -> Any:
        return getattr(self._settings, field, None)

    def get(self, field: str) -> Any:
        if field not in ALL_FIELDS:
            return None
        raw = self._read_raw()
        if field in SECRET_FIELDS:
            enc = raw.get(f"{field}_encrypted")
            if enc:
                decrypted = self._decrypt(str(enc))
                if decrypted is not None:
                    return decrypted
            return self._env_fallback(field)
        if field in raw and raw[field] is not None and raw[field] != "":
            val = raw[field]
            if field == "smtp_port":
                try:
                    return int(val)
                except (TypeError, ValueError):
                    return self._env_fallback(field)
            if field == "smtp_use_tls":
                if isinstance(val, bool):
                    return val
                return str(val).lower() in {"1", "true", "yes", "on"}
            return val
        return self._env_fallback(field)

    def resolved(self) -> Settings:
        """Return Settings with store values overlaid (env as fallback)."""
        update: dict[str, Any] = {}
        for field in ALL_FIELDS:
            val = self.get(field)
            if val is not None and val != "":
                update[field] = val
        return self._settings.model_copy(update=update)

    def status(self) -> dict[str, Any]:
        nc_user = self.get("namecheap_api_user")
        nc_key = self.get("namecheap_api_key")
        nc_ip = self.get("namecheap_client_ip") or self._settings.server_public_ip
        ps_secret = self.get("paystack_secret_key")
        ps_public = self.get("paystack_public_key")
        smtp_host = self.get("smtp_host")
        smtp_pass = self.get("smtp_password")
        sms_provider = (self.get("sms_provider") or "none") or "none"
        sms_key = self.get("sms_api_key")

        raw = self._read_raw()
        return {
            "updated_at": raw.get("updated_at"),
            "namecheap": {
                "configured": bool(nc_user and nc_key and nc_ip),
                "api_user": nc_user or None,
                "api_key_masked": mask_secret(str(nc_key) if nc_key else None),
                "client_ip": nc_ip or None,
                "api_url": self.get("namecheap_api_url") or "https://api.namecheap.com/xml.response",
            },
            "paystack": {
                "configured": bool(ps_secret),
                "public_key": ps_public or None,
                "secret_key_masked": mask_secret(str(ps_secret) if ps_secret else None),
                "base_url": self.get("paystack_base_url") or "https://api.paystack.co",
                "demo_mode": not bool(ps_secret),
            },
            "smtp": {
                "configured": bool(smtp_host),
                "host": smtp_host or None,
                "port": int(self.get("smtp_port") or 587),
                "username": self.get("smtp_username") or None,
                "password_set": bool(smtp_pass),
                "password_masked": mask_secret(str(smtp_pass) if smtp_pass else None),
                "from_address": self.get("smtp_from") or None,
                "use_tls": bool(self.get("smtp_use_tls") if self.get("smtp_use_tls") is not None else True),
            },
            "sms": {
                "provider": str(sms_provider),
                "configured": str(sms_provider).lower() not in {"", "none", "off"}
                and (str(sms_provider).lower() == "log" or bool(sms_key)),
                "api_url": self.get("sms_api_url") or None,
                "api_key_masked": mask_secret(str(sms_key) if sms_key else None),
                "api_secret_set": bool(self.get("sms_api_secret")),
                "sender_id": self.get("sms_sender_id") or "IFNOTUS",
            },
            "momo": {
                "network": self.get("momo_network") or "MTN",
                "number": self.get("momo_number") or "0257940791",
                "account_name": self.get("momo_account_name") or "Emmanuel Kwofie",
            },
        }

    def update(self, payload: dict[str, Any]) -> dict[str, Any]:
        raw = self._read_raw()
        changed = False

        def set_plain(field: str, value: Any) -> None:
            nonlocal changed
            if value is None:
                return
            if isinstance(value, str) and value.strip() == "" and field not in {
                "sms_provider",
                "smtp_from",
                "sms_sender_id",
            }:
                # Empty string clears optional plain fields
                if field in raw:
                    raw.pop(field, None)
                    changed = True
                return
            raw[field] = value
            changed = True

        def set_secret(field: str, value: str | None, *, clear: bool = False) -> None:
            nonlocal changed
            key = f"{field}_encrypted"
            if clear:
                if key in raw:
                    raw.pop(key, None)
                    changed = True
                return
            if value is None:
                return
            text = value.strip()
            if not text:
                raise AppException(f"{field} cannot be empty.", code="integration_empty")
            raw[key] = self._encrypt(text)
            changed = True

        nc = payload.get("namecheap") or {}
        if isinstance(nc, dict):
            if "api_user" in nc:
                set_plain("namecheap_api_user", nc.get("api_user"))
            if "client_ip" in nc:
                set_plain("namecheap_client_ip", nc.get("client_ip"))
            if "api_url" in nc and nc.get("api_url"):
                set_plain("namecheap_api_url", nc.get("api_url"))
            if nc.get("clear_api_key"):
                set_secret("namecheap_api_key", None, clear=True)
            elif "api_key" in nc and nc.get("api_key") is not None:
                set_secret("namecheap_api_key", str(nc.get("api_key")))

        ps = payload.get("paystack") or {}
        if isinstance(ps, dict):
            if "public_key" in ps:
                set_plain("paystack_public_key", ps.get("public_key"))
            if "base_url" in ps and ps.get("base_url"):
                set_plain("paystack_base_url", ps.get("base_url"))
            if ps.get("clear_secret_key"):
                set_secret("paystack_secret_key", None, clear=True)
            elif "secret_key" in ps and ps.get("secret_key") is not None:
                set_secret("paystack_secret_key", str(ps.get("secret_key")))

        smtp = payload.get("smtp") or {}
        if isinstance(smtp, dict):
            for src, dest in (
                ("host", "smtp_host"),
                ("username", "smtp_username"),
                ("from_address", "smtp_from"),
            ):
                if src in smtp:
                    set_plain(dest, smtp.get(src))
            if "port" in smtp and smtp.get("port") is not None:
                set_plain("smtp_port", int(smtp["port"]))
            if "use_tls" in smtp and smtp.get("use_tls") is not None:
                set_plain("smtp_use_tls", bool(smtp["use_tls"]))
            if smtp.get("clear_password"):
                set_secret("smtp_password", None, clear=True)
            elif "password" in smtp and smtp.get("password") is not None:
                set_secret("smtp_password", str(smtp.get("password")))

        sms = payload.get("sms") or {}
        if isinstance(sms, dict):
            for src, dest in (
                ("provider", "sms_provider"),
                ("api_url", "sms_api_url"),
                ("sender_id", "sms_sender_id"),
            ):
                if src in sms:
                    set_plain(dest, sms.get(src))
            if sms.get("clear_api_key"):
                set_secret("sms_api_key", None, clear=True)
            elif "api_key" in sms and sms.get("api_key") is not None:
                set_secret("sms_api_key", str(sms.get("api_key")))
            if sms.get("clear_api_secret"):
                set_secret("sms_api_secret", None, clear=True)
            elif "api_secret" in sms and sms.get("api_secret") is not None:
                set_secret("sms_api_secret", str(sms.get("api_secret")))

        momo = payload.get("momo") or {}
        if isinstance(momo, dict):
            for src, dest in (
                ("network", "momo_network"),
                ("number", "momo_number"),
                ("account_name", "momo_account_name"),
            ):
                if src in momo:
                    set_plain(dest, momo.get(src))

        if not changed:
            return self.status()
        raw["updated_at"] = datetime.now(UTC).isoformat()
        self._write_raw(raw)
        return self.status()

    def import_from_env(self) -> dict[str, Any]:
        """One-shot: copy currently effective env values into the encrypted store."""
        payload: dict[str, Any] = {
            "namecheap": {
                "api_user": self._settings.namecheap_api_user,
                "client_ip": self._settings.namecheap_client_ip or self._settings.server_public_ip,
                "api_url": self._settings.namecheap_api_url,
            },
            "paystack": {
                "public_key": self._settings.paystack_public_key,
                "base_url": self._settings.paystack_base_url,
            },
            "smtp": {
                "host": self._settings.smtp_host,
                "port": self._settings.smtp_port,
                "username": self._settings.smtp_username,
                "from_address": self._settings.smtp_from,
                "use_tls": self._settings.smtp_use_tls,
            },
            "sms": {
                "provider": self._settings.sms_provider or "none",
                "api_url": self._settings.sms_api_url,
                "sender_id": self._settings.sms_sender_id,
            },
        }
        if self._settings.namecheap_api_key:
            payload["namecheap"]["api_key"] = self._settings.namecheap_api_key
        if self._settings.paystack_secret_key:
            payload["paystack"]["secret_key"] = self._settings.paystack_secret_key
        if self._settings.smtp_password:
            payload["smtp"]["password"] = self._settings.smtp_password
        if self._settings.sms_api_key:
            payload["sms"]["api_key"] = self._settings.sms_api_key
        if self._settings.sms_api_secret:
            payload["sms"]["api_secret"] = self._settings.sms_api_secret
        return self.update(payload)
