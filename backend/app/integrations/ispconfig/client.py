"""ISPConfig remote JSON API client — server-side only.

ISPConfig 3 JSON remoting expects:
  POST {base}/remote/json.php?{method}
  body: named params matching the PHP method signature
  response: {"code":"ok","message":"","response":...}
"""

from __future__ import annotations

import asyncio
from typing import Any

import httpx

from app.core.config import Settings
from app.core.logging import get_logger
from app.integrations.ispconfig.exceptions import ISPConfigAPIError, ISPConfigNotConfigured

logger = get_logger(__name__)


class ISPConfigClient:
    """ISPConfig 3 remote JSON API wrapper."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._base = (settings.ispconfig_base_url or "").rstrip("/")
        self._user = (settings.ispconfig_remote_user or "").strip()
        self._password = (settings.ispconfig_remote_password or "").strip()
        self._timeout = float(settings.ispconfig_timeout_seconds or 60)
        self._verify = bool(getattr(settings, "ispconfig_verify_ssl", True))
        self._session: str | None = None

    @property
    def configured(self) -> bool:
        return bool(self._base and self._user and self._password)

    def _require(self) -> None:
        if not self.configured:
            raise ISPConfigNotConfigured(
                "ISPConfig is not configured. Set ISPCONFIG_BASE_URL, "
                "ISPCONFIG_REMOTE_USER, and ISPCONFIG_REMOTE_PASSWORD."
            )

    @property
    def _endpoint(self) -> str:
        return f"{self._base}/remote/json.php"

    async def _call(self, method: str, **params: Any) -> Any:
        self._require()
        url = f"{self._endpoint}?{method}"
        body = {k: v for k, v in params.items() if v is not None}
        last_exc: ISPConfigAPIError | None = None
        for attempt in range(3):
            async with httpx.AsyncClient(timeout=self._timeout, verify=self._verify) as client:
                try:
                    resp = await client.post(url, json=body)
                except httpx.HTTPError as exc:
                    logger.warning("ispconfig_http_error", method=method, error=str(exc))
                    last_exc = ISPConfigAPIError(f"ISPConfig unreachable: {exc}")
                    if attempt < 2:
                        await asyncio.sleep(1.5 * (attempt + 1))
                        continue
                    raise last_exc from exc

            try:
                data = resp.json()
            except Exception:
                last_exc = ISPConfigAPIError(
                    f"ISPConfig non-JSON response HTTP {resp.status_code}",
                    status_code=resp.status_code,
                    payload={"raw": resp.text[:2000]},
                )
                if resp.status_code in {502, 503, 504} and attempt < 2:
                    await asyncio.sleep(1.5 * (attempt + 1))
                    continue
                raise last_exc from None

            if resp.status_code >= 400:
                last_exc = ISPConfigAPIError(
                    f"ISPConfig HTTP {resp.status_code} for {method}",
                    status_code=resp.status_code,
                    payload=data if isinstance(data, dict) else {"data": data},
                )
                if resp.status_code in {502, 503, 504} and attempt < 2:
                    await asyncio.sleep(1.5 * (attempt + 1))
                    continue
                raise last_exc

            if not isinstance(data, dict):
                return data

            code = data.get("code")
            if code not in (None, "ok", "OK", 0, "0"):
                raise ISPConfigAPIError(
                    str(data.get("message") or f"ISPConfig error code={code}"),
                    payload=data,
                )

            if "response" in data:
                return data.get("response")
            return data

        if last_exc:
            raise last_exc
        raise ISPConfigAPIError(f"ISPConfig call failed for {method}")

    async def login(self) -> str:
        session = await self._call(
            "login",
            username=self._user,
            password=self._password,
            client_login=False,
        )
        if not session:
            raise ISPConfigAPIError("ISPConfig login returned empty session")
        self._session = str(session)
        return self._session

    async def logout(self) -> None:
        if not self._session:
            return
        try:
            await self._call("logout", session_id=self._session)
        finally:
            self._session = None

    async def _session_id(self) -> str:
        if self._session:
            return self._session
        return await self.login()

    async def health(self) -> dict[str, Any]:
        if not self.configured:
            return {"ok": False, "configured": False, "error": "not_configured"}
        try:
            sid = await self.login()
            await self.logout()
            return {"ok": True, "configured": True, "session": bool(sid)}
        except ISPConfigAPIError as exc:
            return {"ok": False, "configured": True, "error": str(exc)}

    # --- client ---

    async def client_add(self, reseller_id: int, params: dict[str, Any]) -> Any:
        sid = await self._session_id()
        return await self._call(
            "client_add",
            session_id=sid,
            reseller_id=reseller_id,
            params=params,
        )

    async def client_get(self, client_id: int) -> Any:
        sid = await self._session_id()
        return await self._call("client_get", session_id=sid, client_id=client_id)

    async def client_get_by_username(self, username: str) -> Any:
        sid = await self._session_id()
        return await self._call(
            "client_get_by_username",
            session_id=sid,
            username=username,
        )

    async def client_update(
        self, client_id: int, reseller_id: int, params: dict[str, Any]
    ) -> Any:
        sid = await self._session_id()
        return await self._call(
            "client_update",
            session_id=sid,
            client_id=client_id,
            reseller_id=reseller_id,
            params=params,
        )

    async def client_change_password(self, client_id: int, new_password: str) -> Any:
        sid = await self._session_id()
        return await self._call(
            "client_change_password",
            session_id=sid,
            client_id=client_id,
            new_password=new_password,
        )

    async def client_delete(self, client_id: int) -> Any:
        sid = await self._session_id()
        return await self._call("client_delete", session_id=sid, client_id=client_id)

    async def client_delete_everything(self, client_id: int) -> Any:
        sid = await self._session_id()
        return await self._call(
            "client_delete_everything",
            session_id=sid,
            client_id=client_id,
        )

    # --- websites ---

    async def sites_web_domain_add(self, client_id: int, params: dict[str, Any]) -> Any:
        sid = await self._session_id()
        return await self._call(
            "sites_web_domain_add",
            session_id=sid,
            client_id=client_id,
            params=params,
            readonly=False,
        )

    async def sites_web_domain_update(
        self, client_id: int, domain_id: int, params: dict[str, Any]
    ) -> Any:
        sid = await self._session_id()
        return await self._call(
            "sites_web_domain_update",
            session_id=sid,
            client_id=client_id,
            primary_id=domain_id,
            params=params,
        )

    async def sites_web_domain_set_status(self, domain_id: int, status: str) -> Any:
        sid = await self._session_id()
        return await self._call(
            "sites_web_domain_set_status",
            session_id=sid,
            primary_id=domain_id,
            status=status,
        )

    async def sites_web_domain_delete(self, domain_id: int) -> Any:
        sid = await self._session_id()
        return await self._call(
            "sites_web_domain_delete",
            session_id=sid,
            primary_id=domain_id,
        )

    async def sites_web_domain_get(self, domain_id: int) -> Any:
        sid = await self._session_id()
        return await self._call(
            "sites_web_domain_get",
            session_id=sid,
            primary_id=domain_id,
        )

    async def sites_web_domain_get_all_by_user(self, client_id: int) -> Any:
        sid = await self._session_id()
        cid = int(client_id)
        sys_userid: int | None = None
        sys_groupid: int | None = None

        async def _remember_sys_ids(domain_id: int) -> None:
            nonlocal sys_userid, sys_groupid
            try:
                dom = await self.sites_web_domain_get(domain_id)
            except ISPConfigAPIError:
                return
            if not isinstance(dom, dict):
                return
            su = int(dom.get("sys_userid") or 0)
            sg = int(dom.get("sys_groupid") or 0)
            if su and sg:
                sys_userid, sys_groupid = su, sg

        try:
            dbs = await self.sites_database_get_all_by_user(cid)
            if isinstance(dbs, list):
                for row in dbs:
                    pid = int(row.get("parent_domain_id") or 0)
                    if not pid:
                        db_id = int(row.get("database_id") or 0)
                        if db_id:
                            try:
                                detail = await self.sites_database_get(db_id)
                                if isinstance(detail, dict):
                                    pid = int(detail.get("parent_domain_id") or 0)
                            except ISPConfigAPIError:
                                pass
                    if pid:
                        await _remember_sys_ids(pid)
        except ISPConfigAPIError:
            pass

        if sys_userid and sys_groupid:
            result = await self._call(
                "client_get_sites_by_user",
                session_id=sid,
                sys_userid=sys_userid,
                sys_groupid=sys_groupid,
            )
            if isinstance(result, list):
                return result

        client = await self.client_get(cid)
        if not isinstance(client, dict):
            return []
        fallback_uid = int(client.get("sys_userid") or 0)
        fallback_gid = int(client.get("sys_groupid") or 0)
        if not fallback_uid or not fallback_gid:
            return []
        result = await self._call(
            "client_get_sites_by_user",
            session_id=sid,
            sys_userid=fallback_uid,
            sys_groupid=fallback_gid,
        )
        return result if isinstance(result, list) else []

    async def sites_web_subdomain_add(self, client_id: int, params: dict[str, Any]) -> Any:
        sid = await self._session_id()
        return await self._call(
            "sites_web_subdomain_add",
            session_id=sid,
            client_id=client_id,
            params=params,
        )

    async def sites_web_subdomain_delete(self, subdomain_id: int) -> Any:
        sid = await self._session_id()
        return await self._call(
            "sites_web_subdomain_delete",
            session_id=sid,
            primary_id=subdomain_id,
        )

    async def sites_web_aliasdomain_add(self, client_id: int, params: dict[str, Any]) -> Any:
        sid = await self._session_id()
        return await self._call(
            "sites_web_aliasdomain_add",
            session_id=sid,
            client_id=client_id,
            params=params,
        )

    async def sites_web_aliasdomain_delete(self, alias_id: int) -> Any:
        sid = await self._session_id()
        return await self._call(
            "sites_web_aliasdomain_delete",
            session_id=sid,
            primary_id=alias_id,
        )

    # --- databases ---

    async def sites_database_user_add(self, client_id: int, params: dict[str, Any]) -> Any:
        sid = await self._session_id()
        return await self._call(
            "sites_database_user_add",
            session_id=sid,
            client_id=client_id,
            params=params,
        )

    async def sites_database_user_delete(self, db_user_id: int) -> Any:
        sid = await self._session_id()
        return await self._call(
            "sites_database_user_delete",
            session_id=sid,
            primary_id=db_user_id,
        )

    async def sites_database_add(self, client_id: int, params: dict[str, Any]) -> Any:
        sid = await self._session_id()
        return await self._call(
            "sites_database_add",
            session_id=sid,
            client_id=client_id,
            params=params,
        )

    async def sites_database_get(self, db_id: int) -> Any:
        sid = await self._session_id()
        return await self._call(
            "sites_database_get",
            session_id=sid,
            primary_id=db_id,
        )

    async def sites_database_delete(self, db_id: int) -> Any:
        sid = await self._session_id()
        return await self._call(
            "sites_database_delete",
            session_id=sid,
            primary_id=db_id,
        )

    async def sites_database_get_all_by_user(self, client_id: int) -> Any:
        sid = await self._session_id()
        return await self._call(
            "sites_database_get_all_by_user",
            session_id=sid,
            client_id=client_id,
        )

    # --- FTP / shell ---

    async def sites_ftp_user_add(self, client_id: int, params: dict[str, Any]) -> Any:
        sid = await self._session_id()
        return await self._call(
            "sites_ftp_user_add",
            session_id=sid,
            client_id=client_id,
            params=params,
        )

    async def sites_ftp_user_get(self, ftp_user_id: int) -> Any:
        sid = await self._session_id()
        return await self._call(
            "sites_ftp_user_get",
            session_id=sid,
            primary_id=ftp_user_id,
        )

    async def sites_ftp_user_update(
        self, client_id: int, ftp_user_id: int, params: dict[str, Any]
    ) -> Any:
        sid = await self._session_id()
        return await self._call(
            "sites_ftp_user_update",
            session_id=sid,
            client_id=client_id,
            primary_id=ftp_user_id,
            params=params,
        )

    async def sites_ftp_user_delete(self, ftp_user_id: int) -> Any:
        sid = await self._session_id()
        return await self._call(
            "sites_ftp_user_delete",
            session_id=sid,
            primary_id=ftp_user_id,
        )

    async def sites_shell_user_add(self, client_id: int, params: dict[str, Any]) -> Any:
        sid = await self._session_id()
        return await self._call(
            "sites_shell_user_add",
            session_id=sid,
            client_id=client_id,
            params=params,
        )

    async def sites_shell_user_get(self, shell_user_id: int) -> Any:
        sid = await self._session_id()
        return await self._call(
            "sites_shell_user_get",
            session_id=sid,
            primary_id=shell_user_id,
        )

    async def sites_shell_user_delete(self, shell_user_id: int) -> Any:
        sid = await self._session_id()
        return await self._call(
            "sites_shell_user_delete",
            session_id=sid,
            primary_id=shell_user_id,
        )

    # --- cron ---

    async def sites_cron_add(self, client_id: int, params: dict[str, Any]) -> Any:
        sid = await self._session_id()
        return await self._call(
            "sites_cron_add",
            session_id=sid,
            client_id=client_id,
            params=params,
        )

    async def sites_cron_get(self, cron_id: int) -> Any:
        sid = await self._session_id()
        return await self._call(
            "sites_cron_get",
            session_id=sid,
            cron_id=cron_id,
        )

    async def sites_cron_delete(self, cron_id: int) -> Any:
        sid = await self._session_id()
        return await self._call(
            "sites_cron_delete",
            session_id=sid,
            cron_id=cron_id,
        )

    # --- usage ---

    async def quota_get_by_user(self, client_id: int) -> Any:
        sid = await self._session_id()
        return await self._call(
            "quota_get_by_user",
            session_id=sid,
            client_id=client_id,
        )

    async def trafficquota_get_by_user(self, client_id: int, lastdays: int = 30) -> Any:
        sid = await self._session_id()
        return await self._call(
            "trafficquota_get_by_user",
            session_id=sid,
            client_id=client_id,
            lastdays=lastdays,
        )

    # --- mail (basic) ---

    async def mail_domain_add(self, client_id: int, params: dict[str, Any]) -> Any:
        sid = await self._session_id()
        return await self._call(
            "mail_domain_add",
            session_id=sid,
            client_id=client_id,
            params=params,
        )

    async def mail_user_add(self, client_id: int, params: dict[str, Any]) -> Any:
        sid = await self._session_id()
        return await self._call(
            "mail_user_add",
            session_id=sid,
            client_id=client_id,
            params=params,
        )

    async def mail_user_delete(self, mailbox_id: int) -> Any:
        sid = await self._session_id()
        return await self._call(
            "mail_user_delete",
            session_id=sid,
            primary_id=mailbox_id,
        )

    # --- DNS (basic) ---

    async def dns_zone_add(self, client_id: int, params: dict[str, Any]) -> Any:
        sid = await self._session_id()
        return await self._call(
            "dns_zone_add",
            session_id=sid,
            client_id=client_id,
            params=params,
        )

    async def dns_a_add(
        self, client_id: int, params: dict[str, Any], *, update_serial: bool = True
    ) -> Any:
        sid = await self._session_id()
        return await self._call(
            "dns_a_add",
            session_id=sid,
            client_id=client_id,
            params=params,
            update_serial=update_serial,
        )

    async def dns_a_delete(self, record_id: int, *, update_serial: bool = True) -> Any:
        sid = await self._session_id()
        return await self._call(
            "dns_a_delete",
            session_id=sid,
            primary_id=record_id,
            update_serial=update_serial,
        )
