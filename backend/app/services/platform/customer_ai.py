"""Build a DeepSeek agent jailed to one customer environment."""

from __future__ import annotations

from pathlib import Path
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.models.platform import CustomerEnvironment
from app.services.ai.agent import DeepSeekAgentService
from app.services.hosting.files import FileManagerService


def build_customer_agent(
    settings: Settings,
    session: AsyncSession,
    *,
    customer_id: UUID,
    env: CustomerEnvironment,
    roots: list[Path],
) -> DeepSeekAgentService:
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
    return DeepSeekAgentService(
        settings,
        files,
        terminal=None,
        monitoring=None,
        mode="customer",
        allowed_roots=roots,
        env_context={
            "domain": env.domain,
            "document_root": env.document_root,
            "environment_id": str(env.id),
            "customer_id": str(customer_id),
            "storage_limit_gb": int(env.storage_limit_gb),
        },
        customer_db=customer_db,
        memory_root=memory_root,
    )
