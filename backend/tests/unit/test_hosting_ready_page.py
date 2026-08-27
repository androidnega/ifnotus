"""Phase F — hosting-ready parking page + DNS resolution helpers."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

from app.services.platform.hosting_ready_page import (
    hosting_ready_html,
    is_internal_addon_hostname,
    is_parking_page,
    manage_hosting_url,
    panel_entry_url,
    panel_path,
    ready_page_label,
    write_hosting_ready_page,
)
from app.services.platform.stacks import detect_stack_from_filesystem


def test_hosting_ready_html_contains_product_copy() -> None:
    html = hosting_ready_html(hostname="manuel.ifnotus.space")
    assert "Your hosting is ready" in html
    assert "manuel.ifnotus.space" in html
    assert "Open hosting panel" in html
    assert 'href="/cpanel"' in html
    assert "Install WordPress" not in html
    assert "Upload Website" not in html
    assert "Create Application" not in html


def test_hosting_ready_custom_domain_links_cpanel_host() -> None:
    html = hosting_ready_html(hostname="adastrachambers.com")
    assert 'href="/cpanel"' in html
    assert "Open hosting panel" in html


def test_hosting_ready_a_record_only_uses_relative_cpanel(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.services.platform.hosting_ready_page._host_resolves_publicly",
        lambda host: host == "yalleydadzie.online",
    )
    html = hosting_ready_html(hostname="yalleydadzie.online")
    assert 'href="/cpanel"' in html
    assert "cpanel.yalleydadzie.online" not in html


def test_panel_path() -> None:
    assert panel_path() == "/cpanel"
    assert panel_path(tab="files") == "/cpanel?tab=files"


def test_hosting_ready_hides_internal_addon_hostname() -> None:
    html = hosting_ready_html(hostname="env-70ff10fc.customers.ifnotus.space")
    assert "env-70ff10fc" not in html
    assert "customers.ifnotus.space" not in html
    assert "DNS already points here" not in html
    assert "https://ifnotus.space/account" in html


def test_hosting_ready_shows_purchased_domain_over_internal_host() -> None:
    html = hosting_ready_html(
        hostname="env-70ff10fc.customers.ifnotus.space",
        display_hostname="yalleydadzie.online",
    )
    assert "yalleydadzie.online" in html
    assert "env-70ff10fc" not in html


def test_panel_entry_url_skips_internal_host(monkeypatch) -> None:
    assert panel_entry_url("env-abc.customers.ifnotus.space") == "https://ifnotus.space/account"
    assert "go/hosting?host=studio.online" in panel_entry_url("studio.online")


def test_write_hosting_ready_page_skips_customer_content(tmp_path: Path) -> None:
    root = tmp_path / "public"
    root.mkdir()
    (root / "index.html").write_text("<html><body><h1>My Site</h1></body></html>", encoding="utf-8")
    write_hosting_ready_page(root, hostname="x.ifnotus.space", force=False)
    assert "My Site" in (root / "index.html").read_text(encoding="utf-8")


def test_write_hosting_ready_upgrades_legacy_parking(tmp_path: Path) -> None:
    root = tmp_path / "public"
    root.mkdir()
    (root / "index.html").write_text("<h1>It works</h1><p>Provisioned by IFNOTUS.</p>", encoding="utf-8")
    write_hosting_ready_page(root, hostname="x.ifnotus.space", force=False)
    text = (root / "index.html").read_text(encoding="utf-8")
    assert "Your hosting is ready" in text
    assert detect_stack_from_filesystem(root) is None


def test_is_parking_markers() -> None:
    assert is_parking_page("<h1>Your hosting is ready</h1>")
    assert is_parking_page("<h1>It works</h1>")
    assert not is_parking_page("<h1>Welcome to my blog</h1>")


def test_manage_hosting_url_tabs() -> None:
    assert manage_hosting_url("a.ifnotus.space", tab="files") == "https://a.ifnotus.space/cpanel?tab=files"


def test_ensure_a_included_reports_unresolved(monkeypatch) -> None:
    import asyncio

    from app.services.platform.dns import EnvironmentDnsService

    monkeypatch.setattr(
        EnvironmentDnsService,
        "verify_hostname_resolves",
        staticmethod(lambda _h: {"ok": False, "addresses": [], "error": "nodename nor servname"}),
    )
    svc = EnvironmentDnsService(MagicMock(), MagicMock())
    monkeypatch.setattr(svc, "is_included_hostname", lambda _n: True)
    env = SimpleNamespace(domain="missing.ifnotus.space")

    result = asyncio.run(svc.ensure_a(env))
    assert result["ok"] is False
    assert "does not resolve" in result["message"]
