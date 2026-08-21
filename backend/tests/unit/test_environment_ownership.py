"""Multi-environment ownership regression (PHASE 0).

A customer may own many environments; environment APIs must resolve by
(customer_id, environment_id) together — never by environment id alone.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from app.core.exceptions import NotFoundError
from app.services.platform.lifecycle import EnvironmentLifecycleService


@pytest.mark.asyncio
async def test_get_owned_returns_matching_environment(test_settings) -> None:
    customer_id = uuid4()
    env_id = uuid4()
    env = SimpleNamespace(id=env_id, customer_id=customer_id, status="active")
    session = MagicMock()
    session.execute = AsyncMock(
        return_value=SimpleNamespace(scalar_one_or_none=lambda: env)
    )
    svc = EnvironmentLifecycleService(test_settings, session)

    got = await svc.get_owned(customer_id, env_id)
    assert got is env
    assert got.customer_id == customer_id


@pytest.mark.asyncio
async def test_get_owned_raises_when_environment_belongs_to_other_customer(
    test_settings,
) -> None:
    session = MagicMock()
    session.execute = AsyncMock(
        return_value=SimpleNamespace(scalar_one_or_none=lambda: None)
    )
    svc = EnvironmentLifecycleService(test_settings, session)

    with pytest.raises(NotFoundError, match="Environment not found"):
        await svc.get_owned(uuid4(), uuid4())


@pytest.mark.asyncio
async def test_same_customer_can_own_multiple_environment_ids(test_settings) -> None:
    """Ownership is per (customer_id, environment_id); multi-env accounts are valid."""
    customer_id = uuid4()
    envs = [
        SimpleNamespace(id=uuid4(), customer_id=customer_id),
        SimpleNamespace(id=uuid4(), customer_id=customer_id),
    ]
    session = MagicMock()
    svc = EnvironmentLifecycleService(test_settings, session)

    for env in envs:
        session.execute = AsyncMock(
            return_value=SimpleNamespace(scalar_one_or_none=lambda e=env: e)
        )
        got = await svc.get_owned(customer_id, env.id)
        assert got.id == env.id
        assert got.customer_id == customer_id
