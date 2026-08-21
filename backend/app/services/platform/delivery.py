"""Outbound email (SMTP) and SMS delivery for customer notifications."""

from __future__ import annotations

from email.message import EmailMessage
from typing import Any

import httpx

from app.core.config import Settings
from app.core.logging import get_logger

logger = get_logger(__name__)


class MessageDelivery:
    def __init__(self, settings: Settings) -> None:
        from app.services.platform.integrations_store import IntegrationsSettingsStore

        self._settings = IntegrationsSettingsStore(settings).resolved()

    @property
    def email_enabled(self) -> bool:
        return bool(self._settings.smtp_host)

    @property
    def sms_enabled(self) -> bool:
        provider = (self._settings.sms_provider or "none").lower()
        if provider in {"", "none", "off"}:
            return False
        if provider == "log":
            return True
        return bool(self._settings.sms_api_key)

    def send_email(
        self, *, to: str, subject: str, body: str, html: str | None = None
    ) -> dict[str, Any]:
        if not self.email_enabled:
            return {"ok": False, "skipped": True, "reason": "smtp_not_configured"}
        try:
            import smtplib
            import ssl

            msg = EmailMessage()
            msg["Subject"] = subject
            msg["From"] = self._settings.smtp_from or "noreply@ifnotus.space"
            msg["To"] = to
            msg.set_content(body)
            if html:
                msg.add_alternative(html, subtype="html")
            # Local Postfix often presents a hostname-mismatched/self-signed cert.
            tls_ctx = ssl.create_default_context()
            host = (self._settings.smtp_host or "").strip()
            if host in {"127.0.0.1", "localhost", "::1"}:
                tls_ctx.check_hostname = False
                tls_ctx.verify_mode = ssl.CERT_NONE
            with smtplib.SMTP(host, self._settings.smtp_port, timeout=15) as smtp:
                if self._settings.smtp_use_tls:
                    smtp.starttls(context=tls_ctx)
                if self._settings.smtp_username:
                    smtp.login(
                        self._settings.smtp_username,
                        self._settings.smtp_password or "",
                    )
                smtp.send_message(msg)
            logger.info("email_sent", to=to, subject=subject)
            return {"ok": True, "channel": "email"}
        except Exception as exc:  # noqa: BLE001
            logger.warning("email_send_failed", to=to, error=str(exc))
            return {"ok": False, "channel": "email", "error": str(exc)}

    def send_sms(self, *, to: str, body: str) -> dict[str, Any]:
        phone = self._normalize_phone(to)
        if not phone:
            return {"ok": False, "skipped": True, "reason": "invalid_phone"}
        provider = (self._settings.sms_provider or "none").lower()
        if provider in {"", "none", "off"}:
            return {"ok": False, "skipped": True, "reason": "sms_not_configured"}
        if provider == "log":
            logger.info("sms_log_stub", to=phone, body=body[:160])
            return {"ok": True, "channel": "sms", "provider": "log"}
        try:
            if provider == "hubtel":
                return self._send_hubtel(phone, body)
            if provider == "http":
                return self._send_http(phone, body)
            logger.warning("sms_unknown_provider", provider=provider)
            return {"ok": False, "skipped": True, "reason": f"unknown_provider:{provider}"}
        except Exception as exc:  # noqa: BLE001
            logger.warning("sms_send_failed", to=phone, error=str(exc))
            return {"ok": False, "channel": "sms", "error": str(exc)}

    def _send_http(self, phone: str, body: str) -> dict[str, Any]:
        url = self._settings.sms_api_url
        if not url:
            return {"ok": False, "skipped": True, "reason": "sms_api_url_missing"}
        payload = {
            "to": phone,
            "from": self._settings.sms_sender_id or "IFNOTUS",
            "content": body[:320],
            "message": body[:320],
        }
        headers = {"Content-Type": "application/json"}
        if self._settings.sms_api_key:
            headers["Authorization"] = f"Bearer {self._settings.sms_api_key}"
        with httpx.Client(timeout=20) as client:
            resp = client.post(url, headers=headers, json=payload)
        ok = 200 <= resp.status_code < 300
        return {
            "ok": ok,
            "channel": "sms",
            "provider": "http",
            "status_code": resp.status_code,
            "response": resp.text[:300],
        }

    def _send_hubtel(self, phone: str, body: str) -> dict[str, Any]:
        """Hubtel SMS API (common for GHS/Ghana deployments)."""
        client_id = self._settings.sms_api_key or ""
        client_secret = self._settings.sms_api_secret or ""
        sender = self._settings.sms_sender_id or "IFNOTUS"
        base = (self._settings.sms_api_url or "https://smsc.hubtel.com/v1/messages/send").rstrip(
            "/"
        )
        params = {
            "From": sender,
            "To": phone,
            "Content": body[:320],
            "ClientId": client_id,
            "ClientSecret": client_secret,
        }
        with httpx.Client(timeout=20) as client:
            resp = client.get(base, params=params)
        ok = 200 <= resp.status_code < 300
        return {
            "ok": ok,
            "channel": "sms",
            "provider": "hubtel",
            "status_code": resp.status_code,
            "response": resp.text[:300],
        }

    @staticmethod
    def _normalize_phone(raw: str) -> str | None:
        digits = "".join(ch for ch in (raw or "") if ch.isdigit() or ch == "+")
        if digits.startswith("00"):
            digits = "+" + digits[2:]
        if digits.startswith("0") and len(digits) == 10:
            # Ghana local → E.164-ish
            digits = "+233" + digits[1:]
        if len(digits) < 10:
            return None
        return digits
