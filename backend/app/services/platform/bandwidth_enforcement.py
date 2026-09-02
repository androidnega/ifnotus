"""Nginx-edge SOFT_BLOCK for bandwidth limits — never touches customer site files.

At 100%: public hosted content is replaced with a clean limit page via a generated
nginx include. Portal / panel / mail / API paths stay reachable (longer ^~ / exact
locations win over the soft-block catch-all).
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Any

from app.core.logging import get_logger

logger = get_logger(__name__)

EVENT_BANDWIDTH_LIMIT_REACHED = "BANDWIDTH_LIMIT_REACHED"
EVENT_BANDWIDTH_LIMIT_CLEARED = "BANDWIDTH_LIMIT_CLEARED"

BLOCKS_DIR = Path("/etc/nginx/ifnotus-bandwidth/blocks")
PAGES_DIR = Path("/var/lib/ifnotus/bandwidth-pages")
SOFT_BLOCK_HTML = "soft-block.html"
SOFT_BLOCK_CONF_NAME = "00-bandwidth-soft-block.conf"
APPS_HOSTS_DIR = Path("/etc/nginx/ifnotus-apps/hosts")

SOFT_BLOCK_PAGE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>Bandwidth limit reached</title>
<style>
  body{margin:0;min-height:100vh;display:flex;align-items:center;justify-content:center;
       font-family:ui-sans-serif,system-ui,sans-serif;background:#0f1419;color:#e8eef4;}
  main{max-width:32rem;padding:2rem;text-align:center}
  h1{font-size:1.5rem;margin:0 0 .75rem}
  p{margin:0 0 1rem;line-height:1.5;color:#a8b3bf}
  a{color:#7dd3fc}
</style>
</head>
<body>
<main>
  <h1>Bandwidth limit reached</h1>
  <p>This site has used its allotted bandwidth for the current billing period.
     The customer portal remains available so you can upgrade, add allowance, or wait for the next cycle.</p>
  <p><a href="https://ifnotus.space/login">Open customer portal</a></p>
</main>
</body>
</html>
"""

# Preferential catch-all: longer ^~ paths (/hosting/, /mail/, /api/) and exact
# panel redirects remain defined in the parent vhost and take precedence.
SOFT_BLOCK_NGINX = """# IFNOTUS bandwidth SOFT_BLOCK — generated; do not edit
location ^~ / {{
    root {pages};
    rewrite ^ /{html} break;
    default_type text/html;
    add_header Cache-Control "no-store" always;
    add_header X-IFNOTUS-Bandwidth-Limit "SOFT_BLOCK" always;
}}
"""

CLEAR_NGINX = "# IFNOTUS bandwidth — no soft-block active\n"


def ensure_pages() -> Path:
    PAGES_DIR.mkdir(parents=True, exist_ok=True)
    page = PAGES_DIR / SOFT_BLOCK_HTML
    if not page.is_file():
        page.write_text(SOFT_BLOCK_PAGE, encoding="utf-8")
    return PAGES_DIR


def soft_block_conf_path(hostname: str) -> Path:
    host = (hostname or "").strip().lower()
    if host.startswith("www."):
        host = host[4:]
    return APPS_HOSTS_DIR / host / SOFT_BLOCK_CONF_NAME


def block_stub_path(hostname: str) -> Path:
    """Dedicated always-present include path (optional dual path)."""
    host = (hostname or "").strip().lower()
    if host.startswith("www."):
        host = host[4:]
    return BLOCKS_DIR / f"{host}.conf"


def is_soft_blocked(hostname: str) -> bool:
    path = soft_block_conf_path(hostname)
    if not path.is_file():
        return False
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return False
    return "SOFT_BLOCK" in text or "bandwidth SOFT_BLOCK" in text


def apply_soft_block(hostname: str) -> dict[str, Any]:
    """Write nginx soft-block include for one public hostname."""
    host = (hostname or "").strip().lower()
    if host.startswith("www."):
        host = host[4:]
    if not host:
        return {"ok": False, "hostname": hostname, "error": "empty hostname"}
    ensure_pages()
    conf_dir = APPS_HOSTS_DIR / host
    conf_dir.mkdir(parents=True, exist_ok=True)
    conf = soft_block_conf_path(host)
    body = SOFT_BLOCK_NGINX.format(pages=str(PAGES_DIR), html=SOFT_BLOCK_HTML)
    conf.write_text(body, encoding="utf-8")
    BLOCKS_DIR.mkdir(parents=True, exist_ok=True)
    block_stub_path(host).write_text(body, encoding="utf-8")
    logger.info(
        "bandwidth_soft_block_applied",
        hostname=host,
        bandwidth_event=EVENT_BANDWIDTH_LIMIT_REACHED,
    )
    return {
        "ok": True,
        "hostname": host,
        "path": str(conf),
        "event": EVENT_BANDWIDTH_LIMIT_REACHED,
        "applied": True,
    }


def clear_soft_block(hostname: str) -> dict[str, Any]:
    host = (hostname or "").strip().lower()
    if host.startswith("www."):
        host = host[4:]
    if not host:
        return {"ok": False, "hostname": hostname, "error": "empty hostname"}
    conf = soft_block_conf_path(host)
    removed = False
    if conf.is_file():
        conf.unlink()
        removed = True
    stub = block_stub_path(host)
    BLOCKS_DIR.mkdir(parents=True, exist_ok=True)
    stub.write_text(CLEAR_NGINX, encoding="utf-8")
    # Keep host apps dir if other overlays remain; ensure placeholder so nginx glob stays valid.
    parent = conf.parent
    if parent.is_dir():
        remaining = list(parent.glob("*.conf"))
        if not remaining:
            try:
                (parent / "zz-ifnotus-placeholder.conf").write_text(
                    "# ifnotus apps / bandwidth overlay\n", encoding="utf-8"
                )
            except OSError:
                pass
    logger.info(
        "bandwidth_soft_block_cleared",
        hostname=host,
        bandwidth_event=EVENT_BANDWIDTH_LIMIT_CLEARED,
    )
    return {
        "ok": True,
        "hostname": host,
        "removed": removed,
        "event": EVENT_BANDWIDTH_LIMIT_CLEARED,
        "cleared": True,
    }


def apply_soft_block_hosts(hostnames: list[str]) -> list[dict[str, Any]]:
    return [apply_soft_block(h) for h in hostnames if h]


def clear_soft_block_hosts(hostnames: list[str]) -> list[dict[str, Any]]:
    return [clear_soft_block(h) for h in hostnames if h]


def reload_nginx(*, test: bool = True) -> dict[str, Any]:
    nginx = shutil.which("nginx") or "nginx"
    if test:
        proc = subprocess.run([nginx, "-t"], capture_output=True, text=True, check=False, timeout=30)
        if proc.returncode != 0:
            err = (proc.stderr or proc.stdout or "").strip()[-400:]
            return {"ok": False, "error": err or "nginx -t failed"}
    systemctl = shutil.which("systemctl") or "systemctl"
    proc = subprocess.run(
        [systemctl, "reload", "nginx"],
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout or "").strip()[-400:]
        return {"ok": False, "error": err or "nginx reload failed"}
    return {"ok": True}
