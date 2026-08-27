"""OLSPanel HTTP client — server-side only. Never expose admin credentials to the browser.

API reference: https://olspanel.com/api_documents
Auth: username/password HTTP headers (admin or account, depending on endpoint).
"""

from __future__ import annotations

from typing import Any

import httpx

from app.core.config import Settings
from app.core.logging import get_logger
from app.integrations.olspanel.exceptions import OLSPanelAPIError, OLSPanelNotConfigured

logger = get_logger(__name__)


class OLSPanelClient:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        base = (settings.olspanel_base_url or "").rstrip("/")
        self._base = base
        self._admin_user = (settings.olspanel_admin_username or "").strip()
        self._admin_pass = (settings.olspanel_admin_password or "").strip()
        self._timeout = float(settings.olspanel_timeout_seconds or 60)

    @property
    def configured(self) -> bool:
        return bool(self._base and self._admin_user and self._admin_pass)

    def _require(self) -> None:
        if not self.configured:
            raise OLSPanelNotConfigured(
                "OLSPanel is not configured. Set OLSPANEL_BASE_URL, "
                "OLSPANEL_ADMIN_USERNAME, and OLSPANEL_ADMIN_PASSWORD."
            )

    def _admin_headers(self) -> dict[str, str]:
        return {
            "username": self._admin_user,
            "password": self._admin_pass,
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/json",
        }

    async def _post(self, path: str, data: dict[str, Any] | None = None) -> dict[str, Any] | list[Any]:
        self._require()
        url = f"{self._base}{path if path.startswith('/') else '/' + path}"
        async with httpx.AsyncClient(timeout=self._timeout, verify=True) as client:
            try:
                resp = await client.post(url, data=data or {}, headers=self._admin_headers())
            except httpx.HTTPError as exc:
                logger.warning("olspanel_http_error", path=path, error=str(exc))
                raise OLSPanelAPIError(f"OLSPanel unreachable: {exc}") from exc

        try:
            payload = resp.json()
        except Exception:
            payload = {"raw": resp.text[:2000], "status_code": resp.status_code}

        if resp.status_code >= 400:
            raise OLSPanelAPIError(
                f"OLSPanel HTTP {resp.status_code} for {path}",
                status_code=resp.status_code,
                payload=payload if isinstance(payload, dict) else {"data": payload},
            )

        if isinstance(payload, dict) and payload.get("success") is False:
            msg = payload.get("message") or payload.get("error") or "OLSPanel request failed"
            raise OLSPanelAPIError(str(msg), payload=payload)

        if isinstance(payload, dict) and payload.get("error"):
            raise OLSPanelAPIError(str(payload.get("error")), payload=payload)

        return payload  # type: ignore[return-value]

    async def health(self) -> dict[str, Any]:
        if not self.configured:
            return {"ok": False, "configured": False}
        try:
            packages = await self.packages_list()
            return {
                "ok": True,
                "configured": True,
                "base_url": self._base,
                "packages": len(packages) if isinstance(packages, list) else None,
            }
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "configured": True, "error": str(exc)}

    async def packages_list(self) -> list[dict[str, Any]]:
        data = await self._post("/admin_api/packages_list/")
        if isinstance(data, dict):
            pkgs = data.get("packages")
            return list(pkgs) if isinstance(pkgs, list) else []
        return []

    async def add_user(self, body: dict[str, Any]) -> dict[str, Any]:
        data = await self._post("/admin_api/add_user/", body)
        return data if isinstance(data, dict) else {"data": data}

    async def suspend_user(self, username: str, state: str) -> dict[str, Any]:
        # state: SUSPEND | UNSUSPEND | DELETE
        data = await self._post(
            "/admin_api/suspend_user/",
            {"username": username, "state": state},
        )
        return data if isinstance(data, dict) else {"data": data}

    async def update_user(self, body: dict[str, Any]) -> dict[str, Any]:
        data = await self._post("/admin_api/update_user/", body)
        return data if isinstance(data, dict) else {"data": data}

    async def account_info(self, username: str) -> dict[str, Any]:
        data = await self._post("/admin_api/", {"username": username})
        return data if isinstance(data, dict) else {"data": data}

    async def add_domain(
        self,
        *,
        username: str,
        domain: str,
        php_version: str = "8.2",
        path: str = "public_html",
    ) -> dict[str, Any]:
        data = await self._post(
            "/admin_api/add_domain/",
            {
                "username": username,
                "domain": domain,
                "php_version": php_version,
                "path": path,
            },
        )
        return data if isinstance(data, dict) else {"data": data}

    async def issue_ssl(self, domain: str) -> dict[str, Any]:
        data = await self._post("/admin_api/issue_ssl/", {"domain": domain})
        return data if isinstance(data, dict) else {"data": data}

    async def database_add(
        self,
        *,
        username: str,
        db: str,
        dbuser: str,
        dbpass: str,
    ) -> dict[str, Any]:
        data = await self._post(
            "/admin_api/database_add/",
            {
                "username": username,
                "db": db,
                "dbuser": dbuser,
                "dbpass": dbpass,
                "dbpassc": dbpass,
            },
        )
        return data if isinstance(data, dict) else {"data": data}

    async def new_package(self, body: dict[str, Any]) -> dict[str, Any]:
        data = await self._post("/admin_api/new_package/", body)
        return data if isinstance(data, dict) else {"data": data}

    async def sso_login(self, username: str) -> dict[str, Any]:
        data = await self._post("/admin_api/sso_login/", {"username": username})
        return data if isinstance(data, dict) else {"data": data}
