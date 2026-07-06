"""File manager service with path sandboxing."""

from __future__ import annotations

import asyncio
import os
import shutil
import stat
import zipfile
from datetime import UTC, datetime
from pathlib import Path

from fastapi import UploadFile

from app.core.config import Settings
from app.core.exceptions import AppException, NotFoundError
from app.repositories.applications import ApplicationRepository
from app.schemas.hosting import FileDetailSchema, FileRootSchema, FileRootsResponse
from app.schemas.operations import FileEntry, FileListResponse, OperationResult


class FileManagerService:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._apps = ApplicationRepository(settings)

    def allowed_roots(self) -> list[Path]:
        roots: list[Path] = []
        for raw in self._settings.hosting_allowed_paths:
            roots.append(Path(raw).resolve())
        for app in self._apps.list_all():
            root = self._app_root(app)
            if root.exists():
                roots.append(root)
        if not roots:
            roots.append(Path.cwd().resolve())
        return list(dict.fromkeys(roots))

    async def list_roots(self) -> FileRootsResponse:
        roots: list[FileRootSchema] = []
        for index, path in enumerate(self.allowed_roots()):
            roots.append(
                FileRootSchema(
                    id=f"root:{index}",
                    label=path.name or str(path),
                    path=str(path),
                )
            )
        for app in self._apps.list_all():
            root = self._app_root(app)
            if root.exists():
                roots.append(FileRootSchema(id=app.id, label=app.name, path=str(root)))
        return FileRootsResponse(timestamp=datetime.now(UTC), roots=roots)

    async def list_files(
        self,
        path: str = ".",
        *,
        app_id: str | None = None,
        root_id: str | None = None,
    ) -> FileListResponse:
        base = self._resolve_base(app_id, root_id)
        target = self._safe_path(base, path)
        if not target.exists():
            raise NotFoundError(f"Path not found: {path}")

        entries: list[FileEntry] = []
        if target.is_dir():
            for child in sorted(target.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower())):
                if child.name.startswith(".") and child.name not in {".ifnotus"}:
                    continue
                detail = self._file_detail(child, base)
                entries.append(
                    FileEntry(
                        name=detail.name,
                        path=detail.path,
                        is_dir=detail.is_dir,
                        size_bytes=detail.size_bytes,
                        modified=detail.modified,
                        mode=detail.mode,
                        owner=detail.owner,
                        group=detail.group,
                    )
                )
        parent = None
        if target != base:
            parent = str(target.parent.relative_to(base)) if target.parent != base else "."
        rel = str(target.relative_to(base)) if target != base else "."
        return FileListResponse(timestamp=datetime.now(UTC), path=rel, entries=entries, parent=parent)

    async def read_file(
        self, path: str, *, app_id: str | None = None, root_id: str | None = None
    ) -> FileDetailSchema:
        base = self._resolve_base(app_id, root_id)
        target = self._safe_path(base, path)
        if not target.exists() or target.is_dir():
            raise NotFoundError("File not found.")
        if target.stat().st_size > 2_000_000:
            raise AppException("File too large to edit inline.", code="file_too_large")
        content = await asyncio.to_thread(target.read_text, encoding="utf-8", errors="replace")
        return self._file_detail(target, base, content=content)

    async def write_file(
        self, path: str, content: str, *, app_id: str | None = None, root_id: str | None = None
    ) -> OperationResult:
        base = self._resolve_base(app_id, root_id)
        target = self._safe_path(base, path)
        target.parent.mkdir(parents=True, exist_ok=True)
        await asyncio.to_thread(target.write_text, content, encoding="utf-8")
        return OperationResult(success=True, message=f"Saved {path}")

    async def mkdir(self, path: str, *, app_id: str | None = None, root_id: str | None = None) -> OperationResult:
        base = self._resolve_base(app_id, root_id)
        target = self._safe_path(base, path)
        target.mkdir(parents=True, exist_ok=True)
        return OperationResult(success=True, message=f"Created directory {path}")

    async def move(
        self,
        source: str,
        destination: str,
        *,
        app_id: str | None = None,
        root_id: str | None = None,
    ) -> OperationResult:
        base = self._resolve_base(app_id, root_id)
        src = self._safe_path(base, source)
        dst = self._safe_path(base, destination)
        if not src.exists():
            raise NotFoundError("Source not found.")
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(src), str(dst))
        return OperationResult(success=True, message=f"Moved to {destination}")

    async def delete(self, path: str, *, app_id: str | None = None, root_id: str | None = None) -> OperationResult:
        base = self._resolve_base(app_id, root_id)
        target = self._safe_path(base, path)
        if not target.exists():
            raise NotFoundError("Path not found.")
        if target.is_dir():
            shutil.rmtree(target)
        else:
            target.unlink()
        return OperationResult(success=True, message=f"Deleted {path}")

    async def chmod(
        self, path: str, mode: str, *, app_id: str | None = None, root_id: str | None = None
    ) -> OperationResult:
        base = self._resolve_base(app_id, root_id)
        target = self._safe_path(base, path)
        if not target.exists():
            raise NotFoundError("Path not found.")
        os.chmod(target, int(mode, 8))
        return OperationResult(success=True, message=f"chmod {mode} {path}")

    async def upload(
        self, path: str, file: UploadFile, *, app_id: str | None = None, root_id: str | None = None
    ) -> OperationResult:
        base = self._resolve_base(app_id, root_id)
        target = self._safe_path(base, path)
        if target.is_dir():
            target = target / (file.filename or "upload.bin")
        target.parent.mkdir(parents=True, exist_ok=True)
        data = await file.read()
        await asyncio.to_thread(target.write_bytes, data)
        return OperationResult(success=True, message=f"Uploaded to {target.relative_to(base)}")

    async def unzip(self, path: str, *, app_id: str | None = None, root_id: str | None = None) -> OperationResult:
        base = self._resolve_base(app_id, root_id)
        target = self._safe_path(base, path)
        if not target.is_file() or not target.suffix.lower() == ".zip":
            raise AppException("Only .zip archives can be extracted.", code="invalid_archive")
        dest = target.parent / target.stem
        dest.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(target, "r") as zf:
            zf.extractall(dest)
        return OperationResult(success=True, message=f"Extracted to {dest.relative_to(base)}")

    async def stat_file(
        self, path: str, *, app_id: str | None = None, root_id: str | None = None
    ) -> FileDetailSchema:
        base = self._resolve_base(app_id, root_id)
        target = self._safe_path(base, path)
        if not target.exists():
            raise NotFoundError("Path not found.")
        return self._file_detail(target, base)

    def _app_root(self, app) -> Path:
        root = Path(app.paths.root)
        if not root.is_absolute() and app.source_file:
            return (Path(app.source_file).parent / root).resolve()
        if root.is_absolute():
            return root.resolve()
        return (Path.cwd() / root).resolve()

    def _resolve_base(self, app_id: str | None, root_id: str | None = None) -> Path:
        if app_id:
            app = self._apps.get(app_id)
            return self._app_root(app)
        if root_id and root_id.startswith("root:"):
            index = int(root_id.split(":", 1)[1])
            roots = self.allowed_roots()
            if index < 0 or index >= len(roots):
                raise AppException("Invalid root.", code="invalid_root")
            return roots[index]
        return self.allowed_roots()[0]

    def _safe_path(self, base: Path, path: str) -> Path:
        base = base.resolve()
        for root in self.allowed_roots():
            if str(base).startswith(str(root)) or base == root:
                break
        else:
            if base not in self.allowed_roots():
                raise AppException("Path not in allowed roots.", code="forbidden")
        target = (base / path.lstrip("/")).resolve()
        if not any(str(target).startswith(str(r)) for r in self.allowed_roots()):
            raise AppException("Path traversal denied.", code="forbidden")
        return target

    def _file_detail(self, target: Path, base: Path, *, content: str | None = None) -> FileDetailSchema:
        st = target.stat()
        mode = oct(stat.S_IMODE(st.st_mode))[-3:]
        owner = group = None
        try:
            import pwd
            import grp

            owner = pwd.getpwuid(st.st_uid).pw_name
            group = grp.getgrgid(st.st_gid).gr_name
        except (ImportError, KeyError):
            pass
        return FileDetailSchema(
            name=target.name,
            path=str(target.relative_to(base)),
            is_dir=target.is_dir(),
            size_bytes=None if target.is_dir() else st.st_size,
            mode=mode,
            owner=owner,
            group=group,
            modified=datetime.fromtimestamp(st.st_mtime, tz=UTC),
            content=content,
        )
