"""PHASE 38C — billing suspend/restore/terminate delegates to lifecycle."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from app.services.platform.billing import SubscriptionBillingService


def _billing_service(test_settings) -> tuple[SubscriptionBillingService, MagicMock]:
    session = MagicMock()
    session.flush = AsyncMock()
    session.get = AsyncMock(return_value=SimpleNamespace(full_name="Test User"))
    svc = SubscriptionBillingService(test_settings, session)
    return svc, session


@pytest.mark.asyncio
async def test_suspend_environments_calls_lifecycle_without_per_env_notify(test_settings) -> None:
    customer_id = uuid4()
    sub_id = uuid4()
    env_active = SimpleNamespace(id=uuid4(), status="active")
    env_terminated = SimpleNamespace(id=uuid4(), status="terminated")
    sub = SimpleNamespace(id=sub_id, customer_id=customer_id)

    svc, session = _billing_service(test_settings)
    svc._envs = AsyncMock(return_value=[env_active, env_terminated])  # noqa: SLF001
    svc._notify.notify = AsyncMock()

    mock_lifecycle = MagicMock()
    mock_lifecycle.suspend = AsyncMock(return_value=env_active)

    with patch(
        "app.services.platform.billing.EnvironmentLifecycleService",
        return_value=mock_lifecycle,
    ):
        await svc._suspend_environments(sub, reason="grace ended")  # noqa: SLF001

    mock_lifecycle.suspend.assert_awaited_once_with(
        customer_id, env_active.id, notify_customer=False
    )
    svc._notify.notify.assert_awaited_once()
    session.get.assert_awaited()


@pytest.mark.asyncio
async def test_restore_environments_only_suspended_envs(test_settings) -> None:
    customer_id = uuid4()
    sub_id = uuid4()
    env_suspended = SimpleNamespace(id=uuid4(), status="suspended")
    env_active = SimpleNamespace(id=uuid4(), status="active")
    sub = SimpleNamespace(id=sub_id, customer_id=customer_id)

    svc, _session = _billing_service(test_settings)
    svc._envs = AsyncMock(return_value=[env_suspended, env_active])  # noqa: SLF001

    mock_lifecycle = MagicMock()
    mock_lifecycle.restore = AsyncMock(return_value=env_suspended)

    with patch(
        "app.services.platform.billing.EnvironmentLifecycleService",
        return_value=mock_lifecycle,
    ):
        await svc._restore_environments(sub)  # noqa: SLF001

    mock_lifecycle.restore.assert_awaited_once_with(
        customer_id, env_suspended.id, notify_customer=False
    )


@pytest.mark.asyncio
async def test_terminate_environments_skips_already_terminated(test_settings) -> None:
    customer_id = uuid4()
    sub_id = uuid4()
    env_live = SimpleNamespace(id=uuid4(), status="active")
    env_done = SimpleNamespace(id=uuid4(), status="terminated")
    sub = SimpleNamespace(id=sub_id, customer_id=customer_id)

    svc, _session = _billing_service(test_settings)
    svc._envs = AsyncMock(return_value=[env_live, env_done])  # noqa: SLF001
    svc._notify.notify = AsyncMock()

    mock_lifecycle = MagicMock()
    mock_lifecycle.terminate = AsyncMock(return_value=env_live)

    with patch(
        "app.services.platform.billing.EnvironmentLifecycleService",
        return_value=mock_lifecycle,
    ):
        await svc._terminate_environments(sub)  # noqa: SLF001

    mock_lifecycle.terminate.assert_awaited_once_with(
        customer_id, env_live.id, notify_customer=False
    )
    svc._notify.notify.assert_awaited_once()
