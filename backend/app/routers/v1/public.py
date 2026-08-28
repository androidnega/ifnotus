"""Unauthenticated public endpoints (DNS-aware redirects, SSO token consumption, etc.)."""

from __future__ import annotations

from fastapi import APIRouter, Query, Request
from fastapi.responses import RedirectResponse

from app.api.deps import DbSession, SettingsDep
from app.schemas.platform import HostingSsoConsumeRequest, HostingSsoConsumeResponse
from app.services.platform.hosting_ready_page import panel_entry_url
from app.services.platform.host_routing import sanitize_panel_hostname
from app.services.platform.sso import HostingSsoService

router = APIRouter()


@router.get("/panel-redirect", response_class=RedirectResponse)
async def panel_redirect(
    request: Request,
    settings: SettingsDep,
    host: str | None = Query(default=None, max_length=253),
    tab: str | None = Query(default=None, max_length=64),
) -> RedirectResponse:
    """302 to the canonical Customer Hosting Panel (https://cpanel.<domain>)."""
    name = sanitize_panel_hostname(host)
    if not name:
        forwarded = request.headers.get("x-forwarded-host") or request.headers.get("host")
        name = sanitize_panel_hostname(forwarded)
    portal = settings.customer_portal_url or "https://ifnotus.space"
    if not name:
        return RedirectResponse(url=f"{portal.rstrip('/')}/account", status_code=302)
    url = panel_entry_url(name, portal, tab=tab)
    return RedirectResponse(url=url, status_code=302)


@router.post("/sso/consume", response_model=HostingSsoConsumeResponse)
async def consume_sso_token(
    body: HostingSsoConsumeRequest,
    request: Request,
    session: DbSession,
    settings: SettingsDep,
) -> HostingSsoConsumeResponse:
    """Consume a short-lived, single-use SSO token to log into the tenant control panel."""
    host = body.host or request.headers.get("x-forwarded-host") or request.headers.get("host")
    service = HostingSsoService(settings, session)
    result = await service.consume_handoff(body.token, requested_host=host)
    return HostingSsoConsumeResponse(
        access_token=result["access_token"],
        refresh_token=result["refresh_token"],
        token_type=result["token_type"],
        expires_in=result["expires_in"],
        environment_id=result["environment_id"],
        domain=result["domain"],
        username=result.get("username"),
    )
