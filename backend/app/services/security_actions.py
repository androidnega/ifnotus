"""Map HTTP requests to auditable action keys and detect CLI vs web clients."""

from __future__ import annotations

import re

from fastapi import Request

# Sensitive / mutating actions admins can kill-switch.
KNOWN_BLOCKABLE_ACTIONS: list[dict[str, str]] = [
    {"key": "terminal.execute", "label": "Terminal command execution"},
    {"key": "databases.write", "label": "Database write / drop / restore"},
    {"key": "files.write", "label": "File create / edit / delete / upload"},
    {"key": "files.read", "label": "File browse / download"},
    {"key": "domains.write", "label": "Domain create / update / delete"},
    {"key": "ssl.write", "label": "SSL issue / renew"},
    {"key": "mail.write", "label": "Mailbox / alias create / update"},
    {"key": "operations.write", "label": "Operations / service control"},
    {"key": "apps.write", "label": "Application deploy / restart"},
    {"key": "ai.execute", "label": "AI agent tool execution"},
    {"key": "security.admin", "label": "Security firewall / unlock changes"},
]

_PATH_RULES: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"^/api/v1/terminal(?:/|$)"), "terminal.execute"),
    (re.compile(r"^/api/v1/databases"), "databases.write"),
    (re.compile(r"^/api/v1/files"), "files.write"),
    (re.compile(r"^/api/v1/domains"), "domains.write"),
    (re.compile(r"^/api/v1/ssl"), "ssl.write"),
    (re.compile(r"^/api/v1/mail"), "mail.write"),
    (re.compile(r"^/api/v1/operations"), "operations.write"),
    (re.compile(r"^/api/v1/applications"), "apps.write"),
    (re.compile(r"^/api/v1/server"), "operations.write"),
    (re.compile(r"^/api/v1/ai"), "ai.execute"),
    (re.compile(r"^/api/v1/security"), "security.admin"),
]

# High-signal GET paths still audited for transparency (no health/polling spam).
# List/overview pages are excluded — auditing them rewrote rows every refresh and
# slowed the panel under load.
_AUDIT_GET_PREFIXES = (
    "/api/v1/files",
    "/api/v1/mail",
)

_SKIP_AUDIT_PREFIXES = (
    "/api/v1/health",
    "/api/v1/auth/me",
    "/api/v1/auth/refresh",
    "/api/v1/monitoring",
    "/api/v1/dashboard",
    "/api/v1/alerts",
)

# Reading the audit trail is not itself an auditable action. Logging these made
# every visit to the security page repopulate the tables just cleared there.
_AUDIT_VIEW_PREFIXES = (
    "/api/v1/security/attempts",
    "/api/v1/security/actions",
    "/api/v1/security/action-logs",
    "/api/v1/security/blacklist",
    "/api/v1/security/firewall",
    "/api/v1/security/blocked-actions",
    "/api/v1/terminal/audit",
)


def detect_source(user_agent: str | None) -> str:
    ua = (user_agent or "").lower()
    if any(token in ua for token in ("curl/", "wget/", "httpie/", "python-requests", "go-http", "ifnotus-cli")):
        return "cli"
    if "ssh" in ua:
        return "ssh"
    return "web"


def resolve_action_key(method: str, path: str) -> str | None:
    upper = method.upper()
    for pattern, key in _PATH_RULES:
        if pattern.search(path):
            if upper in {"GET", "HEAD"} and key.endswith(".write"):
                # Map reads of write-scoped APIs to a read key when present.
                read_key = key.replace(".write", ".read")
                if any(a["key"] == read_key for a in KNOWN_BLOCKABLE_ACTIONS):
                    return read_key
                return f"http.{method.lower()}"
            return key
    return f"http.{method.lower()}"


def should_audit(method: str, path: str) -> bool:
    upper = method.upper()
    if any(path.startswith(prefix) for prefix in _SKIP_AUDIT_PREFIXES):
        return False
    if path.startswith("/api/v1/auth/login") or path.startswith("/api/v1/auth/probe"):
        return False
    if not path.startswith("/api/"):
        return False
    # The clear endpoint writes its own audit row after deleting, so skipping it
    # here keeps a single, readable marker instead of a raw request line.
    if path.startswith("/api/v1/security/logs/clear"):
        return False
    if upper in {"GET", "HEAD", "OPTIONS"}:
        if any(path.startswith(prefix) for prefix in _AUDIT_VIEW_PREFIXES):
            return False
        return any(path.startswith(prefix) for prefix in _AUDIT_GET_PREFIXES)
    return True

def client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    real_ip = request.headers.get("x-real-ip")
    if real_ip:
        return real_ip.strip()
    if request.client and request.client.host:
        return request.client.host
    return "unknown"
