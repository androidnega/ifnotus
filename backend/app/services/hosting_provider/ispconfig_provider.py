"""ISPConfig HostingProvider — typed ops + customer-safe errors."""

from __future__ import annotations

from typing import Any

from app.core.config import Settings
from app.core.logging import get_logger
from app.integrations.ispconfig.client import ISPConfigClient
from app.integrations.ispconfig.errors import (
    customer_safe_provider_error,
    provider_error_log_fields,
)
from app.integrations.ispconfig.exceptions import ISPConfigError
from app.schemas.ispconfig_provider import (
    IspAliasCreateParams,
    IspClientCreateParams,
    IspCronCreateParams,
    IspDatabaseCreateParams,
    IspDatabaseUserCreateParams,
    IspFtpUserCreateParams,
    IspShellUserCreateParams,
    IspSubdomainCreateParams,
    IspWebsiteCreateParams,
)
from app.services.hosting_provider.base import (
    CreateAccountRequest,
    HostingProvider,
    HostingProviderKind,
    ProviderAccount,
    ProviderUsage,
    ProviderWebsite,
)
from app.services.hosting_provider.package_map import resolve_ispconfig_template_id

logger = get_logger(__name__)


class ISPConfigHostingProvider(HostingProvider):
    kind = HostingProviderKind.ISPCONFIG

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._client = ISPConfigClient(settings)

    def _server_id(self) -> int:
        return int(self._settings.ispconfig_server_id or 1)

    def _reseller_id(self) -> int:
        rid = int(self._settings.ispconfig_reseller_id or 0)
        return rid if rid > 0 else 0

    def _php_options(self, php_version: str | None) -> str:
        php_opts = php_version or self._settings.ispconfig_default_php_version or "8.2"
        if php_opts and "," not in php_opts and php_opts not in {
            "no",
            "fast-cgi",
            "cgi",
            "mod",
            "suphp",
            "php-fpm",
        }:
            return "no,fast-cgi,php-fpm"
        return php_opts

    async def _client_id_for_username(self, username: str) -> int:
        client = await self._client.client_get_by_username(username)
        if not isinstance(client, dict):
            raise ISPConfigError(f"Invalid client payload for {username!r}")
        return int(client.get("client_id") or 0)

    async def _site_paths_for_domain(self, domain_id: int) -> dict[str, str]:
        domain = await self._client.sites_web_domain_get(domain_id)
        if not isinstance(domain, dict):
            raise ISPConfigError(f"Invalid web domain payload for id={domain_id}")
        doc_root = str(domain.get("document_root") or "").rstrip("/")
        web_dir = f"{doc_root}/web" if doc_root else ""
        return {
            "document_root": doc_root,
            "web_dir": web_dir,
            "system_user": str(domain.get("system_user") or ""),
            "system_group": str(domain.get("system_group") or ""),
        }

    async def _run(self, operation: str, awaitable):  # type: ignore[no-untyped-def]
        try:
            return await awaitable
        except ISPConfigError as exc:
            logger.warning(
                "ispconfig_provider_error",
                operation=operation,
                **provider_error_log_fields(exc),
            )
            raise customer_safe_provider_error(exc, operation=operation) from exc

    async def health(self) -> dict[str, Any]:
        snap = await self._client.health()
        return {"provider": self.kind.value, **snap}

    async def create_account(self, req: CreateAccountRequest) -> ProviderAccount:
        async def _do() -> ProviderAccount:
            template_id = resolve_ispconfig_template_id(self._settings, req.package_id)
            client_params = IspClientCreateParams(
                company_name=f"{req.first_name} {req.last_name}".strip() or req.username,
                contact_name=f"{req.first_name} {req.last_name}".strip() or req.username,
                customer_no=str(req.customer_id or req.username)[:64],
                username=req.username,
                password=req.password,
                email=req.email,
                web_php_options=self._php_options(req.php_version),
                template_master=template_id or 0,
            )
            client_id = await self._client.client_add(
                self._reseller_id(),
                client_params.model_dump(),
            )
            client_id_int = int(client_id) if client_id is not None else 0

            website = IspWebsiteCreateParams(
                domain=req.domain,
                server_id=self._server_id(),
            )
            domain_id = await self._client.sites_web_domain_add(
                client_id_int,
                website.model_dump(exclude_none=True),
            )
            return ProviderAccount(
                provider=self.kind,
                username=req.username,
                user_id=client_id_int,
                main_domain=req.domain,
                package_id=template_id,
                raw={"client_id": client_id_int, "domain_id": domain_id},
            )

        return await self._run("create_account", _do())

    async def suspend_account(self, username: str) -> dict[str, Any]:
        async def _do() -> dict[str, Any]:
            client_id = await self._client_id_for_username(username)
            domains = await self._client.sites_web_domain_get_all_by_user(client_id) or []
            results = []
            if isinstance(domains, list):
                for row in domains:
                    did = int(row.get("domain_id") or row.get("id") or 0)
                    if did:
                        results.append(
                            await self._client.sites_web_domain_set_status(did, "inactive")
                        )
            return {"username": username, "suspended": True, "results": results}

        return await self._run("suspend_account", _do())

    async def unsuspend_account(self, username: str) -> dict[str, Any]:
        async def _do() -> dict[str, Any]:
            client_id = await self._client_id_for_username(username)
            domains = await self._client.sites_web_domain_get_all_by_user(client_id) or []
            results = []
            if isinstance(domains, list):
                for row in domains:
                    did = int(row.get("domain_id") or row.get("id") or 0)
                    if did:
                        results.append(
                            await self._client.sites_web_domain_set_status(did, "active")
                        )
            return {"username": username, "unsuspended": True, "results": results}

        return await self._run("unsuspend_account", _do())

    async def delete_account(self, username: str) -> dict[str, Any]:
        async def _do() -> dict[str, Any]:
            client_id = await self._client_id_for_username(username)
            # Prefer cascade delete when available.
            try:
                deleted = await self._client.client_delete_everything(client_id)
                return {
                    "username": username,
                    "client_id": client_id,
                    "deleted_everything": deleted,
                }
            except ISPConfigError:
                domains = await self._client.sites_web_domain_get_all_by_user(client_id) or []
                deleted_domains = []
                if isinstance(domains, list):
                    for row in domains:
                        did = int(row.get("domain_id") or row.get("id") or 0)
                        if did:
                            deleted_domains.append(
                                await self._client.sites_web_domain_delete(did)
                            )
                deleted_client = await self._client.client_delete(client_id)
                return {
                    "username": username,
                    "client_id": client_id,
                    "deleted_domains": deleted_domains,
                    "deleted_client": deleted_client,
                }

        return await self._run("delete_account", _do())

    async def update_package(self, username: str, package_id: str | int) -> dict[str, Any]:
        async def _do() -> dict[str, Any]:
            template_id = resolve_ispconfig_template_id(self._settings, package_id)
            client_id = await self._client_id_for_username(username)
            updated = await self._client.client_update(
                client_id,
                self._reseller_id(),
                {"template_master": template_id or 0},
            )
            return {
                "username": username,
                "template_id": template_id,
                "updated": updated,
            }

        return await self._run("update_package", _do())

    async def get_usage(self, username: str) -> ProviderUsage:
        async def _do() -> ProviderUsage:
            client = await self._client.client_get_by_username(username)
            if not isinstance(client, dict):
                return ProviderUsage(raw={"client": client})
            client_id = int(client.get("client_id") or 0)
            disk = None
            traffic = None
            try:
                disk = await self._client.quota_get_by_user(client_id)
            except ISPConfigError as exc:
                logger.info("ispconfig_quota_unavailable", **provider_error_log_fields(exc))
            try:
                traffic = await self._client.trafficquota_get_by_user(client_id, lastdays=30)
            except ISPConfigError as exc:
                logger.info("ispconfig_traffic_unavailable", **provider_error_log_fields(exc))

            disk_used = None
            disk_limit = None
            if isinstance(disk, dict):
                disk_used = str(disk.get("used") or disk.get("hdd_used") or "") or None
                disk_limit = str(disk.get("soft") or disk.get("hdd_quota") or "") or None
            elif isinstance(disk, list) and disk:
                row = disk[0] if isinstance(disk[0], dict) else {}
                disk_used = str(row.get("used") or "") or None
                disk_limit = str(row.get("soft") or "") or None

            bw_used = None
            if isinstance(traffic, (list, dict)):
                bw_used = str(traffic)[:120]

            return ProviderUsage(
                disk_used=disk_used,
                disk_limit=disk_limit or str(client.get("limit_web_quota") or "") or None,
                bandwidth_used=bw_used,
                db_limit=int(client["limit_database"])
                if str(client.get("limit_database") or "").isdigit()
                else None,
                ftp_limit=int(client["limit_ftp_user"])
                if str(client.get("limit_ftp_user") or "").isdigit()
                else None,
                domain_limit=int(client["limit_web_domain"])
                if str(client.get("limit_web_domain") or "").isdigit()
                else None,
                raw={"client": client, "disk": disk, "traffic": traffic},
            )

        return await self._run("get_usage", _do())

    async def list_packages(self) -> list[dict[str, Any]]:
        return [{"source": "ispconfig_template_map", "configured": True}]

    async def add_domain(
        self,
        username: str,
        domain: str,
        *,
        php_version: str = "8.2",
        path: str = "public_html",
    ) -> ProviderWebsite:
        async def _do() -> ProviderWebsite:
            client_id = await self._client_id_for_username(username)
            params = IspWebsiteCreateParams(
                domain=domain,
                server_id=self._server_id(),
                document_root=path,
            )
            domain_id = await self._client.sites_web_domain_add(
                client_id,
                params.model_dump(exclude_none=True),
            )
            return ProviderWebsite(
                domain=domain,
                website_id=domain_id,
                path=path,
                php_version=php_version,
                raw={"domain_id": domain_id},
            )

        return await self._run("add_domain", _do())

    async def update_website(
        self, username: str, domain_id: int, params: dict[str, Any]
    ) -> dict[str, Any]:
        async def _do() -> dict[str, Any]:
            client_id = await self._client_id_for_username(username)
            updated = await self._client.sites_web_domain_update(client_id, domain_id, params)
            return {"domain_id": domain_id, "updated": updated}

        return await self._run("update_website", _do())

    async def delete_website(self, username: str, domain_id: int) -> dict[str, Any]:
        async def _do() -> dict[str, Any]:
            # username used for authz context / future ownership checks
            _ = username
            deleted = await self._client.sites_web_domain_delete(domain_id)
            return {"domain_id": domain_id, "deleted": deleted}

        return await self._run("delete_website", _do())

    async def add_subdomain(
        self,
        username: str,
        *,
        parent_domain_id: int,
        subdomain: str,
    ) -> dict[str, Any]:
        async def _do() -> dict[str, Any]:
            client_id = await self._client_id_for_username(username)
            params = IspSubdomainCreateParams(
                domain=subdomain,
                parent_domain_id=parent_domain_id,
                server_id=self._server_id(),
            )
            sid = await self._client.sites_web_subdomain_add(client_id, params.model_dump())
            return {"subdomain_id": sid, "domain": subdomain}

        return await self._run("add_subdomain", _do())

    async def add_alias(
        self,
        username: str,
        *,
        parent_domain_id: int,
        alias_domain: str,
    ) -> dict[str, Any]:
        async def _do() -> dict[str, Any]:
            client_id = await self._client_id_for_username(username)
            params = IspAliasCreateParams(
                domain=alias_domain,
                parent_domain_id=parent_domain_id,
                server_id=self._server_id(),
            )
            aid = await self._client.sites_web_aliasdomain_add(client_id, params.model_dump())
            return {"alias_id": aid, "domain": alias_domain}

        return await self._run("add_alias", _do())

    async def issue_ssl(self, domain: str) -> dict[str, Any]:
        async def _do() -> dict[str, Any]:
            raise ISPConfigError(
                "SSL enable requires domain_id; use issue_ssl_for_domain_id "
                f"(domain={domain})"
            )

        return await self._run("issue_ssl", _do())

    async def issue_ssl_for_domain_id(
        self,
        *,
        domain_id: int,
        client_id: int,
        domain: str | None = None,
    ) -> dict[str, Any]:
        async def _do() -> dict[str, Any]:
            if not domain_id or not client_id:
                raise ISPConfigError("domain_id and client_id are required for SSL")
            current = await self._client.sites_web_domain_get(domain_id)
            params = dict(current) if isinstance(current, dict) else {}
            params.update(
                {
                    "ssl": "y",
                    "ssl_letsencrypt": "y",
                    "ssl_state": params.get("ssl_state") or "Accra",
                    "ssl_locality": params.get("ssl_locality") or "Accra",
                    "ssl_organisation": params.get("ssl_organisation") or "IFNOTUS",
                    "ssl_organisation_unit": params.get("ssl_organisation_unit") or "Hosting",
                    "ssl_country": params.get("ssl_country") or "GH",
                }
            )
            if domain:
                params["domain"] = domain
            updated = await self._client.sites_web_domain_update(client_id, domain_id, params)
            return {
                "ok": True,
                "domain_id": domain_id,
                "ssl": "letsencrypt",
                "updated": updated,
            }

        return await self._run("issue_ssl", _do())

    async def create_database(
        self,
        username: str,
        *,
        db_name: str,
        db_user: str,
        db_password: str,
        parent_domain_id: int | None = None,
    ) -> dict[str, Any]:
        async def _do() -> dict[str, Any]:
            client_id = await self._client_id_for_username(username)
            user_params = IspDatabaseUserCreateParams(
                database_user=db_user,
                database_password=db_password,
            )
            db_user_id = await self._client.sites_database_user_add(
                client_id,
                user_params.model_dump(exclude_none=True),
            )
            db_params = IspDatabaseCreateParams(
                database_name=db_name,
                database_user_id=int(db_user_id),
                server_id=self._server_id(),
                parent_domain_id=int(parent_domain_id or 0),
            )
            db_id = await self._client.sites_database_add(
                client_id,
                db_params.model_dump(),
            )
            return {
                "db_id": db_id,
                "db_user_id": db_user_id,
                "db_name": db_name,
                "db_user": db_user,
            }

        return await self._run("create_database", _do())

    async def delete_database(self, username: str, db_id: int) -> dict[str, Any]:
        async def _do() -> dict[str, Any]:
            _ = username
            deleted = await self._client.sites_database_delete(db_id)
            return {"db_id": db_id, "deleted": deleted}

        return await self._run("delete_database", _do())

    async def create_ftp_user(
        self,
        username: str,
        **kwargs: Any,
    ) -> dict[str, Any]:
        self.require("ftp")

        async def _do() -> dict[str, Any]:
            client_id = await self._client_id_for_username(username)
            parent_domain_id = int(kwargs.get("parent_domain_id") or 0)
            ftp_username = str(kwargs.get("ftp_username") or kwargs.get("username") or "")
            password = str(kwargs.get("password") or "")
            directory = str(kwargs.get("dir") or kwargs.get("directory") or "")
            if not parent_domain_id or not ftp_username or not password:
                raise ISPConfigError(
                    "parent_domain_id, ftp_username/username, and password are required"
                )
            site = await self._site_paths_for_domain(parent_domain_id)
            if not directory:
                directory = site["web_dir"] or site["document_root"]
            params = IspFtpUserCreateParams(
                username=ftp_username,
                password=password,
                parent_domain_id=parent_domain_id,
                server_id=self._server_id(),
                dir=directory,
                uid=site["system_user"],
                gid=site["system_group"],
            )
            ftp_id = await self._client.sites_ftp_user_add(client_id, params.model_dump())
            return {"ftp_user_id": ftp_id, "username": ftp_username}

        return await self._run("create_ftp_user", _do())

    async def delete_ftp_user(self, username: str, **kwargs: Any) -> dict[str, Any]:
        self.require("ftp")

        async def _do() -> dict[str, Any]:
            _ = username
            ftp_user_id = int(kwargs.get("ftp_user_id") or kwargs.get("id") or 0)
            if not ftp_user_id:
                raise ISPConfigError("ftp_user_id is required")
            deleted = await self._client.sites_ftp_user_delete(ftp_user_id)
            return {"ftp_user_id": ftp_user_id, "deleted": deleted}

        return await self._run("delete_ftp_user", _do())

    async def create_shell_user(
        self,
        username: str,
        *,
        parent_domain_id: int,
        shell_username: str,
        password: str,
        chroot: str = "jailkit",
    ) -> dict[str, Any]:
        self.require("sftp")

        async def _do() -> dict[str, Any]:
            client_id = await self._client_id_for_username(username)
            site = await self._site_paths_for_domain(parent_domain_id)
            params = IspShellUserCreateParams(
                username=shell_username,
                password=password,
                parent_domain_id=parent_domain_id,
                server_id=self._server_id(),
                chroot=chroot,
                dir=site["web_dir"] or site["document_root"],
                puser=site["system_user"],
                pgroup=site["system_group"],
            )
            shell_id = await self._client.sites_shell_user_add(client_id, params.model_dump())
            return {"shell_user_id": shell_id, "username": shell_username}

        return await self._run("create_shell_user", _do())

    async def create_cron(self, username: str, **kwargs: Any) -> dict[str, Any]:
        self.require("cron")

        async def _do() -> dict[str, Any]:
            client_id = await self._client_id_for_username(username)
            parent_domain_id = int(kwargs.get("parent_domain_id") or 0)
            command = str(kwargs.get("command") or "")
            if not parent_domain_id or not command:
                raise ISPConfigError("parent_domain_id and command are required")
            params = IspCronCreateParams(
                parent_domain_id=parent_domain_id,
                server_id=self._server_id(),
                command=command,
                type=str(kwargs.get("type") or "url"),
                run_min=str(kwargs.get("run_min") or "0"),
                run_hour=str(kwargs.get("run_hour") or "*"),
                run_mday=str(kwargs.get("run_mday") or "*"),
                run_month=str(kwargs.get("run_month") or "*"),
                run_wday=str(kwargs.get("run_wday") or "*"),
            )
            cron_id = await self._client.sites_cron_add(client_id, params.model_dump())
            return {"cron_id": cron_id}

        return await self._run("create_cron", _do())

    async def delete_cron(self, username: str, **kwargs: Any) -> dict[str, Any]:
        self.require("cron")

        async def _do() -> dict[str, Any]:
            _ = username
            cron_id = int(kwargs.get("cron_id") or kwargs.get("id") or 0)
            if not cron_id:
                raise ISPConfigError("cron_id is required")
            deleted = await self._client.sites_cron_delete(cron_id)
            return {"cron_id": cron_id, "deleted": deleted}

        return await self._run("delete_cron", _do())

    async def create_mail_domain(self, username: str, domain: str) -> dict[str, Any]:
        self.require("mail")

        async def _do() -> dict[str, Any]:
            client_id = await self._client_id_for_username(username)
            mid = await self._client.mail_domain_add(
                client_id,
                {
                    "server_id": self._server_id(),
                    "domain": domain.strip().lower(),
                    "active": "y",
                },
            )
            return {"mail_domain_id": mid, "domain": domain}

        return await self._run("create_mail_domain", _do())

    async def create_mailbox(self, username: str, **kwargs: Any) -> dict[str, Any]:
        self.require("mail")

        async def _do() -> dict[str, Any]:
            client_id = await self._client_id_for_username(username)
            email = str(kwargs.get("email") or "")
            password = str(kwargs.get("password") or "")
            if not email or not password:
                raise ISPConfigError("email and password are required")
            mid = await self._client.mail_user_add(
                client_id,
                {
                    "server_id": self._server_id(),
                    "email": email,
                    "password": password,
                    "name": str(kwargs.get("name") or email.split("@")[0]),
                    "quota": int(kwargs.get("quota") or 0),
                    "active": "y",
                },
            )
            return {"mailbox_id": mid, "email": email}

        return await self._run("create_mailbox", _do())

    async def delete_mailbox(self, username: str, **kwargs: Any) -> dict[str, Any]:
        self.require("mail")

        async def _do() -> dict[str, Any]:
            _ = username
            mailbox_id = int(kwargs.get("mailbox_id") or kwargs.get("id") or 0)
            if not mailbox_id:
                raise ISPConfigError("mailbox_id is required")
            deleted = await self._client.mail_user_delete(mailbox_id)
            return {"mailbox_id": mailbox_id, "deleted": deleted}

        return await self._run("delete_mailbox", _do())

    async def create_dns_zone(self, username: str, domain: str) -> dict[str, Any]:
        self.require("dns")

        async def _do() -> dict[str, Any]:
            client_id = await self._client_id_for_username(username)
            zid = await self._client.dns_zone_add(
                client_id,
                {
                    "server_id": self._server_id(),
                    "origin": domain.strip().lower().rstrip(".") + ".",
                    "ns": "ns1.ifnotus.space.",
                    "mbox": "hostmaster.ifnotus.space.",
                    "active": "Y",
                },
            )
            return {"zone_id": zid, "domain": domain}

        return await self._run("create_dns_zone", _do())

    async def create_dns_record(self, username: str, **kwargs: Any) -> dict[str, Any]:
        self.require("dns")

        async def _do() -> dict[str, Any]:
            client_id = await self._client_id_for_username(username)
            zone = str(kwargs.get("zone") or kwargs.get("name") or "")
            data = str(kwargs.get("data") or kwargs.get("ip") or "")
            if not zone or not data:
                raise ISPConfigError("zone/name and data/ip are required")
            rid = await self._client.dns_a_add(
                client_id,
                {
                    "server_id": self._server_id(),
                    "zone": int(kwargs.get("zone_id") or 0),
                    "name": zone,
                    "data": data,
                    "ttl": str(kwargs.get("ttl") or "3600"),
                    "active": "Y",
                },
            )
            return {"record_id": rid}

        return await self._run("create_dns_record", _do())

    async def sso_login_url(self, username: str) -> str | None:
        _ = username
        base = (self._settings.ispconfig_base_url or "").rstrip("/")
        if not base:
            return None
        # Customers never use this; staff infrastructure only.
        return f"{base}/"
