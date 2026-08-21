"""Paystack payment helpers — server-side verification only."""

from __future__ import annotations

import hashlib
import hmac
import secrets
from typing import Any

import httpx

from app.core.config import Settings
from app.core.exceptions import AppException


class PaystackService:
    def __init__(self, settings: Settings) -> None:
        from app.services.platform.integrations_store import IntegrationsSettingsStore

        self._settings = IntegrationsSettingsStore(settings).resolved()
        self._secret = self._settings.paystack_secret_key
        self._public = self._settings.paystack_public_key
        self._base = self._settings.paystack_base_url.rstrip("/")

    @property
    def enabled(self) -> bool:
        return bool(self._secret)

    @property
    def public_key(self) -> str | None:
        return self._public

    def new_reference(self, prefix: str = "IFN") -> str:
        return f"{prefix}_{secrets.token_hex(12)}"

    async def initialize_transaction(
        self,
        *,
        email: str,
        amount_pesewas: int,
        reference: str,
        callback_url: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if not self.enabled:
            # Dev/demo mode — no live charge
            return {
                "status": True,
                "message": "Paystack not configured — demo mode",
                "data": {
                    "authorization_url": f"{self._settings.customer_portal_url}/billing/demo-pay?ref={reference}",
                    "access_code": "demo",
                    "reference": reference,
                    "demo": True,
                },
            }

        payload: dict[str, Any] = {
            "email": email,
            "amount": amount_pesewas,
            "reference": reference,
            "currency": "GHS",
            "metadata": metadata or {},
        }
        if callback_url:
            payload["callback_url"] = callback_url

        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                f"{self._base}/transaction/initialize",
                json=payload,
                headers={"Authorization": f"Bearer {self._secret}"},
            )
        data = resp.json()
        if resp.status_code >= 400 or not data.get("status"):
            raise AppException(data.get("message") or "Paystack initialize failed.")
        return data

    async def verify_transaction(self, reference: str) -> dict[str, Any]:
        if not self.enabled:
            # Demo: treat any IFN_ reference as successful payment
            if not reference.startswith("IFN"):
                raise AppException("Invalid demo payment reference.")
            return {
                "status": True,
                "message": "Demo verification OK",
                "data": {
                    "status": "success",
                    "reference": reference,
                    "amount": 0,
                    "currency": "GHS",
                    "demo": True,
                },
            }

        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(
                f"{self._base}/transaction/verify/{reference}",
                headers={"Authorization": f"Bearer {self._secret}"},
            )
        data = resp.json()
        if resp.status_code >= 400 or not data.get("status"):
            raise AppException(data.get("message") or "Paystack verify failed.")
        tx = data.get("data") or {}
        if tx.get("status") != "success":
            raise AppException(f"Payment not successful (status={tx.get('status')}).")
        return data

    def verify_webhook_signature(self, body: bytes, signature: str | None) -> bool:
        if not self._secret:
            return True  # demo
        if not signature:
            return False
        digest = hmac.new(self._secret.encode(), body, hashlib.sha512).hexdigest()
        return hmac.compare_digest(digest, signature)
