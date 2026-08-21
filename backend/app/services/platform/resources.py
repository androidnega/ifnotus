"""Resource manager — capacity checks and 20% safety reserve."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.platform import CustomerEnvironment, HostingPlan, InfrastructureNode, Subscription


@dataclass
class CapacitySnapshot:
    node_id: str
    hostname: str
    cpu_total: int
    ram_total_gb: int
    storage_total_gb: int
    cpu_reserved_pct: int
    cpu_allocatable: float
    ram_allocatable: float
    storage_allocatable: int
    cpu_used: float
    ram_used: float
    storage_used: int
    cpu_free: float
    ram_free: float
    storage_free: int
    status: str


class ResourceManager:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_nodes(self) -> list[InfrastructureNode]:
        result = await self._session.execute(
            select(InfrastructureNode).order_by(InfrastructureNode.hostname)
        )
        return list(result.scalars().all())

    async def ensure_primary_node(self, settings) -> InfrastructureNode:
        """Create or refresh the start-node row so checkout can succeed."""
        hostname = getattr(settings, "infra_hostname", None) or "ifnotus-1"
        cpu = int(getattr(settings, "infra_cpu_total", 12) or 12)
        ram = int(getattr(settings, "infra_ram_total_gb", 48) or 48)
        storage = int(getattr(settings, "infra_storage_total_gb", 200) or 200)
        reserved = int(getattr(settings, "infra_cpu_reserved_pct", 20) or 20)
        notes = "Primary shared-hosting node. Do not show this address to customers."
        nodes = await self.list_nodes()
        if nodes:
            node = nodes[0]
            node.hostname = hostname
            node.ip_address = "127.0.0.1"
            node.cpu_total = cpu
            node.ram_total_gb = ram
            node.storage_total_gb = storage
            node.cpu_reserved_pct = reserved
            node.status = "healthy"
            node.notes = notes
            await self._session.flush()
            return node
        node = InfrastructureNode(
            hostname=hostname,
            ip_address="127.0.0.1",
            cpu_total=cpu,
            ram_total_gb=ram,
            storage_total_gb=storage,
            cpu_reserved_pct=reserved,
            status="healthy",
            notes=notes,
        )
        self._session.add(node)
        await self._session.flush()
        return node

    async def pick_node_for_plan(self, plan: HostingPlan) -> InfrastructureNode:
        nodes = await self.list_nodes()
        if not nodes:
            from app.core.config import get_settings

            await self.ensure_primary_node(get_settings())
            nodes = await self.list_nodes()
        healthy = [n for n in nodes if n.status in {"healthy", "warning"}]
        if not healthy:
            raise RuntimeError("No healthy infrastructure nodes available.")

        best: InfrastructureNode | None = None
        best_free = -1.0
        for node in healthy:
            snap = await self.snapshot(node)
            if (
                snap.cpu_free >= float(plan.cpu_cores)
                and snap.ram_free >= float(plan.ram_gb)
                and snap.storage_free >= plan.storage_gb
            ):
                free_score = snap.cpu_free + snap.ram_free + snap.storage_free
                if free_score > best_free:
                    best = node
                    best_free = free_score
        if best is None:
            raise RuntimeError(
                "Insufficient capacity for this plan. Contact IFNOTUS support or choose a smaller plan."
            )
        return best

    async def snapshot(self, node: InfrastructureNode) -> CapacitySnapshot:
        reserved_cpu = max(1, int(node.cpu_total * node.cpu_reserved_pct / 100))
        reserved_ram = max(1, int(node.ram_total_gb * node.cpu_reserved_pct / 100))
        reserved_storage = max(1, int(node.storage_total_gb * node.cpu_reserved_pct / 100))

        cpu_alloc = node.cpu_total - reserved_cpu
        ram_alloc = node.ram_total_gb - reserved_ram
        storage_alloc = node.storage_total_gb - reserved_storage

        result = await self._session.execute(
            select(
                func.coalesce(func.sum(CustomerEnvironment.cpu_limit), 0),
                func.coalesce(func.sum(CustomerEnvironment.ram_limit_gb), 0),
                func.coalesce(func.sum(CustomerEnvironment.storage_limit_gb), 0),
            ).where(
                CustomerEnvironment.node_id == node.id,
                CustomerEnvironment.status.in_(["provisioning", "active", "suspended"]),
            )
        )
        cpu_used, ram_used, storage_used = result.one()
        cpu_used_f = float(cpu_used or 0)
        ram_used_f = float(ram_used or 0)
        storage_used_i = int(storage_used or 0)

        return CapacitySnapshot(
            node_id=str(node.id),
            hostname=node.hostname,
            cpu_total=node.cpu_total,
            ram_total_gb=node.ram_total_gb,
            storage_total_gb=node.storage_total_gb,
            cpu_reserved_pct=node.cpu_reserved_pct,
            cpu_allocatable=float(cpu_alloc),
            ram_allocatable=float(ram_alloc),
            storage_allocatable=storage_alloc,
            cpu_used=cpu_used_f,
            ram_used=ram_used_f,
            storage_used=storage_used_i,
            cpu_free=max(0.0, float(cpu_alloc) - cpu_used_f),
            ram_free=max(0.0, float(ram_alloc) - ram_used_f),
            storage_free=max(0, storage_alloc - storage_used_i),
            status=node.status,
        )

    async def active_subscription_usage(self, customer_id) -> dict:
        result = await self._session.execute(
            select(Subscription).where(
                Subscription.customer_id == customer_id,
                Subscription.status == "active",
            )
        )
        subs = list(result.scalars().all())
        return {
            "active_subscriptions": len(subs),
            "cpu": sum(s.cpu_allocated for s in subs),
            "ram_gb": sum(s.ram_allocated for s in subs),
            "storage_gb": sum(s.storage_allocated for s in subs),
            "bandwidth_used_gb": float(sum((s.bandwidth_used_gb or Decimal(0)) for s in subs)),
        }
