"""Build a DeepSeek agent jailed to one customer environment."""

from __future__ import annotations

import re
from pathlib import Path
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.models.platform import CustomerEnvironment
from app.services.ai.agent import DeepSeekAgentService
from app.services.hosting.files import FileManagerService


def _guess_public_domain(env: CustomerEnvironment) -> str:
    """Best-effort public hostname for live HTTP probes."""
    domain = (env.domain or "").strip().lower()
    root = (env.document_root or "").strip()
    if root:
        for rel in ("config.php", ".env", "wp-config.php", "public/config.php", "public/.env"):
            path = Path(root) / rel
            if not path.is_file():
                continue
            try:
                text = path.read_text(encoding="utf-8", errors="replace")[:8000]
            except OSError:
                continue
            for pattern in (
                r"SITE_URL['\"]?\s*,\s*'https?://([^/']+)",
                r"define\(\s*'SITE_URL'\s*,\s*'https?://([^/']+)",
                r"APP_URL\s*=\s*https?://([^\s/]+)",
                r"WP_HOME['\"]?\s*,\s*'https?://([^/']+)",
            ):
                m = re.search(pattern, text, re.I)
                if m:
                    host = m.group(1).strip().lower()
                    if host and host not in {"localhost", "127.0.0.1"}:
                        return host
    return domain


def build_customer_agent(
    settings: Settings,
    session: AsyncSession,
    *,
    customer_id: UUID,
    env: CustomerEnvironment,
    roots: list[Path],
) -> DeepSeekAgentService:
    del session  # reserved for future async domain lookups
    files = FileManagerService(settings, only_roots=roots, storage_limit_gb=env.storage_limit_gb)
    customer_db = None
    if env.db_registry_id:
        customer_db = {
            "id": str(env.db_registry_id),
            "engine": env.db_engine,
            "name": env.db_name,
            "host": env.db_host,
            "port": env.db_port,
            "username": env.db_username,
        }
    memory_root = str(
        Path(settings.ai_memory_path).resolve() / "customers" / str(customer_id) / str(env.id)
    )
    public_domain = _guess_public_domain(env)
    return DeepSeekAgentService(
        settings,
        files,
        terminal=None,
        monitoring=None,
        mode="customer",
        allowed_roots=roots,
        env_context={
            "domain": public_domain or (env.domain or ""),
            "document_root": env.document_root,
            "environment_id": str(env.id),
            "customer_id": str(customer_id),
            "storage_limit_gb": int(env.storage_limit_gb),
        },
        customer_db=customer_db,
        memory_root=memory_root,
    )
