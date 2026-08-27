"""Provider reconciliation — detect IFNOTUS vs engine drift (non-destructive)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.models.platform import CustomerEnvironment
from app.services.hosting_provider.base import HostingProviderKind
from app.services.hosting_provider.factory import get_hosting_provider


@dataclass
class ReconciliationFinding:
    environment_id: UUID
    domain: str | None
    provider: str
    ifnotus_status: str
    issues: list[str] = field(default_factory=list)
    provider_snapshot: dict[str, Any] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return not self.issues


class ProviderReconciliationService:
    """Compare IFNOTUS ACTIVE envs to provider reality. Never auto-destroys."""

    def __init__(self, settings: Settings, session: AsyncSession) -> None:
        self._settings = settings
        self._session = session

    async def check_environment(self, env: CustomerEnvironment) -> ReconciliationFinding:
        kind = (env.provider or "legacy").strip().lower()
        finding = ReconciliationFinding(
            environment_id=env.id,
            domain=env.domain,
            provider=kind,
            ifnotus_status=env.status or "",
        )
        if kind == HostingProviderKind.LEGACY.value:
            # Legacy truth is local filesystem + nginx.
            from pathlib import Path

            if env.document_root and not Path(env.document_root).exists():
                finding.issues.append("document_root_missing")
            if env.status == "active" and not env.domain:
                finding.issues.append("active_without_domain")
            finding.provider_snapshot = {"engine": "legacy-local"}
            return finding

        if kind == HostingProviderKind.ISPCONFIG.value:
            provider = get_hosting_provider(HostingProviderKind.ISPCONFIG, settings=self._settings)
            health = await provider.health()
            finding.provider_snapshot["health"] = health
            if not health.get("ok"):
                finding.issues.append("ispconfig_unreachable_or_unconfigured")
                return finding
            username = (env.provider_username or env.hosting_name or "").strip()
            if not username:
                finding.issues.append("missing_provider_username")
                return finding
            try:
                usage = await provider.get_usage(username)
                finding.provider_snapshot["usage"] = usage.raw
            except Exception as exc:  # noqa: BLE001
                finding.issues.append(f"provider_account_missing_or_error:{exc}")
            if env.status == "active" and finding.issues:
                finding.issues.append("ifnotus_active_but_provider_drift")
            return finding

        finding.issues.append(f"unsupported_provider:{kind}")
        return finding
