"""PHASE 38I — Staff studio write-gate authorization behavior."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from app.core.exceptions import AppException, AuthorizationError
from app.core.permissions import Permission
from app.routers.v1.databases import _gate_staff_studio_write
from app.schemas.databases import DbQueryRequest


def _user():
    return SimpleNamespace(id=uuid4(), username="ops", email="ops@example.com")


@pytest.mark.asyncio
async def test_select_allowed_without_write_permission() -> None:
    auth = MagicMock()
    auth.user_has_permission.return_value = False
    qclass = await _gate_staff_studio_write(
        user=_user(),
        auth_service=auth,
        body=DbQueryRequest(sql="SELECT 1"),
        engine="mysql",
        database="demo",
    )
    assert qclass == "read"
    auth.user_has_permission.assert_not_called()


@pytest.mark.asyncio
async def test_insert_denied_without_write_permission() -> None:
    auth = MagicMock()
    auth.user_has_permission.return_value = False
    with pytest.raises(AuthorizationError):
        await _gate_staff_studio_write(
            user=_user(),
            auth_service=auth,
            body=DbQueryRequest(sql="INSERT INTO t VALUES (1)"),
            engine="mysql",
            database="demo",
        )
    assert auth.user_has_permission.call_args[0][1] == Permission.DATABASES_WRITE.value


@pytest.mark.asyncio
async def test_insert_allowed_with_write_permission() -> None:
    auth = MagicMock()
    auth.user_has_permission.return_value = True
    auth.confirm_password = AsyncMock()
    qclass = await _gate_staff_studio_write(
        user=_user(),
        auth_service=auth,
        body=DbQueryRequest(sql="INSERT INTO t VALUES (1)"),
        engine="mysql",
        database="demo",
    )
    assert qclass == "write"
    auth.confirm_password.assert_not_awaited()


@pytest.mark.asyncio
async def test_drop_requires_password_confirm() -> None:
    auth = MagicMock()
    auth.user_has_permission.return_value = True
    auth.confirm_password = AsyncMock()
    with pytest.raises(AppException) as exc:
        await _gate_staff_studio_write(
            user=_user(),
            auth_service=auth,
            body=DbQueryRequest(sql="DROP TABLE t"),
            engine="mysql",
            database="demo",
        )
    assert exc.value.code == "db_confirm_required"


@pytest.mark.asyncio
async def test_drop_with_password_permitted() -> None:
    auth = MagicMock()
    auth.user_has_permission.return_value = True
    auth.confirm_password = AsyncMock()
    qclass = await _gate_staff_studio_write(
        user=_user(),
        auth_service=auth,
        body=DbQueryRequest(sql="DROP TABLE t", confirm_password="secret"),
        engine="mysql",
        database="demo",
    )
    assert qclass == "destructive"
    auth.confirm_password.assert_awaited()
