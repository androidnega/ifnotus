"""Monitoring collector base interface and utilities."""

from __future__ import annotations

import time
from abc import ABC, abstractmethod
from datetime import UTC, datetime
from typing import Any, ClassVar, Generic, TypeVar

from pydantic import BaseModel

from app.schemas.monitoring import CollectorHealthSchema, CollectorStatus

T = TypeVar("T", bound=BaseModel)


class BaseCollector(ABC, Generic[T]):
    """Common interface for all monitoring collectors."""

    name: ClassVar[str]
    cache_ttl: ClassVar[int] = 0
    expensive: ClassVar[bool] = False

    @abstractmethod
    async def collect(self) -> T:
        """Collect live metrics from the host."""
        ...

    async def health_check(self) -> CollectorHealthSchema:
        """Verify the collector can gather data."""
        start = time.perf_counter()
        try:
            await self.collect()
            latency = (time.perf_counter() - start) * 1000
            return CollectorHealthSchema(
                name=self.name,
                status=CollectorStatus.HEALTHY,
                latency_ms=round(latency, 2),
                last_collected_at=datetime.now(UTC),
                available=True,
            )
        except CollectorUnavailableError as exc:
            latency = (time.perf_counter() - start) * 1000
            return CollectorHealthSchema(
                name=self.name,
                status=CollectorStatus.UNAVAILABLE,
                latency_ms=round(latency, 2),
                message=str(exc),
                available=False,
            )
        except Exception as exc:
            latency = (time.perf_counter() - start) * 1000
            return CollectorHealthSchema(
                name=self.name,
                status=CollectorStatus.UNHEALTHY,
                latency_ms=round(latency, 2),
                message=str(exc),
                available=True,
            )


class CollectorUnavailableError(Exception):
    """Raised when an optional integration is not configured or not present."""


class CollectorResult(BaseModel):
    """Wrapper for cached collector output."""

    data: Any
    collected_at: datetime
