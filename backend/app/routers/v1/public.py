"""Unauthenticated public endpoints (DNS-aware redirects, etc.)."""

from __future__ import annotations

from fastapi import APIRouter, Query, Request
from fastapi.responses import RedirectResponse

from app.api.deps import SettingsDep
from app.services.platform.hosting_ready_page import panel_entry_url
from app.services.platform.host_routing import sanitize_panel_hostname

router = APIRouter()


@router.get("/panel-redirect", response_class=RedirectResponse)
async def panel_redirect(
    request: Request,
    settings: SettingsDep,
    host: str | None = Query(default=None, max_length=253),
    tab: str | None = Query(default=None, max_length=64),
) -> RedirectResponse:
    """302 to the correct Hosting Panel URL for this site (checked at request time).

    Used by nginx ``/cpanel`` on customer domains so routing stays correct when DNS
    switches between apex-only A records and full cpanel.* delegation.
    """
    name = sanitize_panel_hostname(host)
    if not name:
        forwarded = request.headers.get("x-forwarded-host") or request.headers.get("host")
        name = sanitize_panel_hostname(forwarded)
    portal = settings.customer_portal_url or "https://ifnotus.space"
    if not name:
        return RedirectResponse(url=f"{portal.rstrip('/')}/account", status_code=302)
    url = panel_entry_url(name, portal, tab=tab)
    return RedirectResponse(url=url, status_code=302)
