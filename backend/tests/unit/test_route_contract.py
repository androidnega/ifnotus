"""Route / API contract regression (PHASE 0).

Preserves critical frontend paths and purchase-flow API endpoints so later
phases cannot casually break /login, /signup, /account, /panel, or MoMo APIs.
"""

from __future__ import annotations

from pathlib import Path

from app.core.config import Environment, Settings
from app.main import create_app

FRONTEND_ROUTER = (
    Path(__file__).resolve().parents[3] / "frontend" / "src" / "router" / "index.ts"
)

CRITICAL_FRONTEND_PATHS = (
    "/",
    "/plans",
    "/login",
    "/signup",
    "/account",
    "/panel",
)

CRITICAL_API_PATHS = {
    "/api/v1/health": {"get"},
    "/api/v1/catalog/plans": {"get"},
    "/api/v1/catalog/meta": {"get"},
    "/api/v1/customers/phone/request-otp": {"post"},
    "/api/v1/customers/phone/verify-otp": {"post"},
    "/api/v1/customers/me": {"get", "patch"},
    "/api/v1/customers/me/complete-profile": {"post"},
    "/api/v1/customers/orders": {"get", "post"},
    "/api/v1/customers/orders/{order_id}/momo": {"post"},
    "/api/v1/customers/environments": {"get"},
    "/api/v1/platform/orders/{order_id}/confirm-payment": {"post"},
    "/api/v1/auth/login": {"post"},
}


def test_frontend_preserves_critical_route_paths() -> None:
    text = FRONTEND_ROUTER.read_text(encoding="utf-8")
    for path in CRITICAL_FRONTEND_PATHS:
        assert f"path: '{path}'" in text or f'path: "{path}"' in text, path


def test_openapi_preserves_purchase_and_auth_endpoints(test_settings: Settings) -> None:
    app = create_app(test_settings)
    schema = app.openapi()
    paths = schema["paths"]
    for path, methods in CRITICAL_API_PATHS.items():
        assert path in paths, f"missing API path {path}"
        present = {m.lower() for m in paths[path] if m in {"get", "post", "put", "patch", "delete"}}
        assert methods.issubset(present), f"{path} expected {methods}, got {present}"


def test_create_app_accepts_testing_environment(test_settings: Settings) -> None:
    assert test_settings.environment == Environment.TESTING
    app = create_app(test_settings)
    assert app.title
    assert app.state.container is not None
