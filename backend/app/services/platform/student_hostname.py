"""Allocate unique student hostnames under the student project zone.

New assignments use ifnotus.space (configurable via Settings.student_zone).
Legacy *.serverlabsttu.space student hostnames remain recognized and are never
mass-renamed by this module.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConflictError, ValidationError
from app.models.hosting import Domain
from app.models.platform import CustomerDomain, CustomerEnvironment, Order
from app.services.platform.reserved_subdomains import (
    RESERVED_PLATFORM_SUBDOMAINS,
    is_reserved_platform_subdomain,
    normalize_dns_label,
)

# Active assignment zone. Control-plane hostnames stay reserved under ifnotus.space.
STUDENT_ZONE = "ifnotus.space"
LEGACY_STUDENT_ZONE = "serverlabsttu.space"
MAX_SUFFIX = 999

# Backward-compatible alias — always the central reserved set.
RESERVED_LABELS = RESERVED_PLATFORM_SUBDOMAINS

_ACTIVE_ORDER = {"pending", "submitted", "paid"}
_DEAD_PROVISION = {"failed", "cancelled", "canceled"}


def resolve_student_zone(settings: object | None = None) -> str:
    """Return the zone used for *new* student hostname assignments."""
    if settings is not None:
        raw = getattr(settings, "student_zone", None)
        if isinstance(raw, str) and raw.strip():
            return raw.strip().lower().rstrip(".")
    return STUDENT_ZONE


def resolve_legacy_student_zone(settings: object | None = None) -> str:
    if settings is not None:
        raw = getattr(settings, "legacy_student_zone", None)
        if isinstance(raw, str) and raw.strip():
            return raw.strip().lower().rstrip(".")
    return LEGACY_STUDENT_ZONE


def student_zone_extension(settings: object | None = None) -> str:
    return f".{resolve_student_zone(settings)}"


def all_student_zones(settings: object | None = None) -> tuple[str, ...]:
    active = resolve_student_zone(settings)
    legacy = resolve_legacy_student_zone(settings)
    if active == legacy:
        return (active,)
    return (active, legacy)


def normalize_surname(raw: str) -> str:
    text = unicodedata.normalize("NFKD", raw or "")
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = re.sub(r"[''`´‘’]", "", text)
    return normalize_dns_label(text, max_len=32)


def student_label(base: str, index: int) -> str:
    """Duplicate variants: mensah, mensah2, mensah3 (skip mensah1)."""
    if index <= 0:
        return base
    return f"{base}{index + 1}"


def student_hostname(base: str, index: int = 0, *, zone: str | None = None) -> str:
    z = (zone or STUDENT_ZONE).strip().lower().rstrip(".")
    return f"{student_label(base, index)}.{z}"


def student_zone_of(name: str | None, *, settings: object | None = None) -> str | None:
    """Return the student zone for a hostname, or None if not a student host."""
    host = (name or "").strip().lower().rstrip(".")
    if not host or host.endswith(".customers.ifnotus.space"):
        return None
    for zone in all_student_zones(settings):
        suffix = f".{zone}"
        if not host.endswith(suffix):
            continue
        label = host[: -len(suffix)]
        if label and "." not in label:
            return zone
    return None


def is_student_hostname(name: str | None, *, settings: object | None = None) -> bool:
    """True for single-label hosts under the active or legacy student zone."""
    return student_zone_of(name, settings=settings) is not None


def is_legacy_student_hostname(name: str | None, *, settings: object | None = None) -> bool:
    zone = student_zone_of(name, settings=settings)
    return zone is not None and zone == resolve_legacy_student_zone(settings)


def is_active_student_hostname(name: str | None, *, settings: object | None = None) -> bool:
    zone = student_zone_of(name, settings=settings)
    return zone is not None and zone == resolve_student_zone(settings)


class StudentHostnameService:
    def __init__(self, session: AsyncSession, settings: object | None = None) -> None:
        self._session = session
        self._settings = settings
        self._zone = resolve_student_zone(settings)

    async def preview(self, surname: str) -> dict:
        base = self._require_base(surname)
        hostname = await self._next_free(base)
        return {
            "surname": base,
            "hostname": hostname,
            "available": True,
            "zone": self._zone,
            "message": f"Your site will be {hostname}",
        }

    async def allocate(self, surname: str, *, exclude_order_id: UUID | None = None) -> str:
        """Pick the next free student hostname for a surname (surname, surname1, …)."""
        base = self._require_base(surname)
        await self._lock(base)
        return await self._next_free(base, exclude_order_id=exclude_order_id)

    async def claim(self, hostname: str, *, exclude_order_id: UUID | None = None) -> str:
        host = (hostname or "").strip().lower().rstrip(".")
        if not is_student_hostname(host, settings=self._settings):
            raise ValidationError("That is not a valid student address.", code="student_hostname_invalid")
        label = host.split(".", 1)[0]
        if is_reserved_platform_subdomain(label, settings=self._settings):
            raise ValidationError(
                "That name is reserved for IFNOTUS. Choose another project label.",
                code="student_surname_reserved",
            )
        base = re.sub(r"\d+$", "", label) or label
        if is_reserved_platform_subdomain(base, settings=self._settings):
            raise ValidationError(
                "That name is reserved for IFNOTUS. Choose another project label.",
                code="student_surname_reserved",
            )
        await self._lock(base)
        if await self._is_taken(host, exclude_order_id=exclude_order_id):
            raise ConflictError("That student address is already in use.", code="student_hostname_taken")
        return host

    def _require_base(self, surname: str) -> str:
        base = normalize_surname(surname)
        if len(base) < 2:
            raise ValidationError(
                "Enter your surname using letters only (at least 2 letters).",
                code="student_surname_invalid",
            )
        if is_reserved_platform_subdomain(base, settings=self._settings):
            raise ValidationError(
                "That name is reserved for IFNOTUS. Choose another project label.",
                code="student_surname_reserved",
            )
        return base

    async def _lock(self, base: str) -> None:
        try:
            conn = await self._session.connection()
            if conn.dialect.name != "postgresql":
                return
        except Exception:  # noqa: BLE001
            return
        key = int.from_bytes(hashlib.sha256(f"ifnotus-student:{base}".encode()).digest()[:4], "big") & 0x7FFFFFFF
        await self._session.execute(select(func.pg_advisory_xact_lock(key)))

    async def _next_free(self, base: str, *, exclude_order_id: UUID | None = None) -> str:
        for index in range(0, MAX_SUFFIX + 1):
            hostname = student_hostname(base, index, zone=self._zone)
            if not await self._is_taken(hostname, exclude_order_id=exclude_order_id):
                return hostname
        raise ConflictError(
            "Could not assign a student address for that surname. Try a longer surname.",
            code="student_hostname_exhausted",
        )

    async def _is_taken(self, hostname: str, *, exclude_order_id: UUID | None = None) -> bool:
        domain = await self._session.execute(select(Domain.id).where(func.lower(Domain.name) == hostname))
        if domain.scalar_one_or_none() is not None:
            return True

        env = await self._session.execute(
            select(CustomerEnvironment.id).where(func.lower(CustomerEnvironment.domain) == hostname)
        )
        if env.scalar_one_or_none() is not None:
            return True

        owned = await self._session.execute(
            select(CustomerDomain.id).where(func.lower(CustomerDomain.domain_name) == hostname)
        )
        if owned.scalar_one_or_none() is not None:
            return True

        stmt = select(Order.id).where(
            func.lower(Order.domain_name) == hostname,
            Order.payment_status.in_(_ACTIVE_ORDER),
            or_(Order.provisioning_status.is_(None), Order.provisioning_status.notin_(_DEAD_PROVISION)),
            or_(
                Order.payment_status == "paid",
                Order.expires_at.is_(None),
                Order.expires_at > datetime.now(UTC),
            ),
        )
        if exclude_order_id is not None:
            stmt = stmt.where(Order.id != exclude_order_id)
        row = await self._session.execute(stmt.limit(1))
        return row.scalar_one_or_none() is not None
