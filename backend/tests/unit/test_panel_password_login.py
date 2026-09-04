"""Panel password login identity helpers."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from app.services.platform.panel_passwords import PanelPasswordService


@pytest.mark.asyncio
async def test_panel_status_prefers_hosting_name_over_unix() -> None:
    env_id = uuid4()
    customer_id = uuid4()
    user_id = uuid4()
    env = SimpleNamespace(
        id=env_id,
        customer_id=customer_id,
        hosting_name="sarponghost",
        unix_username="ifn_a59a05e0",
        domain="sarpong.ifnotus.space",
        panel_password_hash="$2b$12$notrealbutset",
        status="active",
    )
    customer = SimpleNamespace(id=customer_id, user_id=user_id)
    user = SimpleNamespace(id=user_id, hashed_password="$2b$12$acct")

    session = MagicMock()
    session.get = AsyncMock(side_effect=lambda model, pk: customer if pk == customer_id else user)

    svc = PanelPasswordService(session)
    svc.env_by_hosting_name = AsyncMock(return_value=env)  # type: ignore[method-assign]

    data = await svc.status(username="sarponghost")
    assert data["username"] == "sarponghost"
    assert data["password_set"] is True
    assert data["domain"] == "sarpong.ifnotus.space"


@pytest.mark.asyncio
async def test_env_by_site_host_strips_cpanel_prefix() -> None:
    env = SimpleNamespace(
        id=uuid4(),
        domain="yalleydadzie.online",
        status="active",
    )
    session = MagicMock()
    result = MagicMock()
    result.scalar_one_or_none.return_value = env
    session.execute = AsyncMock(return_value=result)

    svc = PanelPasswordService(session)
    got = await svc.env_by_site_host("cpanel.yalleydadzie.online")
    assert got is env
