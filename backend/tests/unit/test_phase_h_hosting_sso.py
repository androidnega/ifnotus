"""Phase H — /cpanel shortcut targets Hosting Panel SSO."""

from __future__ import annotations

from types import SimpleNamespace

from app.services.hosting.nginx_provisioner import DomainNginxProvisioner
from app.services.platform.hosting_ready_page import manage_hosting_url
from app.services.platform.panel_access import control_panel_url, panel_sso_url, site_cpanel_url


def test_cpanel_location_proxies_panel_redirect() -> None:
    settings = SimpleNamespace(
        customer_portal_url="https://ifnotus.space",
        webmail_url="https://mail.ifnotus.space",
        nginx_sites_available="/tmp",
        nginx_sites_enabled="/tmp",
    )
    lines = DomainNginxProvisioner(settings)._webmail_locations(hostname="alice.ifnotus.space")  # type: ignore[arg-type]
    joined = "\n".join(lines)
    assert "location = /cpanel" in joined
    assert "go/hosting?host=$host" in joined
    assert "return 302 https://ifnotus.space/account" not in joined


def test_cpanel_location_same_for_custom_domain() -> None:
    settings = SimpleNamespace(
        customer_portal_url="https://ifnotus.space",
        webmail_url="https://mail.ifnotus.space",
        nginx_sites_available="/tmp",
        nginx_sites_enabled="/tmp",
    )
    lines = DomainNginxProvisioner(settings)._webmail_locations(hostname="studio.online")  # type: ignore[arg-type]
    joined = "\n".join(lines)
    assert "go/hosting?host=$host" in joined
    assert "https://cpanel.studio.online/" not in joined
    assert "panel-redirect" not in joined


def test_control_panel_url_all_tenants_use_path() -> None:
    assert control_panel_url("alice.ifnotus.space") == "https://alice.ifnotus.space/cpanel"
    assert control_panel_url("studio.online") == "https://studio.online/cpanel"
    assert site_cpanel_url("yalleydadzie.online") == "https://yalleydadzie.online/cpanel"


def test_manage_hosting_deep_link() -> None:
    url = manage_hosting_url("alice.ifnotus.space", tab="files")
    assert url == "https://alice.ifnotus.space/cpanel?tab=files"


def test_manage_hosting_custom_domain_uses_path() -> None:
    assert manage_hosting_url("adastrachambers.com") == "https://adastrachambers.com/cpanel"
    assert manage_hosting_url("studio.online", tab="files") == "https://studio.online/cpanel?tab=files"


def test_panel_sso_url_for_nginx_redirect() -> None:
    assert "go/hosting?host=alice.ifnotus.space" in panel_sso_url("alice.ifnotus.space")
    assert "tab=files" in panel_sso_url("studio.online", tab="files")
