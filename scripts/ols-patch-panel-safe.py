#!/usr/bin/env python3
"""Patch OLSPanel Ubuntu panel.sh to avoid destroying MySQL/BIND/mail on a busy VPS."""
from __future__ import annotations

import re
from pathlib import Path

SRC = Path("/tmp/panel.sh")
DST = Path("/tmp/panel-safe.sh")

STUBS = {
    "install_mariadb": """install_mariadb() {
    echo "[SAFE] Skipping MariaDB install — MySQL already present."
    return 0
}
""",
    "install_powerdns_and_mysql_backend": """install_powerdns_and_mysql_backend() {
    echo "[SAFE] Skipping PowerDNS — BIND9 named already authoritative."
    return 0
}
""",
    "install_mail_and_ftp_server": """install_mail_and_ftp_server() {
    echo "[SAFE] Skipping Postfix/Dovecot reinstall — keeping existing mail stack."
    apt-get install -y pure-ftpd-mysql 2>/dev/null || true
    return 0
}
""",
}

SAFE_COPY = """
copy_files_and_replace_password_safe() {
    local SOURCE_DIR="$1"
    local TARGET_DIR="$2"
    local NEW_PASSWORD="$3"
    echo "[SAFE] Selective /etc copy — excluding postfix dovecot bind powerdns"
    mkdir -p /tmp/ols-etc-stage
    rm -rf /tmp/ols-etc-stage
    mkdir -p /tmp/ols-etc-stage
    cp -a "$SOURCE_DIR"/. /tmp/ols-etc-stage/ || true
    rm -rf /tmp/ols-etc-stage/postfix /tmp/ols-etc-stage/dovecot /tmp/ols-etc-stage/bind \\
           /tmp/ols-etc-stage/powerdns /tmp/ols-etc-stage/resolv.conf /tmp/ols-etc-stage/hosts 2>/dev/null || true
    copy_files_and_replace_password /tmp/ols-etc-stage "$TARGET_DIR" "$NEW_PASSWORD"
}
"""


def replace_function(text: str, name: str, body: str) -> str:
    lines = text.splitlines(True)
    out: list[str] = []
    i = 0
    while i < len(lines):
        if lines[i].startswith(f"{name}()"):
            out.append(body if body.endswith("\n") else body + "\n")
            i += 1
            while i < len(lines) and not re.match(r"^[a-zA-Z_][a-zA-Z0-9_]*\(\)", lines[i]):
                i += 1
            continue
        out.append(lines[i])
        i += 1
    return "".join(out)


def main() -> None:
    text = SRC.read_text(errors="replace")
    for name, body in STUBS.items():
        text = replace_function(text, name, body)

    text = text.replace(
        "sudo systemctl stop systemd-resolved >/dev/null 2>&1",
        'echo "[SAFE] keep systemd-resolved as-is"',
    )
    text = text.replace(
        "sudo systemctl disable systemd-resolved >/dev/null 2>&1",
        "true",
    )
    text = text.replace(
        "sudo systemctl restart pdns",
        'echo "[SAFE] skip pdns restart"; systemctl is-active named || true',
    )
    text = text.replace(
        'copy_files_and_replace_password "/root/item/move/etc" "/etc"',
        'copy_files_and_replace_password_safe "/root/item/move/etc" "/etc"',
    )
    if "copy_files_and_replace_password_safe()" not in text:
        text = text.replace("generate_mariadb_password()", SAFE_COPY + "\ngenerate_mariadb_password()", 1)

    DST.write_text(text)
    print(f"Wrote {DST} bytes={DST.stat().st_size}")


if __name__ == "__main__":
    main()
