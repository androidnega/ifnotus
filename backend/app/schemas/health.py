"""Health check schemas."""

from datetime import datetime
from enum import StrEnum

from app.schemas.common import SchemaBase


class HealthStatus(StrEnum):
    """Component health status."""

    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"


class ComponentHealth(SchemaBase):
    """Individual component health."""

    name: str
    status: HealthStatus
    latency_ms: float | None = None
    message: str | None = None


class HealthResponse(SchemaBase):
    """Liveness probe response."""

    status: HealthStatus
    version: str
    environment: str
    timestamp: datetime


class ReadinessResponse(SchemaBase):
    """Readiness probe response with dependency checks."""

    status: HealthStatus
    version: str
    environment: str
    timestamp: datetime
    components: list[ComponentHealth]
