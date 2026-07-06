"""Hosting routers — domains, ssl, mail, files, terminal."""

from fastapi import APIRouter

from app.routers.v1 import domains, files, mail, ssl, terminal

hosting_router = APIRouter()

hosting_router.include_router(domains.router, prefix="/domains", tags=["domains"])
hosting_router.include_router(ssl.router, prefix="/ssl", tags=["ssl"])
hosting_router.include_router(mail.router, prefix="/mail", tags=["mail"])
hosting_router.include_router(files.router, prefix="/files", tags=["files"])
hosting_router.include_router(terminal.router, prefix="/terminal", tags=["terminal"])
