"""Automatic clean hosting names — customer never picks or resolves collisions.

Examples: manuelhost, manuelh2, kwofiehost, csdttu, votebridge.

Max length 12. UUID remains the permanent DB identifier.
Filesystem paths and unix usernames are separate concerns.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppException
from app.models.platform import Customer, CustomerEnvironment
from app.services.platform.reserved_subdomains import is_reserved_label
from app.services.platform.student_hostname import is_student_hostname

MAX_HOSTING_NAME_LEN = 12

_HOSTING_NAME_RESERVED = frozenset(
    {
        "admin",
        "root",
        "system",
        "server",
        "host",
        "hosting",
        "mail",
        "fpanel",
        "cpanel",
        "panel",
        "api",
        "mysql",
        "postgres",
        "redis",
        "ftp",
        "sftp",
        "ssh",
        "backup",
        "support",
        "billing",
        "www",
        "ifnotus",
        "tenant",
        "customer",
        "env",
    }
)


def _ascii_fold(raw: str) -> str:
    text = unicodedata.normalize("NFKD", raw or "")
    return "".join(ch for ch in text if not unicodedata.combining(ch))


def _letters_only(raw: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", _ascii_fold(raw).strip().lower())


def _starts_with_letter(text: str) -> str:
    text = text.lstrip("0123456789-_")
    return text or "sitehost"


def domain_label(domain: str | None) -> str:
    host = (domain or "").strip().lower().rstrip(".")
    if not host:
        return ""
    if host.startswith("www."):
        host = host[4:]
    if host.startswith("fpanel."):
        host = host[len("fpanel.") :]
    elif host.startswith("cpanel."):
        host = host[len("cpanel.") :]
    if host.startswith("mail."):
        host = host[len("mail.") :]
    return _letters_only(host.split(".", 1)[0])


def candidate_bases(
    *,
    domain: str | None = None,
    hostname: str | None = None,
    first_name: str | None = None,
    last_name: str | None = None,
) -> list[str]:
    """Priority: custom domain → student+host → surname+host → first+host."""
    out: list[str] = []
    for source in (domain, hostname):
        label = domain_label(source)
        if not label:
            continue
        if is_student_hostname(source or ""):
            out.append(f"{label}host")
        else:
            out.append(label)
    last = _letters_only(last_name or "")
    first = _letters_only(first_name or "")
    if last:
        out.append(f"{last}host")
    if first:
        out.append(f"{first}host")
    if not out:
        out.append("sitehost")

    seen: set[str] = set()
    ordered: list[str] = []
    for item in out:
        base = _starts_with_letter(item)[:MAX_HOSTING_NAME_LEN]
        if len(base) < 2:
            continue
        if base not in seen:
            seen.add(base)
            ordered.append(base)
    return ordered or ["sitehost"]


def is_hosting_name_reserved(name: str | None) -> bool:
    raw = _letters_only(name or "")
    if not raw:
        return True
    if raw in _HOSTING_NAME_RESERVED:
        return True
    return is_reserved_label(raw)


def with_suffix(base: str, index: int) -> str:
    """manuelhost → manuelhost; then manuelh2, manuelh3. csdttu → csdttu2."""
    base = _starts_with_letter(_letters_only(base))[:MAX_HOSTING_NAME_LEN]
    if index <= 0:
        return base
    n = index + 1  # first collision → 2
    suffix = str(n)
    stem = base
    # Compact *host names: manuelhost → manuelh2 (spec examples).
    if stem.endswith("host") and len(stem) > 4:
        stem = f"{stem[:-4]}h"
    room = MAX_HOSTING_NAME_LEN - len(suffix)
    if room < 1:
        return f"h{suffix}"[-MAX_HOSTING_NAME_LEN:]
    stem = stem[:room]
    if not stem or not stem[0].isalpha():
        stem = ("site" + stem)[:room]
    return f"{stem}{suffix}"


def iter_name_candidates(bases: list[str], *, max_per_base: int = 500):
    seen: set[str] = set()
    for base in bases:
        for index in range(0, max_per_base):
            name = with_suffix(base, index)
            if len(name) < 2 or not name[0].isalpha():
                continue
            if is_hosting_name_reserved(name):
                continue
            if name in seen:
                continue
            seen.add(name)
            yield name
    for n in range(2, 100000):
        name = f"site{n}"[:MAX_HOSTING_NAME_LEN]
        if name in seen or is_hosting_name_reserved(name) or not name[0].isalpha():
            continue
        seen.add(name)
        yield name


class HostingNameService:
    """Single source of truth for hosting_name generation."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def _taken(self, name: str, *, exclude_id: UUID | None = None) -> bool:
        q = select(CustomerEnvironment.id).where(
            func.lower(CustomerEnvironment.hosting_name) == name.lower()
        )
        if exclude_id is not None:
            q = q.where(CustomerEnvironment.id != exclude_id)
        row = (await self._session.execute(q.limit(1))).scalar_one_or_none()
        return row is not None

    def _person(self, customer: Any | None) -> tuple[str | None, str | None]:
        if customer is None:
            return None, None
        return getattr(customer, "first_name", None), getattr(customer, "last_name", None)

    async def generate_unique_name(
        self,
        customer: Customer | None = None,
        *,
        domain: str | None = None,
        hostname: str | None = None,
        exclude_env_id: UUID | None = None,
        max_attempts: int = 800,
    ) -> str:
        """Return the next clean available hosting name. Never asks the customer."""
        first, last = self._person(customer)
        bases = candidate_bases(
            domain=domain,
            hostname=hostname,
            first_name=first,
            last_name=last,
        )
        attempts = 0
        for name in iter_name_candidates(bases):
            attempts += 1
            if attempts > max_attempts:
                break
            if await self._taken(name, exclude_id=exclude_env_id):
                continue
            return name
        raise AppException("Could not allocate a hosting name.", code="hosting_name_exhausted")

    async def allocate(
        self,
        *,
        domain: str | None = None,
        hostname: str | None = None,
        customer: Customer | None = None,
        first_name: str | None = None,
        last_name: str | None = None,
        exclude_env_id: UUID | None = None,
        max_attempts: int = 800,
    ) -> str:
        """Alias used by provisioning/scripts. Prefer generate_unique_name in new code."""
        if customer is None and (first_name or last_name):
            from types import SimpleNamespace

            customer = SimpleNamespace(first_name=first_name, last_name=last_name)  # type: ignore[assignment]
        return await self.generate_unique_name(
            customer,
            domain=domain,
            hostname=hostname,
            exclude_env_id=exclude_env_id,
            max_attempts=max_attempts,
        )

    async def assign_if_missing(
        self,
        env: CustomerEnvironment,
        *,
        customer: Customer | None = None,
    ) -> str:
        """Idempotent: keep existing hosting_name forever once set. Retries on UNIQUE races."""
        existing = (getattr(env, "hosting_name", None) or "").strip().lower()
        if existing:
            return existing
        if customer is None:
            customer = await self._session.get(Customer, env.customer_id)

        first, last = self._person(customer)
        bases = candidate_bases(domain=env.domain, first_name=first, last_name=last)
        for name in iter_name_candidates(bases):
            if await self._taken(name, exclude_id=env.id):
                continue
            env.hosting_name = name
            try:
                async with self._session.begin_nested():
                    await self._session.flush()
                return name
            except IntegrityError:
                env.hosting_name = None
                continue
        raise AppException("Could not allocate a hosting name.", code="hosting_name_exhausted")

    def propose_sync(
        self,
        *,
        domain: str | None = None,
        hostname: str | None = None,
        first_name: str | None = None,
        last_name: str | None = None,
    ) -> str:
        """Offline proposal for dry-run scripts (no uniqueness against DB)."""
        bases = candidate_bases(
            domain=domain, hostname=hostname, first_name=first_name, last_name=last_name
        )
        for name in iter_name_candidates(bases):
            return name
        return "sitehost"
