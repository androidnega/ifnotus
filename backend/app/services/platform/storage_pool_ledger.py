"""Transactional shared tenant storage pool ledger (140 GB).

Counts ACTIVE shared CustomerEnvironment storage entitlements against
HostResourcePolicy.tenant_storage_pool_gb. VPS/VDS/dedicated products are
excluded. Domain count does not multiply allocation.

Uses SELECT … FOR UPDATE on a singleton ledger row for race-safe reservations.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppException, ValidationError
from app.core.logging import get_logger
from app.models.platform import CustomerEnvironment, HostingPlan, Subscription
from app.services.platform.resource_policy import (
    HostResourcePolicy,
    PlanCompatibility,
    PlanResourceClass,
    PlanView,
    classify_plan_resource_class,
    default_host_resource_policy,
    evaluate_plan_compatibility,
)

logger = get_logger(__name__)

LEDGER_KEY = "shared_tenant_storage_pool_v1"


@dataclass(frozen=True)
class StoragePoolSnapshot:
    pool_total_gb: float
    committed_gb: float
    remaining_gb: float
    percent_committed: float
    core_reserve_gb: float
    active_shared_envs: int
    excluded_dedicated_envs: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "pool_total_gb": self.pool_total_gb,
            "committed_gb": self.committed_gb,
            "remaining_gb": self.remaining_gb,
            "percent_committed": self.percent_committed,
            "core_reserve_gb": self.core_reserve_gb,
            "active_shared_envs": self.active_shared_envs,
            "excluded_dedicated_envs": self.excluded_dedicated_envs,
        }


def _plan_view_from_orm(plan: HostingPlan | None) -> PlanView | None:
    if plan is None:
        return None
    return PlanView(
        slug=str(plan.slug or ""),
        name=str(plan.name or ""),
        price_monthly=float(plan.price_monthly or 0),
        ram_gb=float(plan.ram_gb or 0),
        storage_gb=float(plan.storage_gb or 0),
        features=dict(plan.features or {}) if isinstance(plan.features, dict) else {},
    )


def is_shared_pool_consumer(plan: PlanView | None, *, policy: HostResourcePolicy) -> bool:
    if plan is None:
        return True  # conservative: unknown counts toward pool
    cls = classify_plan_resource_class(plan, policy=policy)
    if cls in {PlanResourceClass.VPS_STYLE, PlanResourceClass.VDS_STYLE}:
        return False
    compat = evaluate_plan_compatibility(plan, policy=policy)
    if compat == PlanCompatibility.DEDICATED_POLICY_REQUIRED:
        return False
    return True


def entitlement_gb_for_env(
    env: CustomerEnvironment,
    plan: HostingPlan | None,
) -> float:
    """Authoritative per-environment storage allocation (not × domains)."""
    if env.storage_limit_gb is not None:
        return float(env.storage_limit_gb)
    if plan is not None and plan.storage_gb is not None:
        return float(plan.storage_gb)
    return 0.0


class StoragePoolLedgerService:
    def __init__(
        self,
        session: AsyncSession,
        *,
        policy: HostResourcePolicy | None = None,
    ) -> None:
        self._session = session
        self.policy = policy or default_host_resource_policy()

    async def ensure_ledger_row(self) -> None:
        await self._session.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS ifnotus_resource_ledgers (
                    key TEXT PRIMARY KEY,
                    committed_gb NUMERIC(12, 3) NOT NULL DEFAULT 0,
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                    meta JSONB NOT NULL DEFAULT '{}'::jsonb
                )
                """
            )
        )
        await self._session.execute(
            text(
                """
                INSERT INTO ifnotus_resource_ledgers (key, committed_gb)
                VALUES (:k, 0)
                ON CONFLICT (key) DO NOTHING
                """
            ),
            {"k": LEDGER_KEY},
        )

    async def recompute_committed_gb(self) -> StoragePoolSnapshot:
        """Sum active shared env entitlements (authoritative for reporting)."""
        rows = (
            await self._session.execute(
                select(CustomerEnvironment, Subscription, HostingPlan)
                .outerjoin(Subscription, Subscription.id == CustomerEnvironment.subscription_id)
                .outerjoin(HostingPlan, HostingPlan.id == Subscription.plan_id)
                .where(CustomerEnvironment.status.notin_(("terminated", "terminating")))
            )
        ).all()
        committed = 0.0
        shared_n = 0
        dedicated_n = 0
        for env, _sub, plan in rows:
            pv = _plan_view_from_orm(plan)
            if not is_shared_pool_consumer(pv, policy=self.policy):
                dedicated_n += 1
                continue
            # Suspension keeps entitlement while data remains.
            if env.status in {"active", "suspended", "provisioning", "pending"}:
                committed += entitlement_gb_for_env(env, plan)
                shared_n += 1
        total = float(self.policy.tenant_storage_pool_gb)
        remaining = max(0.0, total - committed)
        pct = round(100.0 * committed / total, 2) if total else 0.0
        return StoragePoolSnapshot(
            pool_total_gb=total,
            committed_gb=round(committed, 3),
            remaining_gb=round(remaining, 3),
            percent_committed=pct,
            core_reserve_gb=float(self.policy.core_storage_reserve_gb),
            active_shared_envs=shared_n,
            excluded_dedicated_envs=dedicated_n,
        )

    async def reserve(
        self,
        *,
        requested_gb: float,
        plan: PlanView | None,
        environment_id: UUID | str | None = None,
    ) -> StoragePoolSnapshot:
        """Atomically reserve positive delta for provisioning/upgrade.

        Raises ValidationError if pool would exceed 140 GB.
        """
        if requested_gb <= 0:
            return await self.recompute_committed_gb()
        if not is_shared_pool_consumer(plan, policy=self.policy):
            raise AppException(
                "Dedicated VPS/VDS storage requires dedicated capacity — "
                "not drawn from the shared 140 GB pool.",
                code="dedicated_storage_required",
            )
        await self.ensure_ledger_row()
        # Lock ledger row then recompute from live envs (authoritative).
        await self._session.execute(
            text("SELECT key FROM ifnotus_resource_ledgers WHERE key=:k FOR UPDATE"),
            {"k": LEDGER_KEY},
        )
        snap = await self.recompute_committed_gb()
        if snap.committed_gb + float(requested_gb) > snap.pool_total_gb + 1e-9:
            raise ValidationError(
                f"Shared storage pool exhausted: "
                f"{snap.committed_gb:.1f}+{requested_gb:.1f} > {snap.pool_total_gb:.0f} GB.",
                code="storage_pool_exhausted",
            )
        await self._session.execute(
            text(
                """
                UPDATE ifnotus_resource_ledgers
                SET committed_gb = :c, updated_at = now(),
                    meta = jsonb_set(COALESCE(meta, '{}'::jsonb), '{last_reserve}',
                           to_jsonb(CAST(:m AS text)), true)
                WHERE key = :k
                """
            ),
            {
                "c": Decimal(str(round(snap.committed_gb + float(requested_gb), 3))),
                "k": LEDGER_KEY,
                "m": f"{environment_id}:{requested_gb}:{datetime.now(UTC).isoformat()}",
            },
        )
        logger.info(
            "storage_pool_reserve",
            requested_gb=requested_gb,
            committed_after=snap.committed_gb + float(requested_gb),
            environment_id=str(environment_id) if environment_id else None,
        )
        return StoragePoolSnapshot(
            pool_total_gb=snap.pool_total_gb,
            committed_gb=round(snap.committed_gb + float(requested_gb), 3),
            remaining_gb=round(snap.pool_total_gb - snap.committed_gb - float(requested_gb), 3),
            percent_committed=round(
                100.0 * (snap.committed_gb + float(requested_gb)) / snap.pool_total_gb, 2
            ),
            core_reserve_gb=snap.core_reserve_gb,
            active_shared_envs=snap.active_shared_envs,
            excluded_dedicated_envs=snap.excluded_dedicated_envs,
        )

    async def assert_can_allocate(self, *, requested_gb: float, plan: PlanView | None) -> None:
        if requested_gb <= 0:
            return
        if not is_shared_pool_consumer(plan, policy=self.policy):
            raise AppException(
                "Dedicated VPS/VDS storage requires dedicated capacity.",
                code="dedicated_storage_required",
            )
        snap = await self.recompute_committed_gb()
        if snap.committed_gb + float(requested_gb) > snap.pool_total_gb + 1e-9:
            raise ValidationError(
                f"Shared storage pool exhausted: "
                f"{snap.committed_gb:.1f}+{requested_gb:.1f} > {snap.pool_total_gb:.0f} GB.",
                code="storage_pool_exhausted",
            )
