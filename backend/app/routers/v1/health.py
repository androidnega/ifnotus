"""Health and readiness endpoints."""

from fastapi import APIRouter, Request, Response, status

from app.schemas.health import HealthResponse, HealthStatus, ReadinessResponse
from app.services.health import HealthService

router = APIRouter()


def _get_health_service(request: Request) -> HealthService:
    container = request.app.state.container
    return HealthService(
        container.config(),
        container.db_engine(),
        container.redis_client(),
    )


@router.get("/health", response_model=HealthResponse, summary="Liveness probe")
def liveness(request: Request) -> HealthResponse:
    """Kubernetes liveness probe — returns 200 if process is alive."""
    return _get_health_service(request).liveness()


@router.get("/health/live", response_model=HealthResponse, summary="Liveness probe (alias)")
def liveness_alias(request: Request) -> HealthResponse:
    """Alias for /health."""
    return _get_health_service(request).liveness()


@router.get("/health/ready", response_model=ReadinessResponse, summary="Readiness probe")
async def readiness(request: Request, response: Response) -> ReadinessResponse:
    """Kubernetes readiness probe — checks database and Redis."""
    result = await _get_health_service(request).readiness()
    if result.status == HealthStatus.UNHEALTHY:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return result
