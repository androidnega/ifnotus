"""Domain management service."""

from __future__ import annotations

import asyncio
import socket
from datetime import UTC, datetime
from uuid import UUID

import psutil
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.exceptions import ConflictError, NotFoundError
from app.models.hosting import Domain
from app.repositories.domain import DomainRepository
from app.schemas.hosting import (
    DnsCheckResponse,
    DomainCreate,
    DomainListResponse,
    DomainSchema,
    DomainUpdate,
)
from app.services.applications.readers.nginx import NginxReader
from app.services.hosting.nginx_discovery import NginxDiscoveryService

# Preferred range for reverse-proxy app backends (avoid system / nginx 80/443).
_APP_PORT_RANGE = range(8000, 9101)


class DomainService:
    def __init__(self, settings: Settings, session: AsyncSession) -> None:
        self._settings = settings
        self._repo = DomainRepository(session)
        self._nginx = NginxReader()
        self._nginx_discovery = NginxDiscoveryService(settings)

    async def list_domains(self) -> DomainListResponse:
        domains = await self._repo.list_all()
        enriched = [await self._enrich(d) for d in domains]
        nginx_sites = self._nginx_discovery.scan_sites()
        db_names = {d.name for d in domains}

        discovered = [s for s in nginx_sites if s.server_name not in db_names]
        drift_count = 0
        for entity in domains:
            site = next((s for s in nginx_sites if s.server_name == entity.name), None)
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

        listening, available = self._port_inventory(domains)

        return DomainListResponse(
            timestamp=datetime.now(UTC),
            total=len(enriched),
            domains=enriched,
            discovered=discovered,
            discovered_total=len(discovered),
            drift_count=drift_count,
            listening_ports=listening,
            available_ports=available,
        )

    async def get_domain(self, domain_id: UUID) -> DomainSchema:
        entity = await self._repo.get_by_id(domain_id)
        if entity is None:
            raise NotFoundError("Domain not found.")
        return await self._enrich(entity)

    async def create_domain(self, body: DomainCreate) -> DomainSchema:
        existing = await self._repo.get_by_name(body.name)
        if existing:
            raise ConflictError(f"Domain '{body.name}' already exists.")

        if body.parent_domain_id:
            parent = await self._repo.get_by_id(body.parent_domain_id)
            if parent is None:
                raise NotFoundError("Parent domain not found.")

        if body.proxy_port is not None:
            await self._assert_proxy_port_free(body.proxy_port)

        entity = Domain(
            name=body.name.lower(),
            domain_type=body.domain_type,
            parent_domain_id=body.parent_domain_id,
            application_id=body.application_id,
            document_root=body.document_root,
            proxy_port=body.proxy_port,
            enabled=body.enabled,
            notes=body.notes,
        )
        await self._repo.create(entity)
        return await self._enrich(entity)

    async def update_domain(self, domain_id: UUID, body: DomainUpdate) -> DomainSchema:
        entity = await self._repo.get_by_id(domain_id)
        if entity is None:
            raise NotFoundError("Domain not found.")
        if "application_id" in body.model_fields_set:
            entity.application_id = body.application_id
        if "document_root" in body.model_fields_set:
            entity.document_root = body.document_root
        if "proxy_port" in body.model_fields_set:
            if body.proxy_port is not None:
                await self._assert_proxy_port_free(body.proxy_port, exclude_id=domain_id)
            entity.proxy_port = body.proxy_port
        if body.enabled is not None:
            entity.enabled = body.enabled
        if "notes" in body.model_fields_set:
            entity.notes = body.notes
        await self._repo.update(entity)
        return await self._enrich(entity)

    async def delete_domain(self, domain_id: UUID) -> None:
        entity = await self._repo.get_by_id(domain_id)
        if entity is None:
            raise NotFoundError("Domain not found.")
        await self._repo.delete(entity)

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

        return DnsCheckResponse(
            domain=name,
            resolves=resolves,
            addresses=addresses,
            points_to_server=points,
            server_ip=server_ip,
            message=message,
        )

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
            nginx_enabled=nginx.enabled if nginx.configured else None,
            ssl_certificate_path=entity.ssl_certificate_path,
            notes=entity.notes,
            created_at=entity.created_at,
            updated_at=entity.updated_at,
        )
