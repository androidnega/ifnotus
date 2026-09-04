"""Human-readable customer folder names under customer_environments_root.

Layout: ``/srv/apps/ifnotus-customers/<storage_slug>/<hostname>/public_html``

``storage_slug`` is 10–15 lowercase alphanumeric characters derived from the
account identity (email local part, name, hosting_name). UUID remains the DB id.
"""

from __future__ import annotations

import re
import unicodedata
from pathlib import Path
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.exceptions import AppException
from app.models.platform import Customer, CustomerEnvironment
from app.models.user import User
from app.services.platform.reserved_subdomains import is_reserved_label

MIN_STORAGE_SLUG_LEN = 10
MAX_STORAGE_SLUG_LEN = 15


def _ascii_fold(raw: str) -> str:
    text = unicodedata.normalize("NFKD", raw or "")
    return "".join(ch for ch in text if not unicodedata.combining(ch))


def _letters_only(raw: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", _ascii_fold(raw).strip().lower())


def _starts_with_letter(text: str) -> str:
    text = text.lstrip("0123456789-_")
    return text or "customer"


def email_local_part(email: str | None) -> str:
    local = (email or "").split("@", 1)[0].lower()
    # Drop random suffix from generated usernames (local_hex).
    if "_" in local:
        head, tail = local.rsplit("_", 1)
        if re.fullmatch(r"[0-9a-f]{6}", tail or ""):
            local = head
    return _letters_only(local)


def slug_candidates(
    *,
    email: str | None = None,
    username: str | None = None,
    first_name: str | None = None,
    last_name: str | None = None,
    hosting_names: list[str] | None = None,
) -> list[str]:
    out: list[str] = []
    for source in (email_local_part(email), email_local_part(username), _letters_only(username or "")):
        if source:
            out.append(source)
    for name in hosting_names or []:
        n = _letters_only(name)
        if n:
            out.append(n)
    last = _letters_only(last_name or "")
    first = _letters_only(first_name or "")
    if last and first:
        out.append(f"{first}{last}")
    if last:
        out.append(last)
    if first:
        out.append(first)
    if not out:
        out.append("customer")

    seen: set[str] = set()
    ordered: list[str] = []
    for item in out:
        base = _starts_with_letter(item)
        if base not in seen:
            seen.add(base)
            ordered.append(base)
    return ordered


def fit_slug_length(base: str, *, min_len: int = MIN_STORAGE_SLUG_LEN, max_len: int = MAX_STORAGE_SLUG_LEN) -> str:
    text = _starts_with_letter(base)
    if len(text) > max_len:
        return text[:max_len]
    if len(text) >= min_len:
        return text
    # Pad with a neutral suffix to reach minimum length.
    pad = "host"
    while len(text) < min_len:
        text = (text + pad)[:max_len]
    return text[:max_len]


def slug_with_suffix(base: str, index: int) -> str:
    suffix = str(index) if index > 1 else ""
    max_base = MAX_STORAGE_SLUG_LEN - len(suffix)
    trimmed = _starts_with_letter(base)[:max_base]
    candidate = f"{trimmed}{suffix}"
    return fit_slug_length(candidate)


def is_storage_slug_reserved(name: str | None) -> bool:
    slug = (name or "").strip().lower()
    if not slug or len(slug) < MIN_STORAGE_SLUG_LEN or len(slug) > MAX_STORAGE_SLUG_LEN:
        return True
    if not slug[0].isalpha():
        return True
    if not slug.isalnum():
        return True
    return is_reserved_label(slug)


def customer_prefix_path(
    customers_root: str | Path,
    *,
    customer_id: UUID | str,
    storage_slug: str | None = None,
) -> Path:
    root = Path(customers_root).resolve()
    slug = (storage_slug or "").strip().lower()
    if slug:
        return (root / slug).resolve()
    return (root / str(customer_id)).resolve()


def customer_prefix_from_document_root(
    customers_root: str | Path,
    document_root: str | None,
) -> Path | None:
    root = Path(customers_root).resolve()
    doc = Path(document_root or "")
    if not str(doc):
        return None
    try:
        resolved = doc.resolve()
        rel = resolved.relative_to(root)
    except (ValueError, OSError):
        return None
    if not rel.parts:
        return None
    return (root / rel.parts[0]).resolve()


def resolve_customer_prefix(
    settings: Settings,
    *,
    customer_id: UUID | str,
    storage_slug: str | None = None,
    document_root: str | None = None,
) -> Path:
    root = Path(settings.customer_environments_root).resolve()
    from_doc = customer_prefix_from_document_root(root, document_root)
    if from_doc is not None:
        return from_doc
    return customer_prefix_path(root, customer_id=customer_id, storage_slug=storage_slug)


def environment_public_root(
    settings: Settings,
    customer: Customer,
    hostname: str,
) -> str:
    prefix = customer_prefix_path(
        settings.customer_environments_root,
        customer_id=customer.id,
        storage_slug=getattr(customer, "storage_slug", None),
    )
    return str(prefix / hostname / "public_html")


def purge_customer_storage(
    settings: Settings,
    customer: Customer,
    *,
    envs: list[CustomerEnvironment] | None = None,
) -> dict[str, object]:
    """Remove on-disk customer folders (storage slug + legacy UUID paths)."""
    import shutil

    root = Path(settings.customer_environments_root).resolve()
    removed: list[str] = []
    errors: list[str] = []

    candidates: list[Path] = []
    slug = (getattr(customer, "storage_slug", None) or "").strip()
    if slug:
        candidates.append(customer_prefix_path(root, customer_id=customer.id, storage_slug=slug))
    candidates.append(customer_prefix_path(root, customer_id=customer.id))
    for env in envs or []:
        from_doc = customer_prefix_from_document_root(root, env.document_root)
        if from_doc is not None:
            candidates.append(from_doc)

    seen: set[Path] = set()
    for path in candidates:
        try:
            resolved = path.resolve()
        except OSError:
            continue
        if resolved in seen or resolved == root:
            continue
        seen.add(resolved)
        if not resolved.is_dir():
            continue
        try:
            resolved.relative_to(root)
        except ValueError:
            continue
        try:
            shutil.rmtree(resolved)
            removed.append(str(resolved))
        except OSError as exc:
            errors.append(f"{resolved}: {exc}")

    return {"removed_paths": removed, "errors": errors}


class CustomerStorageService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def _slug_taken(self, slug: str, *, exclude_customer_id: UUID | None = None) -> bool:
        q = select(Customer.id).where(func.lower(Customer.storage_slug) == slug.lower())
        if exclude_customer_id:
            q = q.where(Customer.id != exclude_customer_id)
        row = (await self._session.execute(q)).scalar_one_or_none()
        if row is not None:
            return True
        # Also refuse if a legacy UUID folder name equals slug (unlikely).
        return is_storage_slug_reserved(slug)

    async def generate_unique_slug(
        self,
        customer: Customer | None,
        *,
        user: User | None = None,
        hosting_names: list[str] | None = None,
        exclude_customer_id: UUID | None = None,
    ) -> str:
        names: list[str]
        if hosting_names is not None:
            names = list(hosting_names)
        elif customer:
            names = []
            try:
                from sqlalchemy import text

                rows = (
                    await self._session.execute(
                        text(
                            "SELECT hosting_name FROM customer_environments "
                            "WHERE customer_id = :cid AND hosting_name IS NOT NULL"
                        ),
                        {"cid": str(customer.id)},
                    )
                ).scalars().all()
                names = [n for n in rows if n]
            except Exception:
                names = []
        else:
            names = []

        email = getattr(customer, "email", None) if customer else None
        for index, base in enumerate(slug_candidates(
            email=email,
            username=getattr(user, "username", None) if user else None,
            first_name=getattr(customer, "first_name", None) if customer else None,
            last_name=getattr(customer, "last_name", None) if customer else None,
            hosting_names=names,
        )):
            for attempt in range(1, 100):
                candidate = slug_with_suffix(fit_slug_length(base), attempt if index == 0 else attempt + index)
                if is_storage_slug_reserved(candidate):
                    continue
                if not await self._slug_taken(candidate, exclude_customer_id=exclude_customer_id):
                    return candidate
        raise AppException("Could not allocate a customer storage slug.", code="storage_slug_exhausted")

    async def assign_if_missing(
        self,
        customer: Customer,
        *,
        user: User | None = None,
        hosting_names: list[str] | None = None,
    ) -> str:
        existing = (getattr(customer, "storage_slug", None) or "").strip().lower()
        if existing:
            return existing
        slug = await self.generate_unique_slug(
            customer,
            user=user,
            hosting_names=hosting_names,
            exclude_customer_id=customer.id,
        )
        customer.storage_slug = slug
        await self._session.flush()
        return slug
