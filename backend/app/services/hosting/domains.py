"""Domain management service — cPanel-style domains, subdomains, aliases, redirects."""

from __future__ import annotations

import asyncio
import socket
from datetime import UTC, datetime
from uuid import UUID

import psutil
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import Settings
from app.core.exceptions import AppException, ConflictError, NotFoundError
from app.core.logging import get_logger
from app.models.hosting import Domain, DomainDnsRecord, DomainRedirect
from app.repositories.domain import DomainRepository
from app.schemas.hosting import (
    DnsCheckResponse,
    DomainCreate,
    DomainDnsRecordCreate,
    DomainDnsRecordSchema,
    DomainImportRequest,
    DomainListResponse,
    DomainRedirectCreate,
    DomainRedirectSchema,
    DomainSchema,
    DomainUpdate,
)
from app.schemas.operations import OperationResult
from app.services.applications.readers.nginx import NginxReader
from app.services.hosting.nginx_discovery import NginxDiscoveryService
from app.services.hosting.nginx_provisioner import MANAGED_MARKER, DomainNginxProvisioner

logger = get_logger(__name__)

_APP_PORT_RANGE = range(8000, 9101)

# Host labels that are almost always aliases of the apex, not real domains.
_ALIAS_LABELS = frozenset({"www"})


def classify_hostname(name: str, known_names: set[str]) -> tuple[str, str | None, str | None]:
    """Return (domain_type, parent_hostname, subdomain_label) for a hostname.

    Prefers an existing apex already in `known_names`. ``www.`` hostnames are
    aliases; anything with more labels than a known parent is a subdomain.
    """
    host = name.strip().lower().rstrip(".")
    if not host:
        return "primary", None, None

    if host.startswith("www.") and len(host) > 4:
        parent = host[4:]
        return "alias", parent, "www"

    parts = host.split(".")
    # Longest matching parent among known names (cth.csdttu.online → csdttu.online).
    for i in range(1, len(parts) - 1):
        parent = ".".join(parts[i:])
        if parent in known_names:
            label = ".".join(parts[:i])
            if label in _ALIAS_LABELS:
                return "alias", parent, label
            return "subdomain", parent, label

    # Heuristic: 3+ labels without a known parent still looks like a subdomain
    # of the rightmost two labels (examflow.csdttu.online → csdttu.online).
    if len(parts) >= 3:
        parent = ".".join(parts[-2:])
        label = ".".join(parts[:-2])
        if label and parent != host:
            if label in _ALIAS_LABELS:
                return "alias", parent, label
            return "subdomain", parent, label

    return "primary", None, None


class DomainService:
    def __init__(self, settings: Settings, session: AsyncSession) -> None:
        self._settings = settings
        self._session = session
        self._repo = DomainRepository(session)
        self._nginx = NginxReader()
        self._nginx_discovery = NginxDiscoveryService(settings)
        self._provisioner = DomainNginxProvisioner(settings)

    async def list_domains(self) -> DomainListResponse:
        try:
            from app.services.hosting.host_inventory_sync import HostInventorySync

            await HostInventorySync(self._settings, self._session).sync()
        except Exception:  # noqa: BLE001
            nginx_sites = await asyncio.to_thread(self._nginx_discovery.scan_sites)
            await self._sync_from_nginx(nginx_sites)

        nginx_sites = await asyncio.to_thread(self._nginx_discovery.scan_sites)
        raw_domains = await self._list_with_relations()
        domains = [d for d in raw_domains if NginxDiscoveryService.is_actual_domain_or_subdomain(d.name)]
        site_by_name = {s.server_name: s for s in nginx_sites}
        enriched = [self._enrich_from_site(d, site_by_name.get(d.name)) for d in domains]
        db_names = {d.name for d in domains}

        discovered = [s for s in nginx_sites if s.server_name not in db_names]
        drift_count = 0
        for entity in domains:
            site = site_by_name.get(entity.name)
            if site is None:
                drift_count += 1
            elif not site.enabled:
                drift_count += 1
            elif (
                entity.document_root
                and site.document_root
                and site.document_root != entity.document_root
            ):
                drift_count += 1

        listening, available = await asyncio.to_thread(self._port_inventory, domains)
        return DomainListResponse(
            timestamp=datetime.now(UTC),
            total=len(enriched),
            domains=enriched,
            discovered=discovered,
            discovered_total=len(discovered),
            drift_count=drift_count,
            listening_ports=listening,
            available_ports=available,
            server_ip=self._settings.server_public_ip,
        )

    async def get_domain(self, domain_id: UUID) -> DomainSchema:
        entity = await self._get_with_relations(domain_id)
        if entity is None:
            raise NotFoundError("Domain not found.")
        return await self._enrich(entity)

    async def create_domain(self, body: DomainCreate) -> DomainSchema:
        parent = None
        if body.parent_domain_id:
            parent = await self._repo.get_by_id(body.parent_domain_id)
            if parent is None:
                raise NotFoundError("Parent domain not found.")

        # When the caller didn't pick subdomain/alias explicitly, infer from the hostname
        # so "cth.csdttu.online" never lands as another primary domain.
        if body.domain_type == "primary" and body.name and not body.parent_domain_id:
            known = {d.name for d in await self._repo.list_all()}
            guessed_type, parent_name, label = classify_hostname(body.name, known)
            if guessed_type != "primary" and parent_name:
                parent = await self._repo.get_by_name(parent_name)
                if parent is None:
                    parent = await self._ensure_parent(parent_name, [])
                body = body.model_copy(
                    update={
                        "domain_type": guessed_type,
                        "parent_domain_id": parent.id if parent else None,
                        "subdomain_label": body.subdomain_label or label,
                    }
                )

        hostname = self._resolve_hostname(body, parent)
        existing = await self._repo.get_by_name(hostname)
        if existing:
            raise ConflictError(f"Domain '{hostname}' already exists.")

        if body.domain_type in {"subdomain", "alias"} and not parent:
            raise AppException("Parent domain is required for subdomain/alias.", code="parent_required")

        if body.proxy_port is not None:
            parent_shares = bool(
                parent
                and (
                    parent.proxy_port == body.proxy_port
                    or (
                        body.document_root
                        and parent.document_root
                        and parent.document_root == body.document_root
                    )
                )
            )
            if not parent_shares:
                await self._assert_proxy_port_free(body.proxy_port)

        # Defaults for docroot / alias parked behavior
        document_root = body.document_root
        redirect_url = body.redirect_url
        if body.domain_type == "alias" and parent and not document_root and not redirect_url:
            document_root = parent.document_root or f"/var/www/{parent.name}"
        if body.domain_type == "redirect" and not redirect_url:
            raise AppException("redirect_url is required for redirect domains.", code="redirect_required")
        if not document_root and body.domain_type != "redirect":
            document_root = f"/var/www/{hostname}"

        entity = Domain(
            name=hostname,
            domain_type=body.domain_type,
            parent_domain_id=body.parent_domain_id,
            application_id=body.application_id,
            document_root=document_root,
            proxy_port=body.proxy_port,
            enabled=body.enabled,
            force_https=body.force_https,
            redirect_url=redirect_url,
            subdomain_label=body.subdomain_label,
            notes=body.notes,
            nginx_site=self._provisioner.site_name(hostname),
        )
        await self._repo.create(entity)

        # Seed default DNS hints (A @ and www CNAME for primary/addon)
        await self._seed_dns_hints(entity)

        # Reload with relationships before nginx provision (avoid async lazy-load)
        entity = await self._get_with_relations(entity.id)
        if entity is None:
            raise AppException("Domain disappeared after create.", code="domain_missing")

        if body.provision:
            await self._provision_entity(
                entity,
                create_docroot=bool(body.create_docroot) and entity.domain_type != "redirect",
            )
            try:
                from app.services.hosting.webmail_settings import WebmailSettingsStore

                await WebmailSettingsStore(self._settings).ensure_webmail_for_domains(force=True)
            except Exception:  # noqa: BLE001
                pass

        return await self.get_domain(entity.id)

    async def update_domain(self, domain_id: UUID, body: DomainUpdate) -> DomainSchema:
        entity = await self._get_with_relations(domain_id)
        if entity is None:
            raise NotFoundError("Domain not found.")

        enabled_changed = False
        if "application_id" in body.model_fields_set:
            entity.application_id = body.application_id
        if "document_root" in body.model_fields_set:
            entity.document_root = body.document_root
        if "proxy_port" in body.model_fields_set:
            if body.proxy_port is not None:
                await self._assert_proxy_port_free(body.proxy_port, exclude_id=domain_id)
            entity.proxy_port = body.proxy_port
        if body.enabled is not None and body.enabled != entity.enabled:
            entity.enabled = body.enabled
            enabled_changed = True
        if body.force_https is not None:
            entity.force_https = body.force_https
        if "redirect_url" in body.model_fields_set:
            entity.redirect_url = body.redirect_url
        if "notes" in body.model_fields_set:
            entity.notes = body.notes

        await self._repo.update(entity)

        if body.reprovision:
            await self._provision_entity(entity)
        elif enabled_changed:
            await self._provisioner.set_enabled(entity.name, entity.enabled)

        return await self.get_domain(entity.id)

    async def delete_domain(self, domain_id: UUID) -> None:
        entity = await self._repo.get_by_id(domain_id)
        if entity is None:
            raise NotFoundError("Domain not found.")
        await self._provisioner.remove(entity.name, remove_files=True)
        await self._repo.delete(entity)

    async def provision_domain(self, domain_id: UUID, *, ensure_https: bool = True) -> OperationResult:
        entity = await self._get_with_relations(domain_id)
        if entity is None:
            raise NotFoundError("Domain not found.")
        return await self._provision_entity(entity, ensure_https=ensure_https)

    async def reprovision_all(self) -> list[OperationResult]:
        """Ensure /mail webmail on all nginx sites; fully reprovision IFNOTUS-managed domains."""
        results: list[OperationResult] = [
            await self._provisioner.ensure_webmail_on_all_sites(),
        ]
        entities = await self._repo.list_all()
        for entity in entities:
            if not entity.enabled:
                continue
            available, _ = self._provisioner.site_paths(entity.name)
            try:
                text = available.read_text(encoding="utf-8", errors="replace") if available.exists() else ""
            except OSError:
                text = ""
            if MANAGED_MARKER not in text and available.exists():
                # Custom / imported vhosts: /mail was injected above; don't rewrite.
                continue
            try:
                full = await self._get_with_relations(entity.id)
                if full is None:
                    continue
                results.append(await self._provision_entity(full))
            except Exception as exc:  # noqa: BLE001
                results.append(
                    OperationResult(
                        success=False,
                        message=f"{entity.name}: {exc}",
                        details={"domain": entity.name},
                    )
                )
        return results

    async def import_discovered(self, body: DomainImportRequest) -> DomainSchema:
        name = body.server_name.strip().lower()
        existing = await self._repo.get_by_name(name)
        if existing:
            raise ConflictError(f"Domain '{name}' already exists.")

        sites = await asyncio.to_thread(self._nginx_discovery.scan_sites)
        match = next((s for s in sites if s.server_name == name), None)
        proxy_port = None
        if match and match.proxy_pass:
            import re

            m = re.search(r":(\d+)", match.proxy_pass)
            if m:
                proxy_port = int(m.group(1))

        known = {s.server_name for s in sites}
        for row in await self._repo.list_all():
            known.add(row.name)
        domain_type = body.domain_type
        parent_id = body.parent_domain_id
        label = None
        if not parent_id or domain_type == "primary":
            guessed_type, parent_name, label = classify_hostname(name, known - {name})
            if body.domain_type == "primary" or not body.parent_domain_id:
                domain_type = guessed_type
            if parent_name and not parent_id:
                parent = await self._ensure_parent(parent_name, sites)
                parent_id = parent.id if parent else None

        create = DomainCreate(
            name=name,
            domain_type=domain_type,
            parent_domain_id=parent_id,
            subdomain_label=label,
            document_root=match.document_root if match else None,
            proxy_port=proxy_port,
            provision=False,
            create_docroot=False,
            notes="Imported from nginx discovery",
        )
        parent = None
        if create.parent_domain_id:
            parent = await self._repo.get_by_id(create.parent_domain_id)
        hostname = self._resolve_hostname(create, parent)
        entity = Domain(
            name=hostname,
            domain_type=create.domain_type,
            parent_domain_id=create.parent_domain_id,
            document_root=create.document_root,
            proxy_port=create.proxy_port,
            subdomain_label=create.subdomain_label,
            enabled=True,
            notes=create.notes,
            nginx_site=self._provisioner.site_name(hostname),
            nginx_enabled=bool(match.enabled) if match else True,
            force_https=False,
        )
        await self._repo.create(entity)
        await self._seed_dns_hints(entity)
        return await self.get_domain(entity.id)

    async def check_dns(self, domain_name: str) -> DnsCheckResponse:
        name = domain_name.lower().strip()
        addresses: list[str] = []
        resolves = False
        message = None
        try:
            loop = asyncio.get_event_loop()
            infos = await loop.getaddrinfo(name, None, type=socket.SOCK_STREAM)
            addresses = sorted({info[4][0] for info in infos})
            resolves = bool(addresses)
        except socket.gaierror as exc:
            message = str(exc)

        server_ip = self._settings.server_public_ip
        points = None
        if server_ip and addresses:
            points = server_ip in addresses

        entity = await self._repo.get_by_name(name)
        if entity:
            entity.dns_points_here = points
            await self._repo.update(entity)

        suggested: list[dict] = []
        if server_ip:
            suggested = [
                {"record_type": "A", "host": "@", "value": server_ip, "ttl": 3600},
                {"record_type": "CNAME", "host": "www", "value": name, "ttl": 3600},
            ]

        return DnsCheckResponse(
            domain=name,
            resolves=resolves,
            addresses=addresses,
            points_to_server=points,
            server_ip=server_ip,
            message=message,
            suggested_records=suggested,
        )

    # ── Redirects ──────────────────────────────────────────────────────────

    async def list_redirects(self, domain_id: UUID) -> list[DomainRedirectSchema]:
        entity = await self._get_with_relations(domain_id)
        if entity is None:
            raise NotFoundError("Domain not found.")
        return [self._redirect_schema(r) for r in entity.redirects]

    async def create_redirect(self, domain_id: UUID, body: DomainRedirectCreate) -> DomainRedirectSchema:
        entity = await self._get_with_relations(domain_id)
        if entity is None:
            raise NotFoundError("Domain not found.")
        source = body.source_path if body.source_path.startswith("/") else f"/{body.source_path}"
        existing = next((r for r in entity.redirects if r.source_path == source), None)
        if existing is not None:
            raise ConflictError(f"A redirect for {source} already exists.")
        row = DomainRedirect(
            domain_id=domain_id,
            source_path=source,
            target_url=body.target_url,
            status_code=body.status_code,
            enabled=body.enabled,
        )
        self._session.add(row)
        await self._session.flush()
        await self._session.refresh(row)
        entity.redirects.append(row)
        await self._provision_entity(entity)
        return self._redirect_schema(row)

    async def delete_redirect(self, domain_id: UUID, redirect_id: UUID) -> OperationResult:
        entity = await self._get_with_relations(domain_id)
        if entity is None:
            raise NotFoundError("Domain not found.")
        row = next((r for r in entity.redirects if r.id == redirect_id), None)
        if row is None:
            raise NotFoundError("Redirect not found.")
        await self._session.delete(row)
        await self._session.flush()
        entity.redirects = [r for r in entity.redirects if r.id != redirect_id]
        await self._provision_entity(entity)
        return OperationResult(success=True, message="Redirect deleted.")

    # ── DNS records (zone editor hints) ────────────────────────────────────

    async def list_dns_records(self, domain_id: UUID) -> list[DomainDnsRecordSchema]:
        entity = await self._get_with_relations(domain_id)
        if entity is None:
            raise NotFoundError("Domain not found.")
        return [self._dns_schema(r) for r in entity.dns_records]

    async def create_dns_record(self, domain_id: UUID, body: DomainDnsRecordCreate) -> DomainDnsRecordSchema:
        entity = await self._repo.get_by_id(domain_id)
        if entity is None:
            raise NotFoundError("Domain not found.")
        row = DomainDnsRecord(
            domain_id=domain_id,
            record_type=body.record_type.upper(),
            host=body.host.strip() or "@",
            value=body.value.strip(),
            ttl=body.ttl,
            priority=body.priority,
        )
        self._session.add(row)
        await self._session.flush()
        await self._session.refresh(row)
        return self._dns_schema(row)

    async def delete_dns_record(self, domain_id: UUID, record_id: UUID) -> OperationResult:
        stmt = select(DomainDnsRecord).where(
            DomainDnsRecord.id == record_id,
            DomainDnsRecord.domain_id == domain_id,
        )
        result = await self._session.execute(stmt)
        row = result.scalar_one_or_none()
        if row is None:
            raise NotFoundError("DNS record not found.")
        await self._session.delete(row)
        await self._session.flush()
        return OperationResult(success=True, message="DNS record removed.")

    # ── Internals ──────────────────────────────────────────────────────────

    async def _sync_from_nginx(self, nginx_sites) -> None:
        """Import missing nginx hostnames and fix domain_type / parent links.

        Apexes are created first so subdomains can attach to a real parent row.
        Existing rows that were wrongly stored as ``primary`` are reclassified.
        """
        if not nginx_sites:
            return

        existing = await self._repo.list_all()
        by_name = {d.name: d for d in existing}
        known = {s.server_name for s in nginx_sites} | set(by_name)
        site_by_name = {s.server_name: s for s in nginx_sites}

        # Create missing apex / primary hostnames before children.
        ordered = sorted(nginx_sites, key=lambda s: (s.server_name.count("."), s.server_name))
        changed = False
        for site in ordered:
            name = site.server_name
            if name in by_name:
                continue
            domain_type, parent_name, label = classify_hostname(name, known - {name})
            parent_id = None
            if parent_name:
                parent = by_name.get(parent_name)
                if parent is None:
                    parent = await self._ensure_parent(parent_name, nginx_sites)
                    if parent:
                        by_name[parent.name] = parent
                        known.add(parent.name)
                parent_id = parent.id if parent else None
                if parent is None:
                    domain_type = "primary"
                    label = None

            proxy_port = None
            if site.proxy_pass:
                import re

                m = re.search(r":(\d+)", site.proxy_pass)
                if m:
                    proxy_port = int(m.group(1))

            entity = Domain(
                name=name,
                domain_type=domain_type,
                parent_domain_id=parent_id,
                subdomain_label=label,
                document_root=site.document_root,
                proxy_port=proxy_port,
                enabled=bool(site.enabled),
                nginx_enabled=bool(site.enabled),
                nginx_site=self._provisioner.site_name(name),
                notes="Auto-imported from nginx",
                force_https=False,
            )
            await self._repo.create(entity)
            await self._seed_dns_hints(entity)
            by_name[name] = entity
            known.add(name)
            changed = True

        # Reclassify rows that look like subdomains / www aliases of a known parent.
        for entity in list(by_name.values()):
            domain_type, parent_name, label = classify_hostname(entity.name, known - {entity.name})
            if domain_type == "primary":
                continue
            parent = by_name.get(parent_name) if parent_name else None
            if parent is None and parent_name:
                parent = await self._ensure_parent(parent_name, nginx_sites)
                if parent:
                    by_name[parent.name] = parent
                    known.add(parent.name)
            if parent is None:
                continue
            dirty = False
            if entity.domain_type != domain_type:
                entity.domain_type = domain_type
                dirty = True
            if entity.parent_domain_id != parent.id:
                entity.parent_domain_id = parent.id
                dirty = True
            if label and entity.subdomain_label != label:
                entity.subdomain_label = label
                dirty = True
            site = site_by_name.get(entity.name)
            if site and not entity.document_root and site.document_root:
                entity.document_root = site.document_root
                dirty = True
            if site and entity.nginx_enabled is None:
                entity.nginx_enabled = bool(site.enabled)
                dirty = True
            if dirty:
                await self._repo.update(entity)
                changed = True

        if changed:
            await self._session.commit()

    async def _ensure_parent(self, parent_name: str, nginx_sites) -> Domain | None:
        existing = await self._repo.get_by_name(parent_name)
        if existing:
            return existing
        site = next((s for s in nginx_sites if s.server_name == parent_name), None)
        entity = Domain(
            name=parent_name,
            domain_type="primary",
            document_root=site.document_root if site else f"/var/www/{parent_name}",
            enabled=bool(site.enabled) if site else True,
            nginx_enabled=bool(site.enabled) if site else None,
            nginx_site=self._provisioner.site_name(parent_name),
            notes="Auto-created parent for subdomain/alias",
            force_https=False,
        )
        await self._repo.create(entity)
        await self._seed_dns_hints(entity)
        return entity

    def _resolve_hostname(self, body: DomainCreate, parent: Domain | None) -> str:
        if body.domain_type == "subdomain":
            if body.subdomain_label and parent:
                return f"{body.subdomain_label}.{parent.name}"
            if body.name:
                return body.name.strip().lower()
            raise AppException("Provide subdomain_label + parent, or full hostname.", code="name_required")
        if not body.name:
            raise AppException("Domain name is required.", code="name_required")
        return body.name.strip().lower()

    async def _seed_dns_hints(self, entity: Domain) -> None:
        server_ip = self._settings.server_public_ip
        if not server_ip:
            return
        seeds = [
            DomainDnsRecord(
                domain_id=entity.id,
                record_type="A",
                host="@",
                value=server_ip,
                ttl=3600,
            ),
        ]
        if entity.domain_type in {"primary", "addon"}:
            seeds.extend([
                DomainDnsRecord(
                    domain_id=entity.id,
                    record_type="CNAME",
                    host="www",
                    value=entity.name,
                    ttl=3600,
                ),
                DomainDnsRecord(
                    domain_id=entity.id,
                    record_type="A",
                    host="fpanel",
                    value=server_ip,
                    ttl=3600,
                ),
                DomainDnsRecord(
                    domain_id=entity.id,
                    record_type="A",
                    host="webmail",
                    value=server_ip,
                    ttl=3600,
                ),
                DomainDnsRecord(
                    domain_id=entity.id,
                    record_type="A",
                    host="mail",
                    value=server_ip,
                    ttl=3600,
                ),
            ])
        for row in seeds:
            self._session.add(row)
        await self._session.flush()

    async def _provision_entity(
        self,
        entity: Domain,
        *,
        create_docroot: bool | None = None,
        ensure_https: bool = True,
    ) -> OperationResult:
        aliases: list[str] = []
        # Include alias-type children that share this as parent and park on same vhost? 
        # Simpler: each hostname gets its own vhost.
        path_redirects = [
            {
                "source_path": r.source_path,
                "target_url": r.target_url,
                "status_code": r.status_code,
                "enabled": r.enabled,
            }
            for r in list(entity.__dict__.get("redirects") or [])
        ]
        # Whole-domain redirect for type=redirect uses redirect_url
        redirect_url = entity.redirect_url
        if entity.domain_type == "redirect":
            redirect_url = entity.redirect_url

        from pathlib import Path

        from app.services.hosting.ssl import SslService

        le = Path(f"/etc/letsencrypt/live/{entity.name}/fullchain.pem")
        if SslService.is_ifnotus_hostname(entity.name) and le.exists():
            entity.ssl_certificate_path = str(le)
            entity.force_https = True

        # Ensure Authoritative DNS zone is written / reloaded
        try:
            from app.services.platform.authoritative_dns import AuthoritativeDnsService
            from app.services.platform.panel_access import is_platform_hostname

            if not is_platform_hostname(entity.name, settings=self._settings) and not entity.name.endswith(".customers.ifnotus.space"):
                AuthoritativeDnsService(self._settings).ensure_zone(entity.name)
            elif entity.name.endswith(".customers.ifnotus.space"):
                AuthoritativeDnsService(self._settings).ensure_generated_environment_dns(entity.name)
        except Exception as dns_exc:  # noqa: BLE001
            logger.warning("domain_dns_zone_ensure_failed", domain=entity.name, error=str(dns_exc))

        result = await self._provisioner.provision(
            hostname=entity.name,
            document_root=entity.document_root,
            proxy_port=entity.proxy_port,
            force_https=bool(entity.force_https),
            redirect_url=redirect_url,
            aliases=aliases,
            ssl_certificate=entity.ssl_certificate_path,
            enabled=bool(entity.enabled),
            create_docroot=entity.domain_type != "redirect" if create_docroot is None else bool(create_docroot),
            path_redirects=path_redirects,
        )
        if not result.success:
            raise AppException(result.message, code="nginx_provision_failed")
        entity.nginx_site = self._provisioner.site_name(entity.name)
        entity.nginx_enabled = entity.enabled
        await self._repo.update(entity)

        if (
            ensure_https
            and not le.exists()
            and entity.name
            not in {
                "ifnotus.space",
                getattr(self._settings, "student_zone", "ifnotus.space"),
                getattr(self._settings, "legacy_student_zone", "serverlabsttu.space"),
            }
        ):
            try:
                from app.schemas.hosting import SslActionRequest

                issued = await SslService(self._settings, self._session).issue(
                    SslActionRequest(domain=entity.name, webroot="/var/www/letsencrypt", dry_run=False)
                )
                if not issued.success:
                    logger.warning("auto_https_failed", domain=entity.name, error=issued.message)
            except Exception as exc:  # noqa: BLE001
                logger.warning("auto_https_failed", domain=entity.name, error=str(exc))
        return result

    async def _list_with_relations(self) -> list[Domain]:
        stmt = (
            select(Domain)
            .options(selectinload(Domain.redirects), selectinload(Domain.dns_records))
            .order_by(Domain.name)
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().unique().all())

    async def _get_with_relations(self, domain_id: UUID) -> Domain | None:
        stmt = (
            select(Domain)
            .where(Domain.id == domain_id)
            .options(selectinload(Domain.redirects), selectinload(Domain.dns_records))
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def _assert_proxy_port_free(self, port: int, exclude_id: UUID | None = None) -> None:
        domains = await self._repo.list_all()
        for d in domains:
            if exclude_id and d.id == exclude_id:
                continue
            if d.proxy_port == port:
                raise ConflictError(f"Port {port} is already assigned to domain '{d.name}'.")
        listening, _ = self._port_inventory(domains)
        if port in listening:
            raise ConflictError(f"Port {port} is already in use on this server.")

    def _port_inventory(self, domains: list[Domain]) -> tuple[list[int], list[int]]:
        listening: set[int] = set()
        try:
            for conn in psutil.net_connections(kind="inet"):
                if conn.status == psutil.CONN_LISTEN and conn.laddr:
                    listening.add(int(conn.laddr.port))
        except (psutil.Error, PermissionError, OSError):
            pass
        reserved = {d.proxy_port for d in domains if d.proxy_port}
        taken = listening | reserved
        available = [p for p in _APP_PORT_RANGE if p not in taken][:24]
        return sorted(listening), available

    def _enrich_from_site(self, entity: Domain, site) -> DomainSchema:
        nginx_enabled = entity.nginx_enabled
        if site is not None:
            nginx_enabled = bool(site.enabled)
        return DomainSchema(
            id=entity.id,
            name=entity.name,
            domain_type=entity.domain_type,
            parent_domain_id=entity.parent_domain_id,
            application_id=entity.application_id,
            document_root=entity.document_root or (site.document_root if site else None),
            proxy_port=entity.proxy_port,
            enabled=entity.enabled,
            dns_points_here=entity.dns_points_here,
            nginx_enabled=nginx_enabled,
            ssl_certificate_path=entity.ssl_certificate_path,
            force_https=bool(getattr(entity, "force_https", False)),
            redirect_url=getattr(entity, "redirect_url", None),
            nginx_site=getattr(entity, "nginx_site", None),
            subdomain_label=getattr(entity, "subdomain_label", None),
            notes=entity.notes,
            created_at=entity.created_at,
            updated_at=entity.updated_at,
            redirects=[self._redirect_schema(r) for r in getattr(entity, "redirects", []) or []],
            dns_records=[self._dns_schema(r) for r in getattr(entity, "dns_records", []) or []],
        )

    async def _enrich(self, entity: Domain) -> DomainSchema:
        nginx = await asyncio.to_thread(self._nginx.read, None, entity.name)
        return DomainSchema(
            id=entity.id,
            name=entity.name,
            domain_type=entity.domain_type,
            parent_domain_id=entity.parent_domain_id,
            application_id=entity.application_id,
            document_root=entity.document_root,
            proxy_port=entity.proxy_port,
            enabled=entity.enabled,
            dns_points_here=entity.dns_points_here,
            nginx_enabled=nginx.enabled if nginx.configured else entity.nginx_enabled,
            ssl_certificate_path=entity.ssl_certificate_path,
            force_https=bool(getattr(entity, "force_https", False)),
            redirect_url=getattr(entity, "redirect_url", None),
            nginx_site=getattr(entity, "nginx_site", None),
            subdomain_label=getattr(entity, "subdomain_label", None),
            notes=entity.notes,
            created_at=entity.created_at,
            updated_at=entity.updated_at,
            redirects=[self._redirect_schema(r) for r in getattr(entity, "redirects", []) or []],
            dns_records=[self._dns_schema(r) for r in getattr(entity, "dns_records", []) or []],
        )

    @staticmethod
    def _redirect_schema(row: DomainRedirect) -> DomainRedirectSchema:
        return DomainRedirectSchema(
            id=row.id,
            domain_id=row.domain_id,
            source_path=row.source_path,
            target_url=row.target_url,
            status_code=row.status_code,
            enabled=row.enabled,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )

    @staticmethod
    def _dns_schema(row: DomainDnsRecord) -> DomainDnsRecordSchema:
        return DomainDnsRecordSchema(
            id=row.id,
            domain_id=row.domain_id,
            record_type=row.record_type,
            host=row.host,
            value=row.value,
            ttl=row.ttl,
            priority=row.priority,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )
