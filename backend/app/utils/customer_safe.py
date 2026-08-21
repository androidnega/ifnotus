"""Scrub host filesystem paths from customer-facing strings."""

from __future__ import annotations

import re

# Absolute tenant / host layouts that must never appear in customer UI or APIs.
_HOST_PATH_RE = re.compile(
    r"(?:/srv/apps/ifnotus-customers|/var/www/ifnotus-customers|"
    r"/home/[^/\s]+/ifnotus-customers|/srv/apps/ifnotus|"
    r"/etc/nginx|/etc/letsencrypt|/var/lib|/var/log|/usr/share|/usr/lib|"
    r"/opt/ifnotus|/root)"
    r"/[^\s`\"'<>)\]]*",
    re.IGNORECASE,
)
_PREFIX_RE = re.compile(
    r"/srv/apps/ifnotus-customers\b|/var/www/ifnotus-customers\b|"
    r"/srv/apps/ifnotus\b|ifnotus-customers/[0-9a-f-]{8,}",
    re.IGNORECASE,
)
# Never rewrite file bodies — customers may legitimately mention absolute paths in code.
_SKIP_CONTENT_KEYS = frozenset(
    {
        "content",
        "body",
        "file_content",
        "html",
        "source",
        "code",
        "chunk",
        "raw",
        "diff",
        "data_b64",
        "bytes",
    }
)


def scrub_host_paths(value: str | None, *, placeholder: str = "site root") -> str:
    """Replace absolute host paths with a safe customer-facing label."""
    if not value:
        return ""
    text = str(value)

    def _rel(match: re.Match[str]) -> str:
        abs_path = match.group(0).rstrip("/")
        parts = abs_path.split("/ifnotus-customers/", 1)
        if len(parts) == 2:
            rest = parts[1]
            segs = rest.split("/", 1)
            if len(segs) == 2 and segs[1]:
                # Drop opaque tenant id segment → relative site path.
                return segs[1]
            return placeholder
        if abs_path.endswith("ifnotus-customers") or "/ifnotus-customers" in abs_path:
            return placeholder
        return placeholder

    out = _HOST_PATH_RE.sub(_rel, text)
    out = _PREFIX_RE.sub(placeholder, out)
    return out


def scrub_obj(data: object, *, skip_content: bool = True) -> object:
    """Recursively scrub host paths in JSON-like structures (not file bodies)."""
    if isinstance(data, str):
        return scrub_host_paths(data)
    if isinstance(data, list):
        return [scrub_obj(item, skip_content=skip_content) for item in data]
    if isinstance(data, dict):
        out: dict = {}
        for key, value in data.items():
            if skip_content and str(key).lower() in _SKIP_CONTENT_KEYS and isinstance(value, str):
                out[key] = value
            else:
                out[key] = scrub_obj(value, skip_content=skip_content)
        return out
    return data
