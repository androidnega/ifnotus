"""Hosting service accessors."""

from fastapi import Request

from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db
from app.core.config import Settings
from app.services.hosting.domains import DomainService
from app.services.hosting.files import FileManagerService
from app.services.hosting.mail import MailService
from app.services.hosting.ssl import SslService
from app.services.hosting.terminal import TerminalService


def get_settings(request: Request) -> Settings:
    return request.app.state.container.config()


async def get_domain_service(request: Request, session: AsyncSession) -> DomainService:
    return DomainService(get_settings(request), session)


async def get_ssl_service(request: Request, session: AsyncSession) -> SslService:
    return SslService(get_settings(request), session)


async def get_mail_service(request: Request, session: AsyncSession) -> MailService:
    return MailService(get_settings(request), session)


def get_file_service(request: Request) -> FileManagerService:
    return FileManagerService(get_settings(request))


async def get_terminal_service(request: Request, session: AsyncSession) -> TerminalService:
    return TerminalService(get_settings(request), session)
