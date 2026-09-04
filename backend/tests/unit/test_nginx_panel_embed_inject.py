"""Nginx panel embed injection — HTTPS-only, preserve app-proxy configs."""

from __future__ import annotations

from types import SimpleNamespace

from app.services.hosting.nginx_provisioner import DomainNginxProvisioner, MANAGED_MARKER


def _settings() -> SimpleNamespace:
    return SimpleNamespace(
        customer_portal_url="https://ifnotus.space",
        webmail_url="https://mail.ifnotus.space",
        nginx_sites_available="/tmp",
        nginx_sites_enabled="/tmp",
        frontend_dist_root="/var/www/ifnotus",
        local_api_upstream="http://127.0.0.1:8010",
    )


def test_inject_skips_http_redirect_only_server_block() -> None:
    conf = """
server {
    listen 80;
    server_name alice.ifnotus.space;
    location ^~ /.well-known/acme-challenge/ { root /var/www/letsencrypt; }
    location / {
        return 301 https://$host$request_uri;
    }
}

server {
    listen 443 ssl;
    server_name alice.ifnotus.space;
    ssl_certificate /etc/letsencrypt/live/alice/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/alice/privkey.pem;
    location / {
        try_files $uri $uri/ /index.html;
    }
}
"""
    svc = DomainNginxProvisioner(_settings())  # type: ignore[arg-type]
    updated = svc.inject_webmail_into_config(conf)
    assert updated.count("location ^~ /hosting/") == 1
    assert "listen 80" in updated
    http_block = updated.split("server {", 2)[1]
    assert "location ^~ /hosting/" not in http_block


def test_inject_into_https_proxy_with_upstream() -> None:
    conf = """
upstream app_backend {
    server 127.0.0.1:3000;
}

server {
    listen 80;
    server_name examflow.ifnotus.space;
    location / { return 301 https://$host$request_uri; }
}

server {
    listen 443 ssl http2;
    server_name examflow.ifnotus.space;
    ssl_certificate /etc/letsencrypt/live/examflow/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/examflow/privkey.pem;
    location /static/ { alias /srv/static/; }
    location / {
        proxy_pass http://app_backend;
    }
}
"""
    svc = DomainNginxProvisioner(_settings())  # type: ignore[arg-type]
    updated = svc.inject_webmail_into_config(conf)
    assert "upstream app_backend" in updated
    assert updated.count("location ^~ /hosting/") == 1
    assert "proxy_pass http://app_backend" in updated
    assert "location ^~ /api/" in updated


def test_is_custom_app_proxy_config() -> None:
    custom = "upstream foo { server 127.0.0.1:3000; }\nserver { proxy_pass http://foo; }"
    managed = f"{MANAGED_MARKER}\nserver {{ proxy_pass http://127.0.0.1:3000; }}"
    assert DomainNginxProvisioner.is_custom_app_proxy_config(custom)
    assert not DomainNginxProvisioner.is_custom_app_proxy_config(managed)


def test_location_block_includes_diagnostic_pages(tmp_path, monkeypatch) -> None:
    svc = DomainNginxProvisioner(_settings())  # type: ignore[arg-type]
    monkeypatch.setattr(svc, "ensure_diagnostic_error_pages", lambda: tmp_path)
    monkeypatch.setattr(svc, "_webmail_locations", lambda **_kw: [])
    monkeypatch.setattr(svc, "_resolve_php_fpm_socket", lambda *_a, **_k: None)

    static_lines = "\n".join(
        svc._location_block(
            hostname="example.test",
            root=str(tmp_path / "www"),
            proxy_port=None,
            redirect_url=None,
            path_redirects=[],
        )
    )
    assert "__ifnotus_site_empty.html" in static_lines
    assert "error_page 403" in static_lines

    proxy_lines = "\n".join(
        svc._location_block(
            hostname="example.test",
            root=str(tmp_path / "www"),
            proxy_port=31234,
            redirect_url=None,
            path_redirects=[],
        )
    )
    assert "__ifnotus_app_down.html" in proxy_lines
    assert "error_page 502 503 504" in proxy_lines
    assert "proxy_pass http://127.0.0.1:31234" in proxy_lines
