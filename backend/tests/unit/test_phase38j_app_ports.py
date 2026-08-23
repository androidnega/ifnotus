"""PHASE 38J — node-global application port allocation."""

from __future__ import annotations

from uuid import UUID

import pytest

from app.core.exceptions import AppException
from app.services.platform.application_runtime import (
    APP_PORT_MAX,
    APP_PORT_MIN,
    pick_free_port,
    port_bind_available,
    preferred_port_base,
    supervisor_environment_line,
)


def test_two_envs_cannot_receive_same_port() -> None:
    used: set[int] = set()
    listening: set[int] = set()

    def available(p: int) -> bool:
        return True

    e1 = UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
    e2 = UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")
    p1 = pick_free_port(
        used=used, listening=listening, preferred_base=preferred_port_base(e1), port_available=available
    )
    used.add(p1)
    p2 = pick_free_port(
        used=used, listening=listening, preferred_base=preferred_port_base(e2), port_available=available
    )
    assert p1 != p2
    assert APP_PORT_MIN <= p1 <= APP_PORT_MAX
    assert APP_PORT_MIN <= p2 <= APP_PORT_MAX


def test_listening_port_is_not_recycled() -> None:
    def available(p: int) -> bool:
        return p != 31000

    port = pick_free_port(
        used=set(),
        listening={31000},
        preferred_base=31000,
        port_available=available,
    )
    assert port != 31000


def test_stale_listener_blocks_assignment_via_bind_check() -> None:
    # Simulate OS still holding a released registry port.
    blocked = {31111}

    def available(p: int) -> bool:
        return p not in blocked

    port = pick_free_port(
        used=set(),  # registry released
        listening=set(),
        preferred_base=31111,
        port_available=available,
    )
    assert port != 31111


def test_port_exhausted() -> None:
    used = set(range(APP_PORT_MIN, APP_PORT_MAX + 1))

    with pytest.raises(AppException) as exc:
        pick_free_port(
            used=used,
            listening=set(),
            preferred_base=APP_PORT_MIN,
            port_available=lambda _p: True,
        )
    assert exc.value.code == "port_exhausted"


def test_supervisor_environment_injects_port() -> None:
    line = supervisor_environment_line({"NODE_ENV": "production", "PORT": "31234"})
    assert line.startswith("environment=")
    assert 'PORT="31234"' in line
    assert 'NODE_ENV="production"' in line


def test_port_bind_available_roundtrip() -> None:
    # Bind an ephemeral port then ensure that port reports unavailable while held.
    import socket

    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(("127.0.0.1", 0))
    held = sock.getsockname()[1]
    try:
        assert port_bind_available(held) is False
    finally:
        sock.close()
    assert port_bind_available(held) is True


def test_node_stub_prefers_env_port() -> None:
    from app.models.platform import ApplicationInstance
    from app.services.platform.application_runtime import ApplicationRuntimeService
    from pathlib import Path
    import tempfile

    app = ApplicationInstance(
        environment_id=UUID("11111111-1111-1111-1111-111111111111"),
        runtime="nodejs",
        framework="express",
        status="pending",
        allocated_port=32123,
        config_json={"name": "demo"},
    )
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        svc = object.__new__(ApplicationRuntimeService)
        svc._write_framework_stub(app, root)
        text = (root / "server.js").read_text(encoding="utf-8")
        assert "process.env.PORT" in text
        assert "32123" in text
        assert "127.0.0.1" in text
