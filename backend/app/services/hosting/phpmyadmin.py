"""phpMyAdmin single sign-on for MySQL databases (shared-hosting style)."""

from __future__ import annotations

import json
import os
import secrets
import time
from pathlib import Path
from typing import Any

from app.core.config import Settings
from app.core.exceptions import AppException, ValidationError

TOKEN_DIR = Path("/run/ifnotus-pma")
TOKEN_TTL_SECONDS = 120
DEFAULT_PUBLIC_BASE = "https://ifnotus.space/phpmyadmin"


class PhpMyAdminService:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    @property
    def public_base(self) -> str:
        base = (getattr(self._settings, "phpmyadmin_url", None) or DEFAULT_PUBLIC_BASE).rstrip("/")
        return base

    def issue_signon(
        self,
        *,
        username: str,
        password: str,
        database: str | None = None,
        host: str = "localhost",
        port: int = 3306,
    ) -> dict[str, str]:
        user = (username or "").strip()
        if not user:
            raise ValidationError("MySQL username is missing.", code="pma_no_user")
        if password is None:
            raise ValidationError("MySQL password is missing.", code="pma_no_password")

        host_norm = (host or "localhost").strip()
        if host_norm in {"127.0.0.1", "::1"}:
            host_norm = "localhost"

        TOKEN_DIR.mkdir(parents=True, exist_ok=True)
        try:
            os.chmod(TOKEN_DIR, 0o770)
        except OSError:
            pass

        token = secrets.token_hex(24)
        path = TOKEN_DIR / f"{token}.json"
        payload: dict[str, Any] = {
            "username": user,
            "password": password,
            "host": host_norm,
            "port": int(port or 3306),
            "database": (database or "").strip() or None,
            "exp": int(time.time()) + TOKEN_TTL_SECONDS,
        }
        path.write_text(json.dumps(payload), encoding="utf-8")
        try:
            os.chmod(path, 0o640)
            # php-fpm usually runs as www-data
            import grp
            import pwd

            uid = pwd.getpwnam("www-data").pw_uid
            gid = grp.getgrnam("www-data").gr_gid
            os.chown(path, uid, gid)
            os.chown(TOKEN_DIR, uid, gid)
        except Exception:  # noqa: BLE001
            # Still readable by root API; php may fail if ownership wrong — surface later.
            pass

        url = f"{self.public_base}/ifnotus-signon.php?token={token}"
        return {"url": url, "token": token, "expires_in": str(TOKEN_TTL_SECONDS)}

    @staticmethod
    def assert_mysql_engine(engine: str | None) -> None:
        eng = (engine or "").strip().lower()
        if eng not in {"mysql", "mariadb"}:
            raise AppException(
                "phpMyAdmin is only for MySQL databases. Use SQL studio for PostgreSQL.",
                code="pma_mysql_only",
            )
