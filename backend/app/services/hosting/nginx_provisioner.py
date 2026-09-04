"""Provision nginx vhosts for managed domains (cPanel-style)."""

from __future__ import annotations

import re
from pathlib import Path

from app.core.config import Settings
from app.core.exceptions import AppException
from app.schemas.operations import OperationResult
from app.services.hosting.nginx_sites import NginxSiteManager
from app.services.monitoring.subprocess_util import resolve_binary, run_command

MANAGED_MARKER = "# managed-by-ifnotus: domain-vhost"
ACME_WEBROOT = "/var/www/letsencrypt"


class DomainNginxProvisioner:
    """Write / enable / remove nginx site configs for domains."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._available = Path(settings.nginx_sites_available)
        self._enabled = Path(settings.nginx_sites_enabled)
        self._sites = NginxSiteManager(settings)

    def site_name(self, hostname: str) -> str:
        # Match existing style on this host: full hostname as filename
        safe = re.sub(r"[^a-z0-9._-]+", "-", hostname.lower()).strip("-.")
        return safe or "site"

    def site_paths(self, hostname: str) -> tuple[Path, Path]:
        name = self.site_name(hostname)
        return self._available / name, self._enabled / name

    @staticmethod
    def resolve_web_root(path: str | Path) -> Path:
        """Pick the nginx document root without forcing a nested public_html.

        - Paths already named public/public_html/web/httpdocs are used as-is.
        - Folders that already contain index.php / index.html are served directly
          (Git/apps can live outside public_html).
        - Otherwise prefer an existing public_html (cPanel) or public child.
        """
        raw = Path(path).resolve()
        web_names = {"public", "public_html", "web", "httpdocs"}
        if raw.name in web_names:
            return raw
        if (raw / "index.php").is_file() or (raw / "index.html").is_file():
            return raw
        for name in ("public_html", "public", "web", "httpdocs"):
            candidate = raw / name
            if not candidate.is_dir() and not candidate.is_symlink():
                continue
            try:
                if any(candidate.iterdir()):
                    return candidate.resolve()
            except OSError:
                return candidate.resolve()
        return (raw / "public_html").resolve()

    def ensure_document_root(
        self,
        path: str,
        *,
        hostname: str | None = None,
        display_hostname: str | None = None,
    ) -> Path:
        from app.services.platform.hosting_ready_page import write_hosting_ready_page
        from app.services.platform.tenant import ensure_cpanel_directory_layout

        raw = Path(path).resolve()
        host = (hostname or "").strip() or raw.parent.name or raw.name
        portal = getattr(self._settings, "customer_portal_url", None) or "https://ifnotus.space"
        from app.services.platform.panel_access import is_service_hostname

        if is_service_hostname(host):
            return raw if raw.name in {"public", "public_html", "web", "httpdocs"} else raw / "public_html"
        web_root = self.resolve_web_root(raw)
        if web_root.name in {"public", "public_html", "web", "httpdocs"} and web_root.parent.exists():
            site_home = web_root.parent
        else:
            site_home = web_root if web_root == raw else raw
            if web_root == raw / "public_html" and not web_root.exists():
                web_root.mkdir(parents=True, exist_ok=True)
        ensure_cpanel_directory_layout(site_home, web_dir=web_root, hostname=host)
        write_hosting_ready_page(
            web_root,
            hostname=host,
            portal_base=portal,
            display_hostname=display_hostname,
            force=False,
        )
        return web_root

    def render_config(
        self,
        *,
        hostname: str,
        document_root: str | None,
        proxy_port: int | None,
        force_https: bool,
        redirect_url: str | None,
        aliases: list[str] | None = None,
        ssl_certificate: str | None = None,
        ssl_certificate_key: str | None = None,
        path_redirects: list[dict] | None = None,
    ) -> str:
        """Render nginx config for a site.

        Important: ``cpanel.<domain>`` and ``mail.<domain>`` are dedicated vhosts
        (not on the site ``server_name``). ``cpanel.*`` serves the Hosting Panel SPA
        on the customer's hostname; ``mail.*`` redirects to shared webmail.
        ACME challenges stay on the HTTP vhost webroot (never bounce to ifnotus.space).
        """
        site_names = [hostname] + [a for a in (aliases or []) if a and a != hostname]
        from app.services.platform.panel_access import control_panel_hostname, webmail_hostname
        from app.services.platform.student_hostname import is_student_hostname

        cpanel_host = None
        webmail_host = None
        mail_host = None
        is_platform_root = hostname in {
            "ifnotus.space",
            "www.ifnotus.space",
            "fpanel.ifnotus.space",
            "mail.ifnotus.space",
            "api.ifnotus.space",
        }

        if not is_platform_root:
            c_host = control_panel_hostname(hostname, settings=self._settings)
            if c_host and c_host != hostname and c_host != "fpanel.ifnotus.space":
                cpanel_host = c_host
            if "." in hostname and not hostname.startswith("www.") and not is_student_hostname(hostname, settings=self._settings):
                mail_host = f"mail.{hostname}"
                w_host = webmail_hostname(hostname, settings=self._settings)
                if w_host and w_host != hostname and w_host != "mail.ifnotus.space":
                    webmail_host = w_host

        # www for apex custom domains (not for platform / student subdomains)
        if (
            not is_platform_root
            and not is_student_hostname(hostname, settings=self._settings)
            and not hostname.endswith(".ifnotus.space")
            and not hostname.endswith(".serverlabsttu.space")
            and not hostname.startswith("www.")
            and f"www.{hostname}" not in site_names
        ):
            site_names.append(f"www.{hostname}")

        # Never put panel/mail aliases on the site server_name (HTTP or HTTPS).
        site_names = [
            n
            for n in dict.fromkeys(site_names)
            if n
            and n != cpanel_host
            and n != mail_host
            and n != webmail_host
            and (not str(n).startswith("fpanel.") or n == hostname)
            and (not str(n).startswith("cpanel.") or n == hostname)
            and (not str(n).startswith("webmail.") or n == hostname)
            and (not str(n).startswith("mail.") or n == hostname)
        ]
        if not site_names:
            site_names = [hostname]
        names_line = " ".join(site_names)
        root = str(self.resolve_web_root(document_root or f"/var/www/{hostname}"))
        cert = ssl_certificate
        key = ssl_certificate_key
        if not cert or not key:
            from app.services.platform.panel_access import find_letsencrypt_cert

            f_cert, f_key = find_letsencrypt_cert(hostname)
            if f_cert and f_key:
                cert = f_cert
                key = f_key
        try:
            Path(ACME_WEBROOT).mkdir(parents=True, exist_ok=True)
        except OSError:
            pass
        acme = [
            "    location ^~ /.well-known/acme-challenge/ {",
            f"        root {ACME_WEBROOT};",
            "        default_type text/plain;",
            "        allow all;",
            "    }",
        ]

        lines: list[str] = [
            MANAGED_MARKER,
            f"# domain={hostname}",
            "",
        ]

        # HTTP-only shortcut hosts (port 80 when no TLS).
        if not (cert and key):
            lines += self._http_alias_redirect_servers(
                cpanel_host=cpanel_host,
                webmail_host=webmail_host,
                mail_host=mail_host,
            )

        # HTTP server for the real site
        lines += [
            "server {",
            "    listen 80;",
            "    listen [::]:80;",
            f"    server_name {names_line};",
        ]
        if force_https and cert and key:
            lines += acme + [
                "    location / {",
                "        return 301 https://$host$request_uri;",
                "    }",
                "}",
                "",
            ]
        else:
            lines += acme
            lines += self._location_block(
                hostname=hostname,
                root=root,
                proxy_port=proxy_port,
                redirect_url=redirect_url,
                path_redirects=path_redirects or [],
            )
            lines += ["}", ""]

        # HTTPS server when cert present (site hosts only)
        if cert and key:
            lines += [
                "server {",
                "    listen 443 ssl;",
                "    listen [::]:443 ssl;",
                f"    server_name {names_line};",
                f"    ssl_certificate {cert};",
                f"    ssl_certificate_key {key};",
            ]
            if Path("/etc/letsencrypt/options-ssl-nginx.conf").exists():
                lines.append("    include /etc/letsencrypt/options-ssl-nginx.conf;")
            if Path("/etc/letsencrypt/ssl-dhparams.pem").exists():
                lines.append("    ssl_dhparam /etc/letsencrypt/ssl-dhparams.pem;")
            # _location_block already includes panel embeds + webmail above the catch-all proxy.
            lines += self._location_block(
                hostname=hostname,
                root=root,
                proxy_port=proxy_port,
                redirect_url=redirect_url,
                path_redirects=path_redirects or [],
            )
            lines += ["}", ""]
            # HTTPS cpanel.* — Hosting Panel SPA on the customer's own hostname (includes port 80).
            if cpanel_host:
                lines += self._cpanel_spa_server(
                    cpanel_host=cpanel_host,
                    cert=cert,
                    key=key,
                    listen_https=True,
                )
            # HTTPS webmail.* — Roundcube Webmail on the customer's own hostname (includes port 80).
            if webmail_host:
                lines += self._webmail_server(
                    webmail_host=webmail_host,
                    cert=cert,
                    key=key,
                    listen_https=True,
                )
            # HTTPS mail.* — Redirect to HTTPS webmail.<domain> (includes port 80).
            if mail_host and webmail_host:
                lines += self._mail_redirect_server(
                    mail_host=mail_host,
                    webmail_host=webmail_host,
                    cert=cert,
                    key=key,
                    listen_https=True,
                )

        return "\n".join(lines)

    def _panel_spa_root(self) -> str:
        return str(getattr(self._settings, "frontend_dist_root", None) or "/var/www/ifnotus")

    def _error_pages_root(self) -> Path:
        return Path("/var/www/ifnotus-errors")

    def ensure_diagnostic_error_pages(self) -> Path:
        """HTML shown instead of bare nginx 403/502 when a site/app is misconfigured."""
        from app.services.platform.hosting_ready_page import empty_site_html

        root = self._error_pages_root()
        root.mkdir(parents=True, exist_ok=True)
        down = root / "app-down.html"
        empty = root / "site-empty.html"
        if not down.is_file():
            down.write_text(
                """<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"/><meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>Application not running</title>
<style>
body{margin:0;min-height:100vh;display:grid;place-items:center;font-family:Figtree,system-ui,sans-serif;background:#f4f6f8;color:#1a1f24;padding:1.5rem}
main{max-width:34rem;background:#fff;border:1px solid #e2e8ef;border-radius:12px;padding:1.25rem 1.35rem}
h1{font-size:1.2rem;margin:0 0 .5rem}p{margin:.4rem 0;line-height:1.5;color:#3a4550}code{font-size:.9em}
ul{margin:.5rem 0 0;padding-left:1.1rem;line-height:1.45;color:#3a4550}
</style></head><body><main>
<h1>Your application is not responding</h1>
<p>Nginx reached this domain, but the Python/Node process behind it is down or crashing.</p>
<ul>
<li>Open <strong>Applications</strong> in your hosting panel and check status.</li>
<li>Read the app log (Passenger / app log path on the card).</li>
<li>Click <strong>Deploy</strong> or <strong>Restart</strong>.</li>
<li>For quick tests, use <strong>Terminal</strong> — see the install guide for Flask / FastAPI / Django commands.</li>
</ul>
<p>Common causes: wrong entry module (<code>app.main:app</code>), missing <code>requirements.txt</code>, app not listening on the assigned <code>PORT</code>, or a traceback on startup.</p>
</main></body></html>
""",
                encoding="utf-8",
            )
        # Always refresh — not a customer public_html file; nginx serves this via error_page.
        empty.write_text(empty_site_html(), encoding="utf-8")
        return root

    def _diagnostic_error_locations(self, *, proxy: bool) -> list[str]:
        err_root = self.ensure_diagnostic_error_pages()
        if proxy:
            return [
                "    proxy_intercept_errors on;",
                "    error_page 502 503 504 /__ifnotus_app_down.html;",
                "    location = /__ifnotus_app_down.html {",
                f"        alias {err_root}/app-down.html;",
                "        default_type text/html;",
                "        internal;",
                "    }",
            ]
        return [
            # Empty public roots return 403 from nginx; rewrite to a 200 parking page
            # served from /var/www/ifnotus-errors (never written into the tenant folder).
            "    error_page 403 =200 /__ifnotus_site_empty.html;",
            "    location = /__ifnotus_site_empty.html {",
            f"        alias {err_root}/site-empty.html;",
            "        default_type text/html;",
            "        internal;",
            "    }",
        ]

    @staticmethod
    def _hostname_from_nginx_conf(conf: str) -> str | None:
        match = re.search(r"server_name\s+([^;\s]+)", conf)
        if not match:
            return None
        host = match.group(1).strip().lower()
        if host in {"_", "default_server"}:
            return None
        return host

    def _api_upstream(self) -> str:
        return str(getattr(self._settings, "local_api_upstream", None) or "http://127.0.0.1:8010")

    def _cpanel_spa_locations(self) -> list[str]:
        """Serve the same SPA + API proxy as cpanel.ifnotus.space / ifnotus.space."""
        root = self._panel_spa_root()
        upstream = self._api_upstream()
        return [
            f"    root {root};",
            "    index index.html;",
            "    location /api/ {",
            f"        proxy_pass {upstream};",
            "        proxy_http_version 1.1;",
            "        proxy_set_header Host $host;",
            "        proxy_set_header X-Real-IP $remote_addr;",
            "        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;",
            "        proxy_set_header X-Forwarded-Proto $scheme;",
            "    }",
            "    location / {",
            "        try_files $uri $uri/ /index.html;",
            "    }",
        ]

    def _cpanel_spa_server(
        self,
        *,
        cpanel_host: str,
        cert: str | None = None,
        key: str | None = None,
        listen_https: bool = False,
    ) -> list[str]:
        fpanel_host = cpanel_host
        if cpanel_host.startswith("cpanel."):
            fpanel_host = f"fpanel.{cpanel_host[len('cpanel.'):]}"
        elif not cpanel_host.startswith("fpanel."):
            fpanel_host = f"fpanel.{cpanel_host}"

        lines: list[str] = []

        if listen_https and cert and key:
            # Modern HTTPS fpanel.<domain> SPA host
            lines += [
                "# Customer control-panel host — Hosting Panel SPA (stays on fpanel.<domain>)",
                "server {",
                "    listen 443 ssl;",
                "    listen [::]:443 ssl;",
                f"    server_name {fpanel_host};",
                f"    ssl_certificate {cert};",
                f"    ssl_certificate_key {key};",
            ]
            if Path("/etc/letsencrypt/options-ssl-nginx.conf").exists():
                lines.append("    include /etc/letsencrypt/options-ssl-nginx.conf;")
            if Path("/etc/letsencrypt/ssl-dhparams.pem").exists():
                lines.append("    ssl_dhparam /etc/letsencrypt/ssl-dhparams.pem;")
            lines += self._cpanel_spa_locations()
            lines += ["}", ""]

            # Modern HTTP fpanel.<domain> -> redirect to HTTPS (with acme-challenge)
            lines += [
                "# Customer control-panel host — Hosting Panel SPA (HTTP redirect)",
                "server {",
                "    listen 80;",
                "    listen [::]:80;",
                f"    server_name {fpanel_host};",
                "    location ^~ /.well-known/acme-challenge/ {",
                f"        root {ACME_WEBROOT};",
                "        default_type text/plain;",
                "        allow all;",
                "    }",
                "    location / {",
                f"        return 301 https://{fpanel_host}$request_uri;",
                "    }",
                "}",
                "",
            ]
        else:
            # Modern HTTP fpanel.<domain> (HTTP only)
            lines += [
                "# Customer control-panel host — Hosting Panel SPA (HTTP)",
                "server {",
                "    listen 80;",
                "    listen [::]:80;",
                f"    server_name {fpanel_host};",
                "    location ^~ /.well-known/acme-challenge/ {",
                f"        root {ACME_WEBROOT};",
                "        default_type text/plain;",
                "        allow all;",
                "    }",
            ]
            if cert and key:
                lines += [
                    "    location / {",
                    f"        return 301 https://{fpanel_host}$request_uri;",
                    "    }",
                ]
            else:
                lines += self._cpanel_spa_locations()
            lines += ["}", ""]
        return lines

    def _webmail_server(
        self,
        *,
        webmail_host: str,
        cert: str | None = None,
        key: str | None = None,
        listen_https: bool = False,
    ) -> list[str]:
        rc_root = str(getattr(self._settings, "roundcube_public_html", None) or "/var/lib/roundcube/public_html")
        sock = self._resolve_php_fpm_socket()
        lines: list[str] = [
            "# Customer webmail host — Roundcube Webmail (stays on webmail.<domain>)",
            "server {",
        ]
        if listen_https and cert and key:
            lines += [
                "    listen 443 ssl;",
                "    listen [::]:443 ssl;",
                f"    server_name {webmail_host};",
                f"    ssl_certificate {cert};",
                f"    ssl_certificate_key {key};",
            ]
            if Path("/etc/letsencrypt/options-ssl-nginx.conf").exists():
                lines.append("    include /etc/letsencrypt/options-ssl-nginx.conf;")
            if Path("/etc/letsencrypt/ssl-dhparams.pem").exists():
                lines.append("    ssl_dhparam /etc/letsencrypt/ssl-dhparams.pem;")
            lines += [
                f"    root {rc_root};",
                "    index index.php index.html;",
                "    location ~ ^/(README|INSTALL|LICENSE|CHANGELOG|UPGRADING)$ { deny all; }",
                "    location ~ ^/(bin|SQL|config|temp|logs)/ { deny all; }",
                "    location ~ ^/\\. { deny all; }",
                "    location / {",
                "        try_files $uri $uri/ /index.php?$args;",
                "    }",
                "    location ~ \\.php$ {",
                "        include snippets/fastcgi-php.conf;",
                f"        fastcgi_pass unix:{sock};",
                "    }",
                "}",
                "",
            ]
            lines += [
                "# Webmail hostname HTTP redirect (HTTPS enabled)",
                "server {",
                "    listen 80;",
                "    listen [::]:80;",
                f"    server_name {webmail_host};",
                "    location ^~ /.well-known/acme-challenge/ {",
                f"        root {ACME_WEBROOT};",
                "        default_type text/plain;",
                "        allow all;",
                "    }",
                "    location / {",
                f"        return 301 https://$host$request_uri;",
                "    }",
                "}",
                "",
            ]
            return lines
        else:
            lines += [
                "    listen 80;",
                "    listen [::]:80;",
                f"    server_name {webmail_host};",
                "    location ^~ /.well-known/acme-challenge/ {",
                f"        root {ACME_WEBROOT};",
                "        default_type text/plain;",
                "        allow all;",
                "    }",
            ]
            if cert and key:
                lines += [
                    "    location / {",
                    "        return 301 https://$host$request_uri;",
                    "    }",
                ]
            else:
                lines += [
                    f"    root {rc_root};",
                    "    index index.php index.html;",
                    "    location / {",
                    "        try_files $uri $uri/ /index.php?$args;",
                    "    }",
                    "    location ~ \\.php$ {",
                    "        include snippets/fastcgi-php.conf;",
                    f"        fastcgi_pass unix:{sock};",
                    "    }",
                ]
        lines += ["}", ""]
        return lines

    def _mail_redirect_server(
        self,
        *,
        mail_host: str,
        webmail_host: str,
        cert: str | None = None,
        key: str | None = None,
        listen_https: bool = False,
    ) -> list[str]:
        lines: list[str] = [
            "# Mail hostname HTTP/HTTPS convenience redirect to webmail",
            "server {",
        ]
        if listen_https and cert and key:
            lines += [
                "    listen 443 ssl;",
                "    listen [::]:443 ssl;",
                f"    server_name {mail_host};",
                f"    ssl_certificate {cert};",
                f"    ssl_certificate_key {key};",
            ]
            if Path("/etc/letsencrypt/options-ssl-nginx.conf").exists():
                lines.append("    include /etc/letsencrypt/options-ssl-nginx.conf;")
            if Path("/etc/letsencrypt/ssl-dhparams.pem").exists():
                lines.append("    ssl_dhparam /etc/letsencrypt/ssl-dhparams.pem;")
            lines += [
                "    location / {",
                f"        return 302 https://{webmail_host}$request_uri;",
                "    }",
                "}",
                "",
            ]
            lines += [
                "# Mail hostname HTTP redirect (HTTPS enabled)",
                "server {",
                "    listen 80;",
                "    listen [::]:80;",
                f"    server_name {mail_host};",
                "    location ^~ /.well-known/acme-challenge/ {",
                f"        root {ACME_WEBROOT};",
                "        default_type text/plain;",
                "        allow all;",
                "    }",
                "    location / {",
                f"        return 302 https://{webmail_host}$request_uri;",
                "    }",
                "}",
                "",
            ]
            return lines
        else:
            lines += [
                "    listen 80;",
                "    listen [::]:80;",
                f"    server_name {mail_host};",
                "    location ^~ /.well-known/acme-challenge/ {",
                f"        root {ACME_WEBROOT};",
                "        default_type text/plain;",
                "        allow all;",
                "    }",
                "    location / {",
                f"        return 302 https://{webmail_host}$request_uri;",
                "    }",
            ]
        lines += ["}", ""]
        return lines

    def _http_alias_redirect_servers(
        self,
        *,
        cpanel_host: str | None,
        webmail_host: str | None = None,
        mail_host: str | None = None,
    ) -> list[str]:
        """Dedicated port-80 servers for cpanel.* / fpanel.* (SPA) / webmail.* / mail.*."""
        lines: list[str] = []
        if cpanel_host:
            lines += self._cpanel_spa_server(
                cpanel_host=cpanel_host, cert=None, key=None, listen_https=False
            )
        if webmail_host:
            lines += self._webmail_server(
                webmail_host=webmail_host, cert=None, key=None, listen_https=False
            )
        if mail_host and webmail_host:
            lines += self._mail_redirect_server(
                mail_host=mail_host, webmail_host=webmail_host, listen_https=False
            )
        return lines

    def _alias_host_ifs(self, *, cpanel_host: str | None, mail_host: str | None) -> list[str]:
        """Deprecated: alias hosts use dedicated HTTP servers now."""
        return []

    def _panel_redirect_proxy(self) -> str:
        port = int(getattr(self._settings, "port", None) or 8010)
        prefix = (getattr(self._settings, "api_prefix", None) or "/api") + (
            getattr(self._settings, "api_v1_prefix", None) or "/v1"
        )
        return f"http://127.0.0.1:{port}{prefix}/public/panel-redirect"

    def _tenant_panel_embed_locations(self, hostname: str | None = None, *, skip_api: bool = False) -> list[str]:
        """Serve Hosting Panel SPA paths on tenant subdomains (user.ifnotus.space/hosting/*)."""
        from urllib.parse import quote

        root = self._panel_spa_root()
        upstream = self._api_upstream()
        host = (hostname or "").strip().lower()
        if host.startswith("www."):
            host = host[4:]
        go_redirect = quote(f"/go/hosting?host={host}", safe="")
        lines: list[str] = [
            "    # Tenant hosting panel (same-origin /hosting/* + SSO)",
        ]
        if not skip_api:
            lines += [
                "    location ^~ /api/ {",
                f"        proxy_pass {upstream};",
                "        proxy_http_version 1.1;",
                "        proxy_set_header Host $host;",
                "        proxy_set_header X-Real-IP $remote_addr;",
                "        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;",
                "        proxy_set_header X-Forwarded-Proto $scheme;",
                "    }",
            ]
        lines += [
            "    location ^~ /assets/ {",
            f"        root {root};",
            "        try_files $uri =404;",
            '        add_header Cache-Control "public, max-age=31536000, immutable" always;',
            "    }",
            "    location = /favicon.svg {",
            f"        root {root};",
            "        try_files /favicon.svg =404;",
            "    }",
            "    location = /login {",
            f"        return 302 https://ifnotus.space/login?redirect={go_redirect};",
            "    }",
            "    location ^~ /login/ {",
            f"        return 302 https://ifnotus.space/login?redirect={go_redirect};",
            "    }",
            "    location = /signup {",
            "        return 302 https://ifnotus.space/signup$is_args$args;",
            "    }",
            "    location ^~ /hosting/ {",
            f"        root {root};",
            "        try_files /index.html =404;",
            '        add_header Cache-Control "no-store" always;',
            "    }",
            "    location = /sso {",
            f"        root {root};",
            "        try_files /index.html =404;",
            '        add_header Cache-Control "no-store" always;',
            "    }",
        ]
        for prefix in (
            "files",
            "databases",
            "domains",
            "cron",
            "backups",
            "logs",
            "transfer",
            "stack",
            "ai",
            "apps",
            "email",
            "git",
        ):
            lines += [
                f"    location ^~ /{prefix} {{",
                f"        root {root};",
                "        try_files /index.html =404;",
                '        add_header Cache-Control "no-store" always;',
                "    }",
            ]
        return lines

    def _roundcube_path_locations(self, *, hostname: str | None = None) -> list[str]:
        """Serve Roundcube under /mail on the same host (no cross-host redirect)."""
        # Roundcube lives outside tenant open_basedir — always use the system PHP pool.
        sock = None
        for candidate in (
            "/run/php/php8.3-fpm.sock",
            "/run/php/php8.2-fpm.sock",
            "/run/php/php8.1-fpm.sock",
            "/run/php/php-fpm.sock",
            getattr(self._settings, "php_fpm_socket", None),
        ):
            if candidate and Path(candidate).exists():
                sock = candidate
                break
        sock = sock or "/run/php/php8.3-fpm.sock"
        rc_root = str(getattr(self._settings, "roundcube_public_html", None) or "/var/lib/roundcube/public_html")
        return [
            "    # Roundcube webmail (IFNOTUS) — https://{domain}/mail/",
            "    location = /webmail {",
            "        return 302 /mail/;",
            "    }",
            "    location = /webmail/ {",
            "        return 302 /mail/;",
            "    }",
            "    location = /mail {",
            "        return 302 /mail/;",
            "    }",
            "    location ~ ^/mail/(.+\\.php)$ {",
            "        include fastcgi_params;",
            f"        fastcgi_param SCRIPT_FILENAME {rc_root}/$1;",
            f"        fastcgi_pass unix:{sock};",
            "    }",
            "    location = /mail/ {",
            "        rewrite ^ /mail/index.php last;",
            "    }",
            "    location /mail/ {",
            f"        alias {rc_root}/;",
            "    }",
        ]

    def _webmail_locations(self, *, hostname: str | None = None, skip_api: bool = False) -> list[str]:
        """Customer convenience locations on the primary website vhost:
        /fpanel & /cpanel -> hosting panel
        /mail & /webmail -> same-host Roundcube (tenant sites)
        Platform apex /mail -> shared mail.ifnotus.space only
        """
        from app.services.platform.panel_access import (
            PLATFORM_APEX,
            PLATFORM_MAIL_HOST,
            PLATFORM_SERVICE_HOSTS,
            STAFF_PANEL_HOST,
            _is_subdomain_host,
            customer_panel_redirect_url,
        )

        raw_host = (hostname or "").strip().lower()
        if raw_host.startswith("www."):
            raw_host = raw_host[4:]
        fpanel_url = customer_panel_redirect_url(raw_host, settings=self._settings) or f"https://{raw_host}/hosting/"

        lines = [
            "    # Customer convenience redirects",
            "    location = /fpanel {",
            f"        return 302 {fpanel_url};",
            "    }",
            "    location = /fpanel/ {",
            f"        return 302 {fpanel_url};",
            "    }",
            "    location = /cpanel {",
            f"        return 302 {fpanel_url};",
            "    }",
            "    location = /cpanel/ {",
            f"        return 302 {fpanel_url};",
            "    }",
        ]

        # Shared mail server UI only — marketing apex / staff never embed tenant /mail.
        use_platform_mail_redirect = (
            not raw_host
            or raw_host == PLATFORM_APEX
            or raw_host == STAFF_PANEL_HOST
            or raw_host in PLATFORM_SERVICE_HOSTS
        )
        if use_platform_mail_redirect:
            platform_mail = f"https://{PLATFORM_MAIL_HOST}/"
            lines += [
                "    location = /webmail {",
                f"        return 302 {platform_mail};",
                "    }",
                "    location = /webmail/ {",
                f"        return 302 {platform_mail};",
                "    }",
                "    location = /mail {",
                f"        return 302 {platform_mail};",
                "    }",
                "    location = /mail/ {",
                f"        return 302 {platform_mail};",
                "    }",
            ]
        else:
            lines += self._roundcube_path_locations(hostname=raw_host or None)

        if raw_host and _is_subdomain_host(raw_host, settings=self._settings):
            lines += self._tenant_panel_embed_locations(raw_host, skip_api=skip_api)
        return lines

    def _location_block(
        self,
        *,
        hostname: str,
        root: str,
        proxy_port: int | None,
        redirect_url: str | None,
        path_redirects: list[dict],
    ) -> list[str]:
        lines: list[str] = [f"    root {root};"]
        php_index = Path(root) / "index.php"
        if php_index.is_file():
            lines.append("    index index.php index.html index.htm;")
        else:
            lines.append("    index index.html index.htm index.php;")
        # Webmail must win over whole-site redirect and app proxy_pass.
        lines += self._webmail_locations(hostname=hostname)
        # Per-app proxy locations + bandwidth soft-block overlays.
        host_apps = Path(f"/etc/nginx/ifnotus-apps/hosts/{hostname}")
        try:
            host_apps.mkdir(parents=True, exist_ok=True)
        except OSError:
            pass
        if host_apps.is_dir():
            # Keep a harmless placeholder so empty globs never break nginx -t.
            placeholder = host_apps / "zz-ifnotus-placeholder.conf"
            if not placeholder.is_file() and not any(host_apps.glob("*.conf")):
                try:
                    placeholder.write_text("# ifnotus apps / bandwidth overlay\n", encoding="utf-8")
                except OSError:
                    pass
            lines.append(f"    include /etc/nginx/ifnotus-apps/hosts/{hostname}/*.conf;")
        seen_sources: set[str] = set()
        for redir in path_redirects:
            if not redir.get("enabled", True):
                continue
            source = str(redir.get("source_path") or "/").strip() or "/"
            target = str(redir.get("target_url") or "").strip()
            code = int(redir.get("status_code") or 301)
            if not target:
                continue
            if source == "/":
                # whole-site path redirect handled below via redirect_url preference
                continue
            # Avoid duplicate location blocks (nginx emerg).
            if source in seen_sources:
                continue
            seen_sources.add(source)
            lines += [
                f"    location = {source} {{",
                f"        return {code} {target};",
                "    }",
            ]
            # also prefix match for trailing paths when source ends without file
            if not Path(source).suffix:
                prefix = source.rstrip("/") + "/"
                if prefix not in seen_sources:
                    seen_sources.add(prefix)
                    lines += [
                        f"    location {prefix} {{",
                        f"        return {code} {target};",
                        "    }",
                    ]

        if redirect_url:
            code = 301
            lines += [
                "    location / {",
                f"        return {code} {redirect_url};",
                "    }",
            ]
            return lines

        if proxy_port:
            lines += self._diagnostic_error_locations(proxy=True)
            lines += [
                "    location / {",
                f"        proxy_pass http://127.0.0.1:{proxy_port};",
                "        proxy_http_version 1.1;",
                "        proxy_set_header Host $host;",
                "        proxy_set_header X-Real-IP $remote_addr;",
                "        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;",
                "        proxy_set_header X-Forwarded-Proto $scheme;",
                "        proxy_set_header Upgrade $http_upgrade;",
                "        proxy_set_header Connection $connection_upgrade;",
                "        proxy_next_upstream error timeout http_502 http_503 http_504;",
                "        proxy_connect_timeout 5s;",
                "        proxy_read_timeout 120s;",
                "    }",
            ]
            # map for upgrade may not exist — keep Connection close-safe alternative
            return [
                line.replace("proxy_set_header Connection $connection_upgrade;", 'proxy_set_header Connection "";')
                if "connection_upgrade" in line
                else line
                for line in lines
            ]

        lines += self._diagnostic_error_locations(proxy=False)
        lines += [
            "    location / {",
            "        try_files $uri $uri/ /index.php?$args;",
            "    }",
        ]
        # PHP-FPM for WordPress / Laravel / PHP apps
        sock = self._resolve_php_fpm_socket(hostname)
        if sock and Path("/etc/nginx/snippets/fastcgi-php.conf").exists():
            open_basedir = self._php_open_basedir(root)
            lines += [
                "    location ~ \\.php$ {",
                "        include snippets/fastcgi-php.conf;",
                f"        fastcgi_pass unix:{sock};",
            ]
            if open_basedir:
                # Jail PHP to this site tree (+ /tmp) — never host root / other customers.
                safe = open_basedir.replace("\\", "\\\\").replace('"', '\\"')
                lines.append(f'        fastcgi_param PHP_VALUE "open_basedir={safe}";')
            lines.append("    }")
        return lines

    def _php_open_basedir(self, root: str) -> str | None:
        """Limit PHP file access to the customer site folder when under tenant root."""
        try:
            path = Path(root).resolve()
            customers = Path(self._settings.customer_environments_root).resolve()
            path.relative_to(customers)
        except (OSError, ValueError):
            return None
        base = path
        if base.name in {"public", "public_html", "web", "httpdocs"}:
            base = base.parent
        return f"{base}:/tmp:/var/tmp"

    def _resolve_php_fpm_socket(self, hostname: str | None = None) -> str | None:
        from app.services.platform.php_fpm import PhpFpmPoolService

        candidates: list[str] = []
        if hostname:
            pool_sock = PhpFpmPoolService(self._settings).socket_for(hostname)
            candidates.append(str(pool_sock))
        candidates += [
            self._settings.php_fpm_socket,
            "/run/php/php8.3-fpm.sock",
            "/run/php/php8.2-fpm.sock",
            "/run/php/php8.1-fpm.sock",
            "/run/php/php-fpm.sock",
        ]
        for path in candidates:
            if path and Path(path).exists():
                return path
        return None

    @staticmethod
    def _is_https_server_block(block: str) -> bool:
        return "listen 443" in block or "listen [::]:443" in block

    @staticmethod
    def _is_http_redirect_only_server(block: str) -> bool:
        """Port-80 vhost whose catch-all location / only redirects to HTTPS."""
        if DomainNginxProvisioner._is_https_server_block(block):
            return False
        if "listen 80" not in block and "listen [::]:80" not in block:
            return False
        match = re.search(r"location\s+/\s*\{([^}]*)\}", block, re.DOTALL)
        if not match:
            return False
        body = match.group(1)
        return bool(re.search(r"return\s+30[12]\s+https://", body))

    @staticmethod
    def _server_block_has_panel_embed(block: str) -> bool:
        return (
            "location = /fpanel" in block
            and "location = /mail" in block
            and "location ^~ /hosting/" in block
            and "location ^~ /files {" in block
            and "location ^~ /assets/" in block
        )

    @staticmethod
    def _inject_before_location_root(block: str, insert: str) -> str:
        if DomainNginxProvisioner._server_block_has_panel_embed(block):
            return block
        updated = re.sub(
            r"(^[ \t]*location / \{)",
            insert + r"\1",
            block,
            count=1,
            flags=re.MULTILINE,
        )
        return updated if updated != block else block

    @staticmethod
    def _replace_server_blocks(conf: str, replacer) -> str:
        out: list[str] = []
        i = 0
        while i < len(conf):
            match = re.search(r"^\s*server\s*\{", conf[i:], re.MULTILINE)
            if not match:
                out.append(conf[i:])
                break
            start = i + match.start()
            out.append(conf[i:start])
            depth = 0
            j = start
            while j < len(conf):
                ch = conf[j]
                if ch == "{":
                    depth += 1
                elif ch == "}":
                    depth -= 1
                    if depth == 0:
                        j += 1
                        break
                j += 1
            block = conf[start:j]
            out.append(replacer(block))
            i = j
        return "".join(out)

    @staticmethod
    def is_custom_app_proxy_config(conf: str) -> bool:
        """Hand-tuned nginx with upstream/app proxy — never full-replace on reconcile."""
        if MANAGED_MARKER in conf or "managed-by-ifnotus" in conf:
            return False
        if re.search(r"^\s*upstream\s+\w+", conf, re.MULTILINE):
            return True
        if re.search(r"proxy_pass\s+http://127\.0\.0\.1:(?!8010)\d+", conf):
            return True
        if re.search(r"proxy_pass\s+http://unix:", conf):
            return True
        if re.search(r"proxy_pass\s+http://\w+;", conf):
            return True
        # Production app trees under /srv/apps (Laravel/Django products) — preserve.
        if re.search(r"^\s*root\s+/srv/apps/", conf, re.MULTILINE):
            return True
        return False

    @staticmethod
    def infer_proxy_port_from_config(conf: str) -> int | None:
        match = re.search(r"upstream\s+\w+\s*\{[^}]*server\s+127\.0\.0\.1:(\d+)", conf, re.DOTALL)
        if match:
            return int(match.group(1))
        match = re.search(r"proxy_pass\s+http://127\.0\.0\.1:(\d+)", conf)
        if match:
            port = int(match.group(1))
            return port if port != 8010 else None
        return None

    def inject_webmail_into_config(self, conf: str) -> str:
        """Ensure /mail, /cpanel, and tenant panel paths exist in serving server blocks."""
        mail_section = ""
        if "Roundcube webmail" in conf:
            mail_section = conf.split("Roundcube webmail", 1)[1].split("Tenant hosting", 1)[0]
        has_same_host_mail = (
            "alias /var/lib/roundcube/public_html/" in mail_section
            and "include fastcgi_params;" in mail_section
            and "fastcgi_param SCRIPT_FILENAME /var/lib/roundcube/public_html/" in mail_section
            and "snippets/fastcgi-php.conf" not in mail_section
            and "/run/php/ifnotus-" not in mail_section
        )
        wrongly_bounces_to_platform_mail = (
            "location = /mail" in conf
            and "return 302 https://mail.ifnotus.space/" in conf
            and "Roundcube webmail (IFNOTUS)" not in conf
        )
        if "location = /fpanel" in conf and "location = /mail" in conf and has_same_host_mail and not wrongly_bounces_to_platform_mail:
            has_tenant_panel = "location ^~ /hosting/" in conf
            has_tenant_assets = "location ^~ /assets/" in conf
            has_tenant_login = (
                "ifnotus.space/login" in conf
                and ("go/hosting?host=" in conf or "redirect=%2Fgo%2Fhosting" in conf)
            )
            has_tenant_panel_tools = "location ^~ /files {" in conf
            if has_tenant_panel and has_tenant_assets and has_tenant_login and has_tenant_panel_tools:
                needs_https_inject = False

                def check_block(server_block: str) -> str:
                    nonlocal needs_https_inject
                    if self._is_https_server_block(server_block) and not self._server_block_has_panel_embed(server_block):
                        needs_https_inject = True
                    if self._is_http_redirect_only_server(server_block) and "location ^~ /hosting/" in server_block:
                        needs_https_inject = True
                    return server_block

                self._replace_server_blocks(conf, check_block)
                if not needs_https_inject:
                    return conf

        # Strip old embedded Roundcube /mail blocks, /webmail, /fpanel, and stale /cpanel blocks.
        cleaned = re.sub(
            r"[ \t]*# Tenant hosting panel[\s\S]*?(?=[ \t]*# Customer convenience redirects|[ \t]*location / \{|\Z)",
            "",
            conf,
        )
        cleaned = re.sub(
            r"[ \t]*# Customer convenience redirects[\s\S]*?(?=[ \t]*location / \{|\Z)",
            "",
            cleaned,
        )
        cleaned = re.sub(
            r"[ \t]*location = /fpanel/? \{[\s\S]*?\n[ \t]*\}\n",
            "",
            cleaned,
        )
        cleaned = re.sub(
            r"[ \t]*location = /webmail/? \{[\s\S]*?\n[ \t]*\}\n",
            "",
            cleaned,
        )
        cleaned = re.sub(
            r"\n?[ \t]*# Roundcube webmail[^\n]*\n"
            r"(?:[ \t]*location = /mail \{[\s\S]*?\n[ \t]*\}\n)?"
            r"(?:[ \t]*location ~ \^/mail/[^\n]+\n(?:[ \t]+[^\n]+\n)*?[ \t]*\}\n)?"
            r"(?:[ \t]*location = /mail/ \{[\s\S]*?\n[ \t]*\}\n)?"
            r"(?:[ \t]*location /mail/ \{[\s\S]*?\n[ \t]*\}\n)?",
            "\n",
            cleaned,
        )
        cleaned = re.sub(
            r"[ \t]*# Roundcube lives on mail\.ifnotus\.space[^\n]*\n"
            r"(?:[ \t]*# [^\n]*\n)*"
            r"(?:[ \t]*location = /mail \{[\s\S]*?\n[ \t]*\}\n)?"
            r"(?:[ \t]*location /mail/ \{[\s\S]*?\n[ \t]*\}\n)?"
            r"(?:[ \t]*# (?:Control panel|Tenant hosting panel)[^\n]*\n)?"
            r"(?:[ \t]*location = /cpanel \{[\s\S]*?\n[ \t]*\}\n)?"
            r"(?:[ \t]*location = /cpanel/ \{[\s\S]*?\n[ \t]*\}\n)?",
            "",
            cleaned,
        )
        cleaned = re.sub(
            r"[ \t]*location = /mail \{[\s\S]*?\n[ \t]*\}\n"
            r"(?:[ \t]*location ~ \^/mail/[\s\S]*?\n[ \t]*\}\n)?"
            r"(?:[ \t]*location = /mail/ \{[\s\S]*?\n[ \t]*\}\n)?"
            r"(?:[ \t]*location /mail/ \{[\s\S]*?\n[ \t]*\}\n)?",
            "",
            cleaned,
        )
        cleaned = re.sub(
            r"[ \t]*# (?:Control panel|Tenant hosting panel)[^\n]*\n"
            r"(?:[ \t]*location = /cpanel \{[\s\S]*?\n[ \t]*\}\n)?"
            r"(?:[ \t]*location = /cpanel/ \{[\s\S]*?\n[ \t]*\}\n)?",
            "",
            cleaned,
        )
        # Stale API proxy for /cpanel (HEAD → 405; prefer direct 302 to portal).
        cleaned = re.sub(
            r"[ \t]*location = /cpanel/? \{[\s\S]*?panel-redirect[\s\S]*?\n[ \t]*\}\n",
            "",
            cleaned,
        )
        cleaned = re.sub(
            r"[ \t]*location = /cpanel \{[\s\S]*?\n[ \t]*\}\n"
            r"(?:[ \t]*location = /cpanel/ \{[\s\S]*?\n[ \t]*\}\n)?",
            "",
            cleaned,
        )
        block_lines = self._webmail_locations(
            hostname=self._hostname_from_nginx_conf(conf),
            skip_api=bool(re.search(r"location\s+(?:\^~\s+)?/api/", cleaned)),
        )
        block = "\n".join(block_lines) + "\n"

        def replacer(server_block: str) -> str:
            if self._is_http_redirect_only_server(server_block):
                return server_block
            return self._inject_before_location_root(server_block, block)

        updated = self._replace_server_blocks(cleaned, replacer)
        return updated if updated != conf else conf

    async def ensure_webmail_on_all_sites(self) -> OperationResult:
        """Add /mail webmail to every nginx site that does not already have it."""
        if not self._available.is_dir():
            return OperationResult(success=False, message="nginx sites-available missing")
        skip_hosts = {
            "00-default-catchall.conf",
            "00-default-catchall",
            "fpanel.ifnotus.space",
            "cpanel.ifnotus.space",
            "ifnotus.space",
            "mail.ifnotus.space",
            "default",
        }
        changed: list[str] = []
        skipped: list[str] = []
        enabled_names = set()
        if self._enabled.is_dir():
            for link in self._enabled.iterdir():
                enabled_names.add(link.name)

        for path in sorted(self._available.iterdir()):
            if not path.is_file() or path.name.startswith("."):
                continue
            name = path.name
            # Never touch backups / package leftovers / disabled drafts
            if ".bak" in name or name.endswith((".tmp", ".dpkg-old", ".dpkg-dist", ".swp")):
                continue
            if name.endswith(".pre-webmail"):
                continue
            if name in skip_hosts or name.startswith("fpanel.") or name.startswith("cpanel."):
                skipped.append(name)
                continue
            # Prefer enabled sites; also allow managed available sites not yet linked
            if enabled_names and name not in enabled_names:
                skipped.append(name)
                continue
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            updated = self.inject_webmail_into_config(text)
            if updated == text:
                skipped.append(name)
                continue
            bak = path.with_name(f"{name}.bak-ifnotus-mail")
            try:
                if not bak.exists():
                    bak.write_text(text, encoding="utf-8")
                path.write_text(updated, encoding="utf-8")
                changed.append(name)
            except OSError as exc:
                return OperationResult(
                    success=False,
                    message=f"Failed writing {name}: {exc}",
                    details={"changed": changed, "skipped": skipped},
                )

        if not changed:
            return OperationResult(
                success=True,
                message="All nginx sites already expose /mail webmail.",
                details={"changed": changed, "skipped": skipped},
            )
        reload = await self._sites.reload()
        if not reload.success:
            # Reload failed — try to revert changed files from bak
            for name in changed:
                bak = self._available / f"{name}.bak-ifnotus-mail"
                site = self._available / name
                if bak.exists():
                    try:
                        site.write_text(bak.read_text(encoding="utf-8"), encoding="utf-8")
                    except OSError:
                        pass
            return OperationResult(
                success=False,
                message=reload.message,
                details={"changed": changed, "skipped": skipped, "reverted": True},
            )
        return OperationResult(
            success=True,
            message=f"Added /mail webmail to {len(changed)} nginx site(s).",
            details={"changed": changed, "skipped": skipped},
        )

    async def provision(
        self,
        *,
        hostname: str,
        document_root: str | None = None,
        proxy_port: int | None = None,
        force_https: bool = False,
        redirect_url: str | None = None,
        aliases: list[str] | None = None,
        ssl_certificate: str | None = None,
        enabled: bool = True,
        create_docroot: bool = True,
        path_redirects: list[dict] | None = None,
        force_takeover: bool = False,
        ram_gb: float | None = None,
        unix_user: str | None = None,
    ) -> OperationResult:
        from app.services.platform.panel_access import is_service_hostname

        # Service aliases (fpanel.*, webmail.*, mail.*) are embedded in the apex domain config —
        # never provision them as standalone customer website vhosts with parking pages.
        if is_service_hostname(hostname) and hostname not in {"fpanel.ifnotus.space", "mail.ifnotus.space"}:
            await self.remove_orphan_service_vhost(hostname)
            return OperationResult(
                success=True,
                message=f"Skipped standalone vhost for service alias {hostname} (handled by apex domain SPA block).",
            )

        root = document_root or f"/var/www/{hostname}"
        if create_docroot and not redirect_url:
            try:
                self.ensure_document_root(root, hostname=hostname)
            except OSError as exc:
                raise AppException(f"Could not create document root: {exc}", code="docroot_failed") from exc

        try:
            self.ensure_diagnostic_error_pages()
        except OSError:
            pass

        from app.services.platform.php_fpm import PhpFpmPoolService

        PhpFpmPoolService(self._settings).ensure_pool(
            hostname=hostname,
            document_root=root,
            ram_gb=ram_gb,
            unix_user=unix_user,
        )

        available, enabled_path = self.site_paths(hostname)
        self._available.mkdir(parents=True, exist_ok=True)
        self._enabled.mkdir(parents=True, exist_ok=True)

        existing_conf: str | None = None
        custom_app_proxy = False
        # Never overwrite an unmanaged / host nginx site (core platform configs).
        if available.exists():
            try:
                existing_conf = available.read_text(encoding="utf-8", errors="replace")
                custom_app_proxy = self.is_custom_app_proxy_config(existing_conf)
                unmanaged = MANAGED_MARKER not in existing_conf and "managed-by-ifnotus" not in existing_conf
                if unmanaged and not force_takeover:
                    raise AppException(
                        f"Nginx site {hostname} exists and is not IFNOTUS-managed — refusing to overwrite.",
                        code="nginx_unmanaged",
                    )
                if unmanaged and force_takeover and custom_app_proxy:
                    import shutil

                    bak = available.with_suffix(".bak-ifnotus-pre-takeover")
                    try:
                        if not bak.exists():
                            shutil.copy2(available, bak)
                    except OSError:
                        pass
                    merged = self.inject_webmail_into_config(existing_conf)
                    if merged != existing_conf:
                        tmp = available.with_suffix(".tmp")
                        tmp.write_text(merged, encoding="utf-8")
                        tmp.replace(available)
                    reload = await self._sites.reload()
                    if not reload.success:
                        return OperationResult(
                            success=False,
                            message=reload.message,
                            details={"site": str(available), "merged_only": True},
                        )
                    return OperationResult(
                        success=True,
                        message=f"Merged hosting panel routes into existing app proxy nginx config for {hostname}.",
                        details={
                            "site": str(available),
                            "document_root": root,
                            "enabled": enabled,
                            "merged_only": True,
                        },
                    )
                if unmanaged and force_takeover:
                    import shutil

                    bak = available.with_suffix(".bak-ifnotus-pre-takeover")
                    try:
                        shutil.copy2(available, bak)
                    except OSError:
                        pass
                if proxy_port is None and existing_conf:
                    inferred = self.infer_proxy_port_from_config(existing_conf)
                    if inferred:
                        proxy_port = inferred
            except AppException:
                raise
            except OSError:
                pass

        # Discover certificate if not explicitly passed
        if not ssl_certificate:
            from app.services.platform.panel_access import find_letsencrypt_cert

            f_cert, f_key = find_letsencrypt_cert(hostname)
            if f_cert and f_key:
                ssl_certificate = f_cert
                ssl_key = f_key
                force_https = True
            elif available.exists():
                try:
                    old = available.read_text(encoding="utf-8", errors="replace")
                    m_cert = re.search(r"ssl_certificate\s+([^;]+);", old)
                    m_key = re.search(r"ssl_certificate_key\s+([^;]+);", old)
                    if m_cert and m_key:
                        ssl_certificate = m_cert.group(1).strip()
                        ssl_key = m_key.group(1).strip()
                    else:
                        ssl_key = None
                except OSError:
                    ssl_key = None
        else:
            ssl_key = None
            if ssl_certificate:
                p = Path(ssl_certificate)
                ssl_key = str(p.parent / "privkey.pem") if p.name == "fullchain.pem" else None

        content = self.render_config(
            hostname=hostname,
            document_root=root,
            proxy_port=proxy_port,
            force_https=force_https,
            redirect_url=redirect_url,
            aliases=aliases,
            ssl_certificate=ssl_certificate,
            ssl_certificate_key=ssl_key if ssl_certificate else None,
            path_redirects=path_redirects,
        )
        content = self.inject_webmail_into_config(content)
        tmp = available.with_suffix(".tmp")
        tmp.write_text(content, encoding="utf-8")
        tmp.replace(available)

        try:
            if enabled:
                if enabled_path.exists() or enabled_path.is_symlink():
                    enabled_path.unlink()
                enabled_path.symlink_to(available)
            else:
                if enabled_path.is_symlink() or enabled_path.exists():
                    enabled_path.unlink()
        except OSError as exc:
            raise AppException(f"Failed to enable nginx site: {exc}", code="nginx_enable_failed") from exc

        reload = await self._sites.reload()
        if not reload.success:
            return OperationResult(
                success=False,
                message=reload.message,
                details={"site": str(available), "enabled": enabled},
            )
        return OperationResult(
            success=True,
            message=f"Nginx site provisioned for {hostname}.",
            details={
                "site": str(available),
                "enabled_path": str(enabled_path),
                "document_root": root,
                "enabled": enabled,
            },
        )

    def inject_diagnostics_into_config(self, conf: str) -> str:
        """Add helpful 403/502 pages to an existing managed vhost without a full rewrite."""
        err_root = self.ensure_diagnostic_error_pages()
        static_block = "\n".join(
            [
                "    error_page 403 =200 /__ifnotus_site_empty.html;",
                "    location = /__ifnotus_site_empty.html {",
                f"        alias {err_root}/site-empty.html;",
                "        default_type text/html;",
                "        internal;",
                "    }",
                "",
            ]
        )
        proxy_block = "\n".join(
            [
                "    proxy_intercept_errors on;",
                "    error_page 502 503 504 /__ifnotus_app_down.html;",
                "    location = /__ifnotus_app_down.html {",
                f"        alias {err_root}/app-down.html;",
                "        default_type text/html;",
                "        internal;",
                "    }",
                "",
            ]
        )

        lines = conf.splitlines(keepends=True)
        out: list[str] = []
        i = 0
        while i < len(lines):
            line = lines[i]
            stripped = line.strip()
            if stripped.startswith("location / {"):
                body: list[str] = []
                j = i + 1
                depth = 1
                while j < len(lines) and depth > 0:
                    body.append(lines[j])
                    depth += lines[j].count("{") - lines[j].count("}")
                    j += 1
                body_text = "".join(body)
                # Look back in the current server block for an already-injected marker.
                lookback = "".join(out[-80:])
                is_api = "8010" in body_text and "proxy_pass" in body_text
                is_app_proxy = (
                    "proxy_pass http://127.0.0.1:" in body_text
                    and "8010" not in body_text
                )
                is_php_site = "try_files" in body_text and "index.php" in body_text
                if is_app_proxy and "__ifnotus_app_down.html" not in lookback:
                    out.append(proxy_block)
                elif is_php_site and not is_api and "__ifnotus_site_empty.html" not in lookback:
                    out.append(static_block)
            out.append(line)
            i += 1
        return "".join(out)

    def patch_managed_sites_diagnostics(self) -> list[str]:
        """Ensure every managed site file has diagnostic error pages."""
        updated: list[str] = []
        if not self._available.is_dir():
            return updated
        self.ensure_diagnostic_error_pages()
        for path in sorted(self._available.iterdir()):
            if not path.is_file():
                continue
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            if MANAGED_MARKER not in text and "managed-by-ifnotus" not in text:
                continue
            new = self.inject_diagnostics_into_config(text)
            if new != text:
                try:
                    tmp = path.with_suffix(".tmp")
                    tmp.write_text(new, encoding="utf-8")
                    tmp.replace(path)
                    updated.append(path.name)
                except OSError:
                    continue
        return updated

    async def set_enabled(self, hostname: str, enabled: bool) -> OperationResult:
        available, enabled_path = self.site_paths(hostname)
        if not available.exists():
            return OperationResult(success=False, message=f"No nginx site for {hostname}. Provision first.")
        try:
            if enabled:
                if enabled_path.exists() or enabled_path.is_symlink():
                    enabled_path.unlink()
                enabled_path.symlink_to(available)
            else:
                if enabled_path.exists() or enabled_path.is_symlink():
                    enabled_path.unlink()
        except OSError as exc:
            return OperationResult(success=False, message=str(exc))
        reload = await self._sites.reload()
        if not reload.success:
            return reload
        return OperationResult(
            success=True,
            message=f"Nginx site for {hostname} {'enabled' if enabled else 'disabled'}.",
        )

    async def remove_orphan_service_vhost(self, hostname: str) -> None:
        """Delete a wrongly provisioned standalone fpanel./webmail./mail. site file."""
        available, enabled_path = self.site_paths(hostname)
        try:
            if enabled_path.exists() or enabled_path.is_symlink():
                enabled_path.unlink()
            if available.exists():
                text = available.read_text(encoding="utf-8", errors="replace")
                if MANAGED_MARKER in text or "managed-by-ifnotus" in text:
                    available.unlink()
        except OSError:
            pass

    async def cleanup_orphan_service_vhosts(self) -> list[str]:
        """Remove standalone service-alias nginx sites (fpanel.*, webmail.*) that duplicate apex SPA blocks."""
        from app.services.platform.panel_access import is_service_hostname

        removed: list[str] = []
        if not self._available.is_dir():
            return removed
        keep = {"fpanel.ifnotus.space", "mail.ifnotus.space", "cpanel.ifnotus.space"}
        for path in sorted(self._available.iterdir()):
            name = path.name
            if name in keep or not is_service_hostname(name):
                continue
            await self.remove_orphan_service_vhost(name)
            removed.append(name)
        if removed:
            await self._sites.reload()
        return removed

    async def remove(self, hostname: str, *, remove_files: bool = True) -> OperationResult:
        available, enabled_path = self.site_paths(hostname)
        try:
            if enabled_path.exists() or enabled_path.is_symlink():
                enabled_path.unlink()
            if remove_files and available.exists():
                # Only remove if IFNOTUS-managed
                text = available.read_text(encoding="utf-8", errors="replace")
                if MANAGED_MARKER not in text:
                    return OperationResult(
                        success=False,
                        message=f"Refusing to remove unmanaged nginx site {hostname}.",
                    )
                available.unlink()
        except OSError as exc:
            return OperationResult(success=False, message=str(exc))
        try:
            from app.services.platform.php_fpm import PhpFpmPoolService

            PhpFpmPoolService(self._settings).remove_pool(hostname)
        except Exception:  # noqa: BLE001
            pass
        try:
            import shutil

            host_apps = Path(f"/etc/nginx/ifnotus-apps/hosts/{hostname}")
            if host_apps.is_dir():
                shutil.rmtree(host_apps, ignore_errors=True)
        except Exception:  # noqa: BLE001
            pass
        reload = await self._sites.reload()
        if not reload.success:
            return reload
        return OperationResult(success=True, message=f"Removed nginx site for {hostname}.")

