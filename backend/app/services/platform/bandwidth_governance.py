"""Wire bandwidth accounting → SOFT_BLOCK nginx enforcement + restores."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.logging import get_logger
from app.models.platform import (
    CustomerDomain,
    CustomerEnvironment,
    HostingPlan,
    PlatformAuditLog,
    Subscription,
)
from app.services.platform.bandwidth_accounting import (
    ACTION_HIGH_WARN,
    ACTION_NONE,
    ACTION_SOFT_BLOCK,
    ACTION_WARN,
    BandwidthStore,
    apply_plan_limit,
    checkpoint_id_from_ingest,
    classify_bandwidth_action,
    ensure_bandwidth_log_snippet,
    grant_additional_allowance,
    ingest_bandwidth_log_deltas,
    merge_usage_delta,
    should_enforce_soft_block,
    tb_to_bytes,
)
from app.services.platform.bandwidth_enforcement import (
    EVENT_BANDWIDTH_LIMIT_CLEARED,
    EVENT_BANDWIDTH_LIMIT_REACHED,
    apply_soft_block_hosts,
    clear_soft_block_hosts,
    reload_nginx,
)

logger = get_logger(__name__)


def _cycle_window(sub: Subscription) -> tuple[datetime, datetime]:
    now = datetime.now(UTC)
    start = sub.renewed_at or sub.started_at or now
    if start.tzinfo is None:
        start = start.replace(tzinfo=UTC)
    end = sub.expires_at
    if end is None:
        end = start + timedelta(days=30)
    elif end.tzinfo is None:
        end = end.replace(tzinfo=UTC)
    if end <= start:
        end = start + timedelta(days=30)
    return start, end


def _limit_from_plan(plan: HostingPlan | None) -> int | None:
    if plan is None:
        return None
    tb = float(getattr(plan, "bandwidth_tb", None) or 0)
    # Explicit 0 / negative → UNLIMITED
    if tb <= 0:
        return None
    return tb_to_bytes(tb)


class BandwidthGovernanceService:
    def __init__(self, settings: Settings, session: AsyncSession) -> None:
        self._settings = settings
        self._session = session
        self._store = BandwidthStore()

    async def _hostnames_for_env(self, env: CustomerEnvironment) -> list[str]:
        hosts: list[str] = []
        if env.domain:
            hosts.append(str(env.domain).strip().lower())
        rows = (
            await self._session.execute(
                select(CustomerDomain.domain_name).where(
                    CustomerDomain.environment_id == env.id,
                    CustomerDomain.status.in_(["active", "pending_verification"]),
                )
            )
        ).scalars().all()
        for name in rows:
            if name:
                hosts.append(str(name).strip().lower())
        # de-dupe preserve order
        seen: set[str] = set()
        out: list[str] = []
        for h in hosts:
            if h.startswith("www."):
                h = h[4:]
            if h and h not in seen:
                seen.add(h)
                out.append(h)
        return out

    async def _host_to_env_map(self) -> dict[str, str]:
        result = await self._session.execute(
            select(CustomerEnvironment).where(
                CustomerEnvironment.status.in_(["active", "provisioned", "ready", "suspended"])
            )
        )
        envs = list(result.scalars().all())
        mapping: dict[str, str] = {}
        for env in envs:
            for host in await self._hostnames_for_env(env):
                mapping[host] = str(env.id)
                mapping[f"www.{host}"] = str(env.id)
        return mapping

    async def tick(self, *, apply: bool = True, reload: bool = True) -> dict[str, Any]:
        """Ingest log deltas, update cycles, apply/clear SOFT_BLOCK."""
        snippet = ensure_bandwidth_log_snippet()
        host_map = await self._host_to_env_map()
        raw_deltas = ingest_bandwidth_log_deltas(host_to_env=host_map)
        ck_id = checkpoint_id_from_ingest(raw_deltas) or f"tick-{datetime.now(UTC).isoformat()}"

        result = await self._session.execute(
            select(CustomerEnvironment, Subscription, HostingPlan)
            .join(Subscription, CustomerEnvironment.subscription_id == Subscription.id)
            .join(HostingPlan, Subscription.plan_id == HostingPlan.id)
            .where(CustomerEnvironment.status.in_(["active", "provisioned", "ready"]))
        )
        rows = list(result.all())

        summary: dict[str, Any] = {
            "environments": 0,
            "warned": 0,
            "high_warned": 0,
            "soft_blocked": 0,
            "cleared": 0,
            "unlimited": 0,
            "log_snippet": snippet,
            "checkpoint": ck_id,
            "events": [],
        }
        nginx_dirty = False

        for env, sub, plan in rows:
            summary["environments"] += 1
            limit = _limit_from_plan(plan)
            start, end = _cycle_window(sub)
            cycle = self._store.ensure_cycle(
                env.id, limit_bytes=limit, cycle_start=start, cycle_end=end
            )
            # Ingest shared multi-domain meter (one cycle per environment).
            delta = raw_deltas.get(str(env.id)) if isinstance(raw_deltas.get(str(env.id)), dict) else None
            if delta and ck_id:
                cycle = merge_usage_delta(
                    cycle,
                    bytes_in_delta=int(delta.get("in") or 0),
                    bytes_out_delta=int(delta.get("out") or 0),
                    checkpoint_id=ck_id,
                )
            else:
                # Still refresh limit / cycle roll without usage delta.
                cycle = apply_plan_limit(cycle, limit)

            action = classify_bandwidth_action(
                cycle.percent, action_at_100=cycle.action_at_100 or ACTION_SOFT_BLOCK
            )
            hosts = await self._hostnames_for_env(env)

            if cycle.effective_limit_bytes is None:
                summary["unlimited"] += 1
                if apply and hosts and (cycle.soft_blocked or cycle.last_event == EVENT_BANDWIDTH_LIMIT_REACHED):
                    clear_soft_block_hosts(hosts)
                    nginx_dirty = True
                    summary["cleared"] += 1
                cycle.soft_blocked = False
                cycle.last_event = None
            elif action == ACTION_WARN:
                summary["warned"] += 1
            elif action == ACTION_HIGH_WARN:
                summary["high_warned"] += 1
            elif should_enforce_soft_block(cycle) or action == ACTION_SOFT_BLOCK:
                cycle.soft_blocked = True
                if apply and hosts:
                    apply_soft_block_hosts(hosts)
                    nginx_dirty = True
                if cycle.last_event != EVENT_BANDWIDTH_LIMIT_REACHED:
                    cycle.last_event = EVENT_BANDWIDTH_LIMIT_REACHED
                    summary["events"].append(
                        {"environment_id": str(env.id), "event": EVENT_BANDWIDTH_LIMIT_REACHED}
                    )
                    self._session.add(
                        PlatformAuditLog(
                            customer_id=env.customer_id,
                            action="bandwidth.limit_reached",
                            target_type="environment",
                            target_id=str(env.id),
                            result="success",
                            metadata_json={
                                "event": EVENT_BANDWIDTH_LIMIT_REACHED,
                                "percent": cycle.percent,
                                "action": ACTION_SOFT_BLOCK,
                                "hosts": hosts,
                            },
                        )
                    )
                summary["soft_blocked"] += 1
            else:
                if cycle.soft_blocked or cycle.last_event == EVENT_BANDWIDTH_LIMIT_REACHED:
                    if apply and hosts:
                        clear_soft_block_hosts(hosts)
                        nginx_dirty = True
                        summary["cleared"] += 1
                    if cycle.last_event != EVENT_BANDWIDTH_LIMIT_CLEARED:
                        cycle.last_event = EVENT_BANDWIDTH_LIMIT_CLEARED
                        summary["events"].append(
                            {"environment_id": str(env.id), "event": EVENT_BANDWIDTH_LIMIT_CLEARED}
                        )
                cycle.soft_blocked = False

            self._store.save(cycle)
            # Mirror GB onto subscription for UI (shared meter).
            used_gb = Decimal(cycle.used_bytes) / Decimal(1000**3)
            sub.bandwidth_used_gb = used_gb.quantize(Decimal("0.01"))

        if apply and reload and nginx_dirty:
            ng = reload_nginx(test=True)
            summary["nginx_reload"] = ng
        elif not nginx_dirty:
            summary["nginx_reload"] = {"ok": True, "skipped": True}

        return summary

    async def restore_environment(
        self,
        env: CustomerEnvironment,
        *,
        new_limit_bytes: int | None = None,
        extra_bytes: int = 0,
        reason: str = "restore",
        update_limit: bool = False,
    ) -> dict[str, Any]:
        """Clear soft-block after plan upgrade, staff grant, or cycle fix."""
        cycle = self._store.load(str(env.id))
        if cycle is None:
            return {"ok": False, "error": "no_cycle"}
        if update_limit or reason in {"plan_upgrade", "plan_change", "cycle_reset"}:
            cycle = apply_plan_limit(cycle, new_limit_bytes)
        if extra_bytes > 0:
            cycle = grant_additional_allowance(cycle, extra_bytes)
        hosts = await self._hostnames_for_env(env)
        cleared = False
        if not should_enforce_soft_block(cycle):
            clear_soft_block_hosts(hosts)
            cycle.soft_blocked = False
            cycle.last_event = EVENT_BANDWIDTH_LIMIT_CLEARED
            cleared = True
            reload_nginx(test=True)
        self._store.save(cycle)
        return {
            "ok": True,
            "cleared": cleared,
            "reason": reason,
            "percent": cycle.percent,
            "hosts": hosts,
            "cycle": cycle.to_dict(),
        }

    async def grant_allowance_gb(self, env_id: UUID | str, gb: float) -> dict[str, Any]:
        env = await self._session.get(CustomerEnvironment, UUID(str(env_id)))
        if not env:
            return {"ok": False, "error": "env_not_found"}
        from app.services.platform.bandwidth_accounting import gb_to_bytes

        extra = gb_to_bytes(gb) or 0
        return await self.restore_environment(env, extra_bytes=extra, reason="staff_grant")
