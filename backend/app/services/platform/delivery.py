"""Outbound email (SMTP) and SMS delivery for customer notifications."""

from __future__ import annotations

import re
import secrets
from email.message import EmailMessage
from email.utils import formataddr, formatdate, make_msgid
from typing import Any

import httpx

from app.core.config import Settings
from app.core.logging import get_logger

logger = get_logger(__name__)

_FROM_ADDR_RE = re.compile(r"<([^>]+)>")


class MessageDelivery:
    def __init__(self, settings: Settings) -> None:
        from app.services.platform.integrations_store import IntegrationsSettingsStore

        self._settings = IntegrationsSettingsStore(settings).resolved()
        self._raw_settings = settings

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

    def _from_header(self) -> str:
        raw = (self._settings.smtp_from or "noreply@ifnotus.space").strip()
        if "<" in raw and ">" in raw:
            return raw
        return formataddr(("IFNOTUS", raw))

    def _from_domain(self) -> str:
        raw = (self._settings.smtp_from or "noreply@ifnotus.space").strip()
        m = _FROM_ADDR_RE.search(raw)
        addr = (m.group(1) if m else raw).strip()
        if "@" in addr:
            return addr.split("@", 1)[1].lower()
        return "ifnotus.space"

    def _reply_to(self) -> str | None:
        support = (getattr(self._raw_settings, "support_email", None) or "").strip()
        if support and "@" in support:
            return formataddr(("IFNOTUS Support", support))
        return None

    def send_email(
        self,
        *,
        to: str,
        subject: str,
        body: str,
        html: str | None = None,
        reply_to: str | None = None,
    ) -> dict[str, Any]:
        if not self.email_enabled:
            return {"ok": False, "skipped": True, "reason": "smtp_not_configured"}
        try:
            import smtplib
            import ssl

            # Keep subjects calm and brand-prefixed for inbox trust.
            clean_subject = (subject or "").strip() or "IFNOTUS update"
            if not clean_subject.upper().startswith("IFNOTUS"):
                clean_subject = f"IFNOTUS — {clean_subject}"

            msg = EmailMessage()
            msg["Subject"] = clean_subject
            msg["From"] = self._from_header()
            msg["To"] = to
            msg["Date"] = formatdate(localtime=True)
            msg["Message-ID"] = make_msgid(
                idstring=secrets.token_hex(8),
                domain=self._from_domain(),
            )
            rt = reply_to or self._reply_to()
            if rt:
                msg["Reply-To"] = rt
            # Transactional headers — help filters treat this as account mail, not promo.
            msg["Auto-Submitted"] = "auto-generated"
            msg["X-Auto-Response-Suppress"] = "All"
            msg["X-Mailer"] = "IFNOTUS-Platform/1"
            msg.set_content(body or " ")
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
            logger.info("email_sent", to=to, subject=clean_subject)
            return {"ok": True, "channel": "email"}
        except Exception as exc:  # noqa: BLE001
            logger.warning("email_send_failed", to=to, error=str(exc))
            return {"ok": False, "channel": "email", "error": str(exc)}

    def mirror_sms_to_email(
        self,
        *,
        to_email: str | None,
        sms_body: str,
        subject: str | None = None,
    ) -> dict[str, Any]:
        """Send the same alert content by email whenever SMS is used."""
        email = (to_email or "").strip().lower()
        if not email or email.endswith("@phone.pending.ifnotus"):
            return {"ok": False, "skipped": True, "reason": "no_email"}
        from app.services.platform import email_templates

        title = (subject or "Account alert").strip()
        _t, text, html = email_templates.operator_alert(subject=title, body=sms_body)
        return self.send_email(to=email, subject=_t, body=text, html=html)

    def send_sms(self, *, to: str, body: str) -> dict[str, Any]:
        phone = self._normalize_phone(to)
        if not phone:
            return {"ok": False, "skipped": True, "reason": "invalid_phone"}
        # Brand is the SMS sender ID — do not also put IFNOTUS in the body.
        body = re.sub(r"(?i)^\s*IFNOTUS(?:\s*tip)?\s*[:\-–—]\s*", "", (body or "").strip())
        provider = (self._settings.sms_provider or "none").lower()
        if provider in {"", "none", "off"}:
            return {"ok": False, "skipped": True, "reason": "sms_not_configured"}
        if provider == "log":
            logger.info("sms_log_stub", to=phone, body=body[:160])
            return {"ok": True, "channel": "sms", "provider": "log"}

        primary = self._dispatch_sms(provider, phone, body)
        if primary.get("ok") or primary.get("skipped"):
            return primary

        fallback = self._try_moolre_fallback(phone, body, primary_provider=provider)
        if fallback is not None:
            return fallback
        return primary

    def _try_moolre_fallback(
        self, phone: str, body: str, *, primary_provider: str
    ) -> dict[str, Any] | None:
        """If Arkasel/Hubtel fails, try Moolre with the fallback key."""
        if primary_provider in {"moolre", "log"}:
            return None
        fallback_provider = (self._settings.sms_fallback_provider or "moolre").lower()
        if fallback_provider not in {"moolre", "moolree"}:
            return None
        # Prefer dedicated fallback key; Hubtel/Arkasel "secret" field can also hold it.
        key = (
            getattr(self._settings, "sms_fallback_api_key", None)
            or self._settings.sms_api_secret
            or None
        )
        if not key:
            logger.info(
                "sms_fallback_skipped",
                primary=primary_provider,
                reason="no_moolre_fallback_key",
            )
            return None
        result = self._send_moolre(phone, body, api_key=str(key))
        result["fallback_from"] = primary_provider
        if result.get("ok"):
            logger.info("sms_fallback_ok", primary=primary_provider, fallback="moolre")
        else:
            logger.warning(
                "sms_fallback_failed",
                primary=primary_provider,
                fallback=result,
            )
        return result

    def _dispatch_sms(self, provider: str, phone: str, body: str) -> dict[str, Any]:
        try:
            if provider == "hubtel":
                return self._send_hubtel(phone, body)
            if provider in {"arkasel", "arkesel"}:
                return self._send_arkasel(phone, body)
            if provider == "moolre":
                return self._send_moolre(phone, body)
            if provider == "http":
                return self._send_http(phone, body)
            logger.warning("sms_unknown_provider", provider=provider)
            return {"ok": False, "skipped": True, "reason": f"unknown_provider:{provider}"}
        except Exception as exc:  # noqa: BLE001
            logger.warning("sms_send_failed", to=phone, provider=provider, error=str(exc))
            return {"ok": False, "channel": "sms", "provider": provider, "error": str(exc)}

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
        with httpx.Client(timeout=15.0) as client:
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
        with httpx.Client(timeout=15.0) as client:
            resp = client.get(base, params=params)
        ok = 200 <= resp.status_code < 300
        return {
            "ok": ok,
            "channel": "sms",
            "provider": "hubtel",
            "status_code": resp.status_code,
            "response": resp.text[:300],
        }

    def _send_arkasel(self, phone: str, body: str) -> dict[str, Any]:
        """Arkesel SMS API — https://sms.arkesel.com/api/v2/sms/send"""
        api_key = self._settings.sms_api_key or ""
        if not api_key:
            return {"ok": False, "skipped": True, "reason": "sms_api_key_missing"}
        sender = (self._settings.sms_sender_id or "IFNOTUS")[:11]
        # Arkesel expects digits with country code, no leading +.
        recipient = phone.lstrip("+")
        payload = {
            "sender": sender,
            "message": body[:320],
            "recipients": [recipient],
        }
        headers = {
            "Content-Type": "application/json",
            "api-key": api_key,
        }
        with httpx.Client(timeout=15.0) as client:
            resp = client.post(
                "https://sms.arkesel.com/api/v2/sms/send",
                headers=headers,
                json=payload,
            )
        ok = 200 <= resp.status_code < 300
        # Arkesel often returns 200 with status:"error" in JSON.
        try:
            data = resp.json()
            if isinstance(data, dict):
                status = str(data.get("status") or "").lower()
                if status in {"error", "failed", "fail"}:
                    ok = False
                code = data.get("code")
                if code is not None and str(code) not in {"ok", "success", "200", "0"}:
                    # Some responses use numeric success codes like "ok"
                    if str(code).lower() not in {"ok", "success"} and not (
                        isinstance(code, int) and 200 <= code < 300
                    ):
                        if status and status not in {"success", "ok"}:
                            ok = False
        except Exception:  # noqa: BLE001
            pass
        return {
            "ok": ok,
            "channel": "sms",
            "provider": "arkasel",
            "status_code": resp.status_code,
            "response": resp.text[:300],
        }

    def _send_moolre(
        self, phone: str, body: str, *, api_key: str | None = None
    ) -> dict[str, Any]:
        """Moolre SMS API — https://api.moolre.com/open/sms/send"""
        key = api_key or self._settings.sms_api_key or ""
        if not key:
            return {"ok": False, "skipped": True, "reason": "sms_api_key_missing"}
        sender = (self._settings.sms_sender_id or "IFNOTUS")[:11]
        recipient = phone.lstrip("+")
        payload = {
            "type": 1,
            "senderid": sender,
            "messages": [{"recipient": recipient, "message": body[:160]}],
        }
        headers = {
            "Content-Type": "application/json",
            "X-API-VASKEY": key,
        }
        with httpx.Client(timeout=15.0) as client:
            resp = client.post(
                "https://api.moolre.com/open/sms/send",
                headers=headers,
                json=payload,
            )
        ok = 200 <= resp.status_code < 300
        try:
            data = resp.json()
            if isinstance(data, dict) and data.get("status") == 0:
                ok = False
        except Exception:  # noqa: BLE001
            pass
        return {
            "ok": ok,
            "channel": "sms",
            "provider": "moolre",
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

    def check_sms_balance(self) -> dict[str, Any]:
        """Fetch live balance details from the configured SMS provider."""
        provider = (self._settings.sms_provider or "none").lower()
        if provider in {"", "none", "off"}:
            return {"ok": False, "provider": provider, "message": "SMS provider is not configured."}
        if provider == "log":
            return {"ok": True, "provider": "log", "sms_balance": 999999, "main_balance": 0.0, "currency": "SMS (dev stub)"}

        if provider in {"arkasel", "arkesel"}:
            api_key = self._settings.sms_api_key or ""
            if not api_key:
                return {"ok": False, "provider": "arkasel", "message": "Arkasel API key is not set."}
            try:
                headers = {"api-key": api_key}
                with httpx.Client(timeout=10.0) as client:
                    resp = client.get("https://sms.arkesel.com/api/v2/clients/balance-details", headers=headers)
                if 200 <= resp.status_code < 300:
                    data = resp.json()
                    inner = data.get("data") if isinstance(data, dict) else {}
                    sms_bal = inner.get("sms_balance") if isinstance(inner, dict) else None
                    main_bal = inner.get("main_balance") if isinstance(inner, dict) else None
                    return {
                        "ok": True,
                        "provider": "arkasel",
                        "sms_balance": sms_bal,
                        "main_balance": main_bal,
                        "message": "Arkasel balance retrieved successfully.",
                    }
                return {
                    "ok": False,
                    "provider": "arkasel",
                    "status_code": resp.status_code,
                    "message": f"Arkasel error ({resp.status_code}): {resp.text[:150]}",
                }
            except Exception as exc:  # noqa: BLE001
                return {"ok": False, "provider": "arkasel", "message": f"Failed to connect to Arkasel: {exc}"}

        if provider == "moolre":
            key = self._settings.sms_api_key or ""
            if not key:
                return {"ok": False, "provider": "moolre", "message": "Moolre API key is not set."}
            try:
                headers = {"X-API-VASKEY": key}
                with httpx.Client(timeout=10.0) as client:
                    resp = client.get("https://api.moolre.com/open/balance", headers=headers)
                if 200 <= resp.status_code < 300:
                    data = resp.json()
                    return {"ok": True, "provider": "moolre", "raw": data, "message": "Moolre balance retrieved."}
                return {
                    "ok": False,
                    "provider": "moolre",
                    "status_code": resp.status_code,
                    "message": f"Moolre error: {resp.text[:150]}",
                }
            except Exception as exc:  # noqa: BLE001
                return {"ok": False, "provider": "moolre", "message": f"Failed to connect to Moolre: {exc}"}

        return {"ok": False, "provider": provider, "message": f"Live balance lookup not supported for provider '{provider}'."}


DeliveryService = MessageDelivery

