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

    def ensure_document_root(
        self,
        path: str,
        *,
        hostname: str | None = None,
        display_hostname: str | None = None,
    ) -> Path:
        from app.services.platform.hosting_ready_page import write_hosting_ready_page
        from app.services.platform.tenant import ensure_cpanel_directory_layout

        root = Path(path).resolve()
        host = (hostname or "").strip() or root.parent.name or root.name
        portal = getattr(self._settings, "customer_portal_url", None) or "https://ifnotus.space"
        site_home = root.parent if root.name in {"public", "public_html", "web", "httpdocs"} and root.parent.exists() else root
        ensure_cpanel_directory_layout(site_home, web_dir=root, hostname=host)
        write_hosting_ready_page(
            root,
            hostname=host,
            portal_base=portal,
            display_hostname=display_hostname,
            force=False,
        )
        return root

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
        from app.services.platform.panel_access import control_panel_hostname, is_platform_hostname, webmail_hostname

        cpanel_host = None
        webmail_host = None
        mail_host = None
        if not is_platform_hostname(hostname):
            cpanel_host = control_panel_hostname(hostname)
            if "." in hostname and not hostname.startswith("www."):
                mail_host = f"mail.{hostname}"
                webmail_host = webmail_hostname(hostname)
        # www for apex custom domains (not for platform / student zones)
        if (
            not is_platform_hostname(hostname)
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
        root = document_root or f"/var/www/{hostname}"
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
            legacy_cpanel_host = cpanel_host
        elif cpanel_host.startswith("fpanel."):
            legacy_cpanel_host = f"cpanel.{cpanel_host[len('fpanel.'):]}"
        else:
            fpanel_host = f"fpanel.{cpanel_host}"
            legacy_cpanel_host = f"cpanel.{cpanel_host}"

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

            # Legacy HTTPS cpanel.<domain> permanent redirect -> fpanel.<domain>
            lines += [
                "# Legacy cpanel.<domain> redirect -> fpanel.<domain>",
                "server {",
                "    listen 443 ssl;",
                "    listen [::]:443 ssl;",
                f"    server_name {legacy_cpanel_host};",
                f"    ssl_certificate {cert};",
                f"    ssl_certificate_key {key};",
            ]
            if Path("/etc/letsencrypt/options-ssl-nginx.conf").exists():
                lines.append("    include /etc/letsencrypt/options-ssl-nginx.conf;")
            if Path("/etc/letsencrypt/ssl-dhparams.pem").exists():
                lines.append("    ssl_dhparam /etc/letsencrypt/ssl-dhparams.pem;")
            lines += [
                "    location / {",
                f"        return 301 https://{fpanel_host}$request_uri;",
                "    }",
                "}",
                "",
            ]

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

            # Legacy HTTP cpanel.<domain> redirect -> fpanel.<domain>
            lines += [
                "# Legacy cpanel.<domain> HTTP redirect -> fpanel.<domain>",
                "server {",
                "    listen 80;",
                "    listen [::]:80;",
                f"    server_name {legacy_cpanel_host};",
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

            # Legacy HTTP cpanel.<domain> redirect -> fpanel.<domain>
            lines += [
                "# Legacy cpanel.<domain> HTTP redirect -> fpanel.<domain>",
                "server {",
                "    listen 80;",
                "    listen [::]:80;",
                f"    server_name {legacy_cpanel_host};",
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

    def _webmail_locations(self, *, hostname: str | None = None) -> list[str]:
        """Customer convenience redirects on the primary website vhost:
        /fpanel & /cpanel -> 302 to https://fpanel.<domain>/
        /webmail -> 302 to https://webmail.<domain>/
        /mail -> 302 to https://webmail.<domain>/
        """
        from app.services.platform.panel_access import control_panel_hostname, webmail_hostname

        raw_host = (hostname or "").strip().lower()
        if raw_host.startswith("www."):
            raw_host = raw_host[4:]
        fpanel_url = f"https://{control_panel_hostname(raw_host)}/" if raw_host else "https://fpanel.$host/"
        webmail_url = f"https://{webmail_hostname(raw_host)}/" if raw_host else "https://webmail.$host/"

        return [
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
            "    location = /webmail {",
            f"        return 302 {webmail_url};",
            "    }",
            "    location = /webmail/ {",
            f"        return 302 {webmail_url};",
            "    }",
            "    location = /mail {",
            f"        return 302 {webmail_url};",
            "    }",
            "    location = /mail/ {",
            f"        return 302 {webmail_url};",
            "    }",
        ]

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
        # Per-app proxy locations written by application_runtime (/apps/<slug>/).
        host_apps = Path(f"/etc/nginx/ifnotus-apps/hosts/{hostname}")
        if host_apps.is_dir():
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
                "    }",
            ]
            # map for upgrade may not exist — keep Connection close-safe alternative
            # Use simpler connection header if map missing
            return [
                line.replace("proxy_set_header Connection $connection_upgrade;", 'proxy_set_header Connection "";')
                if "connection_upgrade" in line
                else line
                for line in lines
            ]

        if php_index.is_file():
            lines += [
                "    location / {",
                "        try_files $uri $uri/ /index.php?$args;",
                "    }",
            ]
        else:
            lines += [
                "    location / {",
                "        try_files $uri $uri/ /index.html;",
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
        if base.name == "public":
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

    def inject_webmail_into_config(self, conf: str) -> str:
        """Ensure /mail and /cpanel exist in every server block before location /."""
        webmail = (self._settings.webmail_url or "https://mail.ifnotus.space").rstrip("/")
        portal = (self._settings.customer_portal_url or "https://ifnotus.space").rstrip("/")
        has_mail = f"return 302 {webmail}/" in conf and "location = /mail" in conf
        has_cpanel = "location = /cpanel" in conf and f"{portal}/go/hosting?host=$host" in conf
        has_stale_cpanel_proxy = "location = /cpanel" in conf and "panel-redirect" in conf
        # Count how many server blocks still miss /cpanel ahead of their location /
        server_chunks = re.split(r"(?=^\s*server\s*\{)", conf, flags=re.MULTILINE)
        needs_https_fix = False
        for chunk in server_chunks:
            if "listen 443" not in chunk and "listen [::]:443" not in chunk:
                continue
            if "location = /cpanel" not in chunk or f"{portal}/go/hosting?host=$host" not in chunk:
                needs_https_fix = True
                break
        if has_mail and has_cpanel and not needs_https_fix and not has_stale_cpanel_proxy:
            return conf
        # Strip old embedded Roundcube /mail blocks and stale /cpanel blocks.
        cleaned = re.sub(
            r"\n?[ \t]*# Roundcube webmail[^\n]*\n"
            r"(?:[ \t]*location = /mail \{[\s\S]*?\n[ \t]*\}\n)?"
            r"(?:[ \t]*location ~ \^/mail/[^\n]+\n(?:[ \t]+[^\n]+\n)*?[ \t]*\}\n)?"
            r"(?:[ \t]*location = /mail/ \{[\s\S]*?\n[ \t]*\}\n)?"
            r"(?:[ \t]*location /mail/ \{[\s\S]*?\n[ \t]*\}\n)?",
            "\n",
            conf,
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
        block_lines = self._webmail_locations()
        block = "\n".join(block_lines) + "\n"
        # Insert before every catch-all location / so HTTPS proxy vhosts get /cpanel too.
        updated = re.sub(
            r"(^[ \t]*location / \{)",
            block + r"\1",
            cleaned,
            flags=re.MULTILINE,
        )
        if updated != cleaned:
            return updated
        if "ssl_certificate_key" in cleaned:
            updated = re.sub(
                r"(ssl_certificate_key\s+[^;]+;\s*\n(?:[ \t]*include\s+[^;]+;\s*\n)*(?:[ \t]*ssl_dhparam\s+[^;]+;\s*\n)?)",
                r"\1" + block,
                cleaned,
                count=1,
            )
            if updated != cleaned:
                return updated
        return cleaned if cleaned != conf else conf

    async def ensure_webmail_on_all_sites(self) -> OperationResult:
        """Add /mail webmail to every nginx site that does not already have it."""
        if not self._available.is_dir():
            return OperationResult(success=False, message="nginx sites-available missing")
        skip_hosts = {
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
        root = document_root or f"/var/www/{hostname}"
        if create_docroot and not redirect_url:
            try:
                self.ensure_document_root(root, hostname=hostname)
            except OSError as exc:
                raise AppException(f"Could not create document root: {exc}", code="docroot_failed") from exc

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

        # Never overwrite an unmanaged / host nginx site (core platform configs).
        if available.exists():
            try:
                existing = available.read_text(encoding="utf-8", errors="replace")
                unmanaged = MANAGED_MARKER not in existing and "managed-by-ifnotus" not in existing
                if unmanaged and not force_takeover:
                    raise AppException(
                        f"Nginx site {hostname} exists and is not IFNOTUS-managed — refusing to overwrite.",
                        code="nginx_unmanaged",
                    )
                if unmanaged and force_takeover:
                    import shutil

                    bak = available.with_suffix(".bak-ifnotus-pre-takeover")
                    try:
                        shutil.copy2(available, bak)
                    except OSError:
                        pass
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

