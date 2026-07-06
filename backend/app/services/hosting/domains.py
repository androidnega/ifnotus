"""Domain management service."""

from __future__ import annotations

import asyncio
import socket
from datetime import UTC, datetime
from uuid import UUID

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


class DomainService:
    def __init__(self, settings: Settings, session: AsyncSession) -> None:
        self._settings = settings
        self._repo = DomainRepository(session)
        self._nginx = NginxReader()

    async def list_domains(self) -> DomainListResponse:
        domains = await self._repo.list_all()
        enriched = [await self._enrich(d) for d in domains]
        return DomainListResponse(
            timestamp=datetime.now(UTC),
            total=len(enriched),
            domains=enriched,
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

        entity = Domain(
            name=body.name.lower(),
            domain_type=body.domain_type,
            parent_domain_id=body.parent_domain_id,
            application_id=body.application_id,
            document_root=body.document_root,
            enabled=body.enabled,
            notes=body.notes,
        )
        await self._repo.create(entity)
        return await self._enrich(entity)

    async def update_domain(self, domain_id: UUID, body: DomainUpdate) -> DomainSchema:
        entity = await self._repo.get_by_id(domain_id)
        if entity is None:
            raise NotFoundError("Domain not found.")
        if body.application_id is not None:
            entity.application_id = body.application_id
        if body.document_root is not None:
            entity.document_root = body.document_root
        if body.enabled is not None:
            entity.enabled = body.enabled
        if body.notes is not None:
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

    async def _enrich(self, entity: Domain) -> DomainSchema:
        nginx = await asyncio.to_thread(self._nginx.read, None, entity.name)
        return DomainSchema(
            id=entity.id,
            name=entity.name,
            domain_type=entity.domain_type,
            parent_domain_id=entity.parent_domain_id,
            application_id=entity.application_id,
            document_root=entity.document_root,
            enabled=entity.enabled,
            dns_points_here=entity.dns_points_here,
            nginx_enabled=nginx.enabled if nginx.configured else None,
            ssl_certificate_path=entity.ssl_certificate_path,
            notes=entity.notes,
            created_at=entity.created_at,
            updated_at=entity.updated_at,
        )
