"""RFC 6238 TOTP helpers (no extra dependency)."""

from __future__ import annotations

import base64
import hashlib
import hmac
import os
import struct
import time


def new_secret() -> str:
    return base64.b32encode(os.urandom(20)).decode("ascii").rstrip("=")


def provisioning_uri(*, secret: str, email: str, issuer: str = "IFNOTUS") -> str:
    label = f"{issuer}:{email}".replace(" ", "%20")
    return (
        f"otpauth://totp/{label}?secret={secret}&issuer={issuer}&algorithm=SHA1&digits=6&period=30"
    )


def _hotp(secret: str, counter: int) -> str:
    padded = secret + "=" * ((8 - len(secret) % 8) % 8)
    key = base64.b32decode(padded, casefold=True)
    msg = struct.pack(">Q", counter)
    digest = hmac.new(key, msg, hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    code = struct.unpack(">I", digest[offset : offset + 4])[0] & 0x7FFFFFFF
    return f"{code % 1_000_000:06d}"


def generate_code(secret: str) -> str:
    """Generate the current 6-digit TOTP code for a secret."""
    counter = int(time.time()) // 30
    return _hotp(secret, counter)


def verify_code(secret: str, code: str, *, window: int = 1) -> bool:
    raw = "".join(ch for ch in (code or "") if ch.isdigit())
    if len(raw) != 6 or not secret:
        return False
    counter = int(time.time()) // 30
    for delta in range(-window, window + 1):
        if hmac.compare_digest(_hotp(secret, counter + delta), raw):
            return True
    return False


def generate_backup_codes(count: int = 8) -> list[str]:
    """Generate cryptographically secure 10-character alphanumeric backup recovery codes."""
    import secrets

    alphabet = "abcdefghjkmnpqrstuvwxyz23456789"  # Unambiguous characters
    return [
        "".join(secrets.choice(alphabet) for _ in range(5))
        + "-"
        + "".join(secrets.choice(alphabet) for _ in range(5))
        for _ in range(count)
    ]
