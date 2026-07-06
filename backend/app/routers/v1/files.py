"""File manager endpoints."""

from fastapi import APIRouter, Depends, File, Query, Request, UploadFile

from app.api.deps import CurrentUser, RequirePermission
from app.core.permissions import Permission
from app.schemas.hosting import (
    FileChmodRequest,
    FileDetailSchema,
    FileMkdirRequest,
    FileMoveRequest,
    FileRootsResponse,
    FileWriteRequest,
)
from app.schemas.operations import FileListResponse, OperationResult
from app.services.hosting.files import FileManagerService

router = APIRouter()


def _files(request: Request) -> FileManagerService:
    settings = request.app.state.container.config()
    return FileManagerService(settings)


def _root_params(app_id: str | None, root_id: str | None) -> dict[str, str | None]:
    return {"app_id": app_id, "root_id": root_id}


@router.get(
    "/roots",
    response_model=FileRootsResponse,
    dependencies=[Depends(RequirePermission(Permission.FILES_READ))],
)
async def list_roots(request: Request, _user: CurrentUser) -> FileRootsResponse:
    return await _files(request).list_roots()


@router.get(
    "",
    response_model=FileListResponse,
    dependencies=[Depends(RequirePermission(Permission.FILES_READ))],
)
async def list_files(
    request: Request,
    _user: CurrentUser,
    path: str = Query(default="."),
    app_id: str | None = Query(default=None),
    root_id: str | None = Query(default=None),
) -> FileListResponse:
    return await _files(request).list_files(path, **_root_params(app_id, root_id))


@router.get(
    "/content",
    response_model=FileDetailSchema,
    dependencies=[Depends(RequirePermission(Permission.FILES_READ))],
)
async def read_file(
    request: Request,
    _user: CurrentUser,
    path: str = Query(...),
    app_id: str | None = Query(default=None),
    root_id: str | None = Query(default=None),
) -> FileDetailSchema:
    return await _files(request).read_file(path, **_root_params(app_id, root_id))


@router.put(
    "/content",
    response_model=OperationResult,
    dependencies=[Depends(RequirePermission(Permission.FILES_WRITE))],
)
async def write_file(
    body: FileWriteRequest,
    request: Request,
    _user: CurrentUser,
    app_id: str | None = Query(default=None),
    root_id: str | None = Query(default=None),
) -> OperationResult:
    return await _files(request).write_file(body.path, body.content, **_root_params(app_id, root_id))


@router.post(
    "/mkdir",
    response_model=OperationResult,
    dependencies=[Depends(RequirePermission(Permission.FILES_WRITE))],
)
async def mkdir(
    body: FileMkdirRequest,
    request: Request,
    _user: CurrentUser,
    app_id: str | None = Query(default=None),
    root_id: str | None = Query(default=None),
) -> OperationResult:
    return await _files(request).mkdir(body.path, **_root_params(app_id, root_id))


@router.post(
    "/move",
    response_model=OperationResult,
    dependencies=[Depends(RequirePermission(Permission.FILES_WRITE))],
)
async def move_file(
    body: FileMoveRequest,
    request: Request,
    _user: CurrentUser,
    app_id: str | None = Query(default=None),
    root_id: str | None = Query(default=None),
) -> OperationResult:
    return await _files(request).move(body.source, body.destination, **_root_params(app_id, root_id))


@router.delete(
    "",
    response_model=OperationResult,
    dependencies=[Depends(RequirePermission(Permission.FILES_WRITE))],
)
async def delete_path(
    request: Request,
    _user: CurrentUser,
    path: str = Query(...),
    app_id: str | None = Query(default=None),
    root_id: str | None = Query(default=None),
) -> OperationResult:
    return await _files(request).delete(path, **_root_params(app_id, root_id))


@router.post(
    "/chmod",
    response_model=OperationResult,
    dependencies=[Depends(RequirePermission(Permission.FILES_WRITE))],
)
async def chmod(
    body: FileChmodRequest,
    request: Request,
    _user: CurrentUser,
    app_id: str | None = Query(default=None),
    root_id: str | None = Query(default=None),
) -> OperationResult:
    return await _files(request).chmod(body.path, body.mode, **_root_params(app_id, root_id))


@router.post(
    "/upload",
    response_model=OperationResult,
    dependencies=[Depends(RequirePermission(Permission.FILES_WRITE))],
)
async def upload_file(
    request: Request,
    _user: CurrentUser,
    path: str = Query(default="."),
    app_id: str | None = Query(default=None),
    root_id: str | None = Query(default=None),
    file: UploadFile = File(...),
) -> OperationResult:
    return await _files(request).upload(path, file, **_root_params(app_id, root_id))


@router.post(
    "/unzip",
    response_model=OperationResult,
    dependencies=[Depends(RequirePermission(Permission.FILES_WRITE))],
)
async def unzip(
    request: Request,
    _user: CurrentUser,
    path: str = Query(...),
    app_id: str | None = Query(default=None),
    root_id: str | None = Query(default=None),
) -> OperationResult:
    return await _files(request).unzip(path, **_root_params(app_id, root_id))


@router.get(
    "/stat",
    response_model=FileDetailSchema,
    dependencies=[Depends(RequirePermission(Permission.FILES_READ))],
)
async def stat_file(
    request: Request,
    _user: CurrentUser,
    path: str = Query(...),
    app_id: str | None = Query(default=None),
    root_id: str | None = Query(default=None),
) -> FileDetailSchema:
    return await _files(request).stat_file(path, **_root_params(app_id, root_id))
