"""API v1 router aggregation."""

from fastapi import APIRouter

from app.routers.v1 import alerts, applications, auth, dashboard, health, hosting, logs, monitoring, operations, processes, server, services

api_v1_router = APIRouter()

api_v1_router.include_router(health.router, tags=["health"])
api_v1_router.include_router(auth.router, prefix="/auth", tags=["auth"])
api_v1_router.include_router(applications.router, prefix="/applications", tags=["applications"])
api_v1_router.include_router(hosting.hosting_router, tags=["hosting"])
api_v1_router.include_router(operations.router, prefix="/operations", tags=["operations"])
api_v1_router.include_router(monitoring.router, prefix="/monitoring", tags=["monitoring"])
api_v1_router.include_router(server.router, prefix="/server", tags=["server"])
api_v1_router.include_router(services.router, prefix="/services", tags=["services"])
api_v1_router.include_router(processes.router, prefix="/processes", tags=["processes"])
api_v1_router.include_router(logs.router, prefix="/logs", tags=["logs"])
api_v1_router.include_router(alerts.router, prefix="/alerts", tags=["alerts"])
api_v1_router.include_router(dashboard.router, prefix="/dashboard", tags=["dashboard"])
