"""Operations service accessors."""

from fastapi import Request

from app.services.operations.app_actions import ApplicationActionsService
from app.services.operations.service import OperationsService


def get_operations_service(request: Request) -> OperationsService:
    return request.app.state.container.operations_service()


def get_application_actions(request: Request) -> ApplicationActionsService:
    return request.app.state.container.application_actions_service()
