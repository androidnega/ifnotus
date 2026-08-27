"""Idempotency helpers for provider_meta on CustomerEnvironment."""

from __future__ import annotations

from typing import Any
from uuid import UUID


def provision_idempotency_key(*, subscription_id: UUID, domain: str, provider: str) -> str:
    """Deterministic key so retries do not create duplicate provider resources."""
    host = (domain or "").strip().lower()
    return f"prov:{provider}:{subscription_id}:{host}"


def get_meta(env: Any) -> dict[str, Any]:
    meta = getattr(env, "provider_meta", None)
    if isinstance(meta, dict):
        return dict(meta)
    return {}


def set_meta(env: Any, **updates: Any) -> dict[str, Any]:
    meta = get_meta(env)
    meta.update({k: v for k, v in updates.items() if v is not None})
    env.provider_meta = meta
    return meta


def already_provisioned_on_provider(env: Any, *, idempotency_key: str) -> bool:
    meta = get_meta(env)
    return bool(meta.get("idempotency_key") == idempotency_key and meta.get("provider_account_created"))
