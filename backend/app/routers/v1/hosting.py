"""Hosting routers — domains, ssl, mail, files, terminal, databases, ai."""

from fastapi import APIRouter, Depends

from app.api.deps import DenyCustomerHost
from app.routers.v1 import ai, databases, domains, files, mail, ssl, terminal

hosting_router = APIRouter(dependencies=[Depends(DenyCustomerHost)])

hosting_router.include_router(domains.router, prefix="/domains", tags=["domains"])
hosting_router.include_router(ssl.router, prefix="/ssl", tags=["ssl"])
hosting_router.include_router(mail.router, prefix="/mail", tags=["mail"])
hosting_router.include_router(files.router, prefix="/files", tags=["files"])
hosting_router.include_router(terminal.router, prefix="/terminal", tags=["terminal"])
hosting_router.include_router(databases.router, prefix="/databases", tags=["databases"])
hosting_router.include_router(ai.router, prefix="/ai", tags=["ai"])
