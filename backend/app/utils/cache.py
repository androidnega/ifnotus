"""Redis cache utilities."""

import json
from typing import Any

from redis.asyncio import Redis


def cache_key(namespace: str, *parts: str) -> str:
    """Build a namespaced cache key."""
    return f"ifnotus:cache:{namespace}:{':'.join(parts)}"


async def get_cached(redis: Redis, key: str) -> Any | None:
    """Retrieve and deserialize a cached value."""
    raw = await redis.get(key)
    if raw is None:
        return None
    return json.loads(raw)


async def set_cached(redis: Redis, key: str, value: Any, ttl: int = 300) -> None:
    """Serialize and store a value in cache."""
    await redis.set(key, json.dumps(value, default=str), ex=ttl)
