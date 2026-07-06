"""Application access helpers."""

from fastapi import Request

from app.services.applications.engine import ApplicationEngine


def get_application_engine(request: Request) -> ApplicationEngine:
    return request.app.state.container.application_engine()
