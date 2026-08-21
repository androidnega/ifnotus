"""Entitlement Model v2 — effective plan capabilities + subscription snapshots."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.platform import HostingPlan, Subscription, SubscriptionEntitlementSnapshot
from app.services.platform.plan_matrix import capabilities_for, features_for


def effective_entitlements(plan: HostingPlan | None) -> dict[str, Any]:
    """Authoritative entitlements: matrix features plus numeric plan limits."""
    feats = features_for(plan)
    caps = capabilities_for(plan)
    limits = {
        "cpu_cores": float(plan.cpu_cores) if plan is not None else 0.0,
        "ram_gb": float(plan.ram_gb) if plan is not None else 0.0,
        "storage_gb": int(plan.storage_gb) if plan is not None else 0,
        "ai_credits": int(plan.ai_credits or 0) if plan is not None else 0,
        "bandwidth_tb": float(plan.bandwidth_tb) if plan is not None else 0.0,
    }
    return {
        "plan_id": str(plan.id) if plan is not None else None,
        "plan_slug": getattr(plan, "slug", None),
        "plan_version": int(getattr(plan, "version", 1) or 1) if plan is not None else 1,
        "features": feats,
        "capabilities": caps,
        "limits": limits,
    }


async def snapshot_for_subscription(
    session: AsyncSession,
    subscription: Subscription,
    plan: HostingPlan,
) -> SubscriptionEntitlementSnapshot:
    """Persist an entitlement snapshot for a newly activated (or changed) subscription."""
    entitlements = effective_entitlements(plan)
    row = SubscriptionEntitlementSnapshot(
        subscription_id=subscription.id,
        plan_version=int(getattr(plan, "version", 1) or 1),
        entitlements_json=entitlements,
        created_at=datetime.now(UTC),
    )
    session.add(row)
    await session.flush()
    return row


async def get_snapshot(
    session: AsyncSession,
    subscription_id: UUID,
) -> SubscriptionEntitlementSnapshot | dict[str, Any]:
    """Return the latest snapshot, or build entitlements from the current plan."""
    result = await session.execute(
        select(SubscriptionEntitlementSnapshot)
        .where(SubscriptionEntitlementSnapshot.subscription_id == subscription_id)
        .order_by(SubscriptionEntitlementSnapshot.created_at.desc())
        .limit(1)
    )
    snap = result.scalar_one_or_none()
    if snap is not None:
        return snap

    sub = await session.get(Subscription, subscription_id)
    if sub is None:
        return effective_entitlements(None)
    plan = await session.get(HostingPlan, sub.plan_id)
    return effective_entitlements(plan)
