"""Phase H — /cpanel shortcut targets Hosting Panel SSO."""

from __future__ import annotations

from types import SimpleNamespace

from app.services.hosting.nginx_provisioner import DomainNginxProvisioner
from app.services.platform.hosting_ready_page import manage_hosting_url
from app.services.platform.panel_access import (
    control_panel_url,
    panel_handoff_url,
    panel_sso_url,
    site_cpanel_url,
)


def test_cpanel_location_redirects_subdomain_to_same_host_hosting() -> None:
    settings = SimpleNamespace(
        customer_portal_url="https://ifnotus.space",
        webmail_url="https://mail.ifnotus.space",
        nginx_sites_available="/tmp",
        nginx_sites_enabled="/tmp",
    )
    lines = DomainNginxProvisioner(settings)._webmail_locations(hostname="alice.ifnotus.space")  # type: ignore[arg-type]
    joined = "\n".join(lines)
    assert "location = /cpanel" in joined
    assert "https://alice.ifnotus.space/hosting/" in joined
    assert "go/hosting?host=$host" not in joined
    assert "location ^~ /hosting/" in joined
    assert "location ^~ /assets/" in joined
    assert "login?redirect=%2Fgo%2Fhosting%3Fhost%3Dalice.ifnotus.space" in joined


def test_cpanel_location_custom_domain_uses_fpanel() -> None:
    settings = SimpleNamespace(
        customer_portal_url="https://ifnotus.space",
        webmail_url="https://mail.ifnotus.space",
        nginx_sites_available="/tmp",
        nginx_sites_enabled="/tmp",
    )
    lines = DomainNginxProvisioner(settings)._webmail_locations(hostname="studio.online")  # type: ignore[arg-type]
    joined = "\n".join(lines)
    assert "https://fpanel.studio.online/" in joined
    assert "go/hosting?host=$host" not in joined
    assert "location ^~ /hosting/" not in joined


def test_control_panel_url_all_tenants() -> None:
    assert control_panel_url("alice.ifnotus.space") == "https://alice.ifnotus.space/hosting/"
    assert control_panel_url("studio.online") == "https://fpanel.studio.online/"
    assert site_cpanel_url("yalleydadzie.online") == "https://fpanel.yalleydadzie.online/"


def test_manage_hosting_deep_link() -> None:
    url = manage_hosting_url("alice.ifnotus.space", tab="files")
    assert url == "https://alice.ifnotus.space/hosting/?tab=files"


def test_manage_hosting_custom_domain_uses_fpanel() -> None:
    assert manage_hosting_url("adastrachambers.com") == "https://fpanel.adastrachambers.com/"
    assert manage_hosting_url("studio.online", tab="files") == "https://fpanel.studio.online/?tab=files"


def test_panel_sso_url_for_nginx_redirect() -> None:
    assert panel_sso_url("alice.ifnotus.space") == "https://alice.ifnotus.space/hosting/"
    assert panel_sso_url("studio.online", tab="files") == "https://fpanel.studio.online/files"


def test_panel_handoff_url_subdomain_vs_custom() -> None:
    sub = panel_handoff_url("media1.ifnotus.space", "token123")
    assert sub is not None
    assert sub.startswith("https://media1.ifnotus.space/hosting/sso?token=")
    custom = panel_handoff_url("yalleydadzie.online", "token456", tab="files")
    assert custom is not None
    assert custom.startswith("https://fpanel.yalleydadzie.online/sso?token=")
    assert "tab=files" in custom
