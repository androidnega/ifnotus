"""Phase K — domain architecture and /cpanel routing tests."""

from __future__ import annotations

from app.services.platform.host_routing import sanitize_panel_hostname
from app.services.platform.panel_access import panel_sso_url, site_cpanel_url


def test_sanitize_rejects_open_redirect_carriers() -> None:
    assert sanitize_panel_hostname("evil.com/path") is None
    assert sanitize_panel_hostname("https://evil.com") is None
    assert sanitize_panel_hostname("user@evil.com") is None
    assert sanitize_panel_hostname("evil.com?x=1") is None
    assert sanitize_panel_hostname("localhost") is None


def test_sanitize_accepts_valid_hosts() -> None:
    assert sanitize_panel_hostname("studio.online") == "studio.online"
    assert sanitize_panel_hostname("www.studio.online") == "studio.online"
    assert sanitize_panel_hostname("cpanel.studio.online") == "cpanel.studio.online"


def test_panel_sso_fixed_portal_origin() -> None:
    url = panel_sso_url("studio.online")
    assert url.startswith("https://ifnotus.space/go/hosting?")
    assert "host=studio.online" in url
    assert "evil.com" not in url.split("?", 1)[0]


def test_panel_sso_rejects_invalid_host() -> None:
    assert panel_sso_url("not-a-host").endswith("/account")
    assert panel_sso_url("evil.com/x").endswith("/account")


def test_site_cpanel_path_not_subdomain() -> None:
    assert site_cpanel_url("example.com") == "https://example.com/cpanel"
    assert site_cpanel_url("www.example.com") == "https://example.com/cpanel"
    assert "cpanel.example.com" not in (site_cpanel_url("example.com") or "")
