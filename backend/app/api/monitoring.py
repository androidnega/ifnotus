"""Shared monitoring service accessor."""

from fastapi import Request

from app.services.monitoring import MonitoringService


def get_monitoring_service(request: Request) -> MonitoringService:
    return request.app.state.container.monitoring_service()
