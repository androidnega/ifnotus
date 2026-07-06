"""File manager service with path sandboxing."""

from __future__ import annotations

import asyncio
import json
import math
import os
import shutil
import stat
import uuid
import zipfile
from datetime import UTC, datetime
from pathlib import Path

from fastapi import UploadFile

from app.core.config import Settings
from app.core.exceptions import AppException, NotFoundError
from app.repositories.applications import ApplicationRepository
from app.schemas.hosting import (
    FileDetailSchema,
    FileRootSchema,
    FileRootsResponse,
    FileUploadInitResponse,
)
from app.schemas.operations import FileEntry, FileListResponse, OperationResult


class FileManagerService:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._apps = ApplicationRepository(settings)
        self._runtime = None

    def _runtime_discovery(self):
        if self._runtime is None:
            from app.services.applications.discovery_runtime import RuntimeApplicationDiscovery

            self._runtime = RuntimeApplicationDiscovery(self._settings)
        return self._runtime

    def allowed_roots(self) -> list[Path]:
        roots: list[Path] = []
        for raw in self._settings.hosting_allowed_paths:
            roots.append(Path(raw).resolve())
        for app in self._apps.list_all():
            root = self._app_root(app)
            if root.exists():
                roots.append(root)
        for item in self._runtime_discovery().discover():
            if not item.registered:
                path = Path(item.root_path)
                if path.exists():
                    roots.append(path.resolve())
        if not roots:
            roots.append(Path.cwd().resolve())
        return list(dict.fromkeys(roots))

    async def list_roots(self) -> FileRootsResponse:
        roots: list[FileRootSchema] = []
        seen_paths: set[str] = set()

        for index, path in enumerate(self._hosting_roots()):
            roots.append(
                FileRootSchema(
                    id=f"root:{index}",
                    label=f"Hosting: {path.name or str(path)}",
                    path=str(path),
                )
            )
            seen_paths.add(str(path))

        for app in self._apps.list_all():
            root = self._app_root(app)
            if root.exists() and str(root) not in seen_paths:
                roots.append(FileRootSchema(id=app.id, label=f"App: {app.name}", path=str(root)))
                seen_paths.add(str(root))

        for item in self._runtime_discovery().discover():
            if item.registered:
                continue
            if item.root_path in seen_paths:
                continue
            roots.append(
                FileRootSchema(
                    id=f"discovered:{item.id}",
                    label=f"Discovered: {item.name}",
                    path=item.root_path,
                )
            )
            seen_paths.add(item.root_path)

        return FileRootsResponse(timestamp=datetime.now(UTC), roots=roots)

    def hosting_roots(self) -> list[Path]:
        return self._hosting_roots()

    def resolve_base(self, app_id: str | None, root_id: str | None = None) -> Path:
        return self._resolve_base(app_id, root_id)

    def _hosting_roots(self) -> list[Path]:
        roots: list[Path] = []
        for raw in self._settings.hosting_allowed_paths:
            roots.append(Path(raw).resolve())
        if not roots:
            roots.append(Path.cwd().resolve())
        return list(dict.fromkeys(roots))

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
        with target.open("wb") as out:
            while chunk := await file.read(1024 * 1024):
                out.write(chunk)
        return OperationResult(success=True, message=f"Uploaded to {target.relative_to(base)}")

    async def init_chunked_upload(
        self,
        filename: str,
        path: str,
        size_bytes: int,
        *,
        app_id: str | None = None,
        root_id: str | None = None,
        chunk_size: int | None = None,
    ) -> FileUploadInitResponse:
        chunk = chunk_size or self._settings.file_upload_chunk_size
        upload_id = str(uuid.uuid4())
        session_dir = self._upload_session_dir(upload_id)
        session_dir.mkdir(parents=True, exist_ok=True)
        meta = {
            "filename": filename,
            "path": path,
            "size_bytes": size_bytes,
            "chunk_size": chunk,
            "app_id": app_id,
            "root_id": root_id,
        }
        (session_dir / "meta.json").write_text(json.dumps(meta), encoding="utf-8")
        total_chunks = max(1, math.ceil(size_bytes / chunk))
        return FileUploadInitResponse(upload_id=upload_id, chunk_size=chunk, total_chunks=total_chunks)

    async def upload_chunk(
        self,
        upload_id: str,
        chunk_index: int,
        data: bytes,
    ) -> OperationResult:
        session_dir = self._upload_session_dir(upload_id)
        if not session_dir.exists():
            raise NotFoundError("Upload session not found or expired.")
        chunk_path = session_dir / f"chunk_{chunk_index:06d}"
        await asyncio.to_thread(chunk_path.write_bytes, data)
        return OperationResult(success=True, message=f"Chunk {chunk_index} stored.")

    async def complete_chunked_upload(self, upload_id: str) -> OperationResult:
        session_dir = self._upload_session_dir(upload_id)
        meta_path = session_dir / "meta.json"
        if not meta_path.exists():
            raise NotFoundError("Upload session not found or expired.")
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        base = self._resolve_base(meta.get("app_id"), meta.get("root_id"))
        dest_dir = self._safe_path(base, meta["path"])
        if not dest_dir.is_dir():
            dest_dir = dest_dir.parent
        target = dest_dir / meta["filename"]
        target.parent.mkdir(parents=True, exist_ok=True)

        chunks = sorted(session_dir.glob("chunk_*"))
        if not chunks:
            raise AppException("No chunks received.", code="upload_incomplete")

        with target.open("wb") as out:
            for chunk_file in chunks:
                out.write(chunk_file.read_bytes())

        shutil.rmtree(session_dir, ignore_errors=True)
        rel = target.relative_to(base)
        return OperationResult(success=True, message=f"Uploaded to {rel}")

    def resolve_download(
        self,
        path: str,
        *,
        app_id: str | None = None,
        root_id: str | None = None,
    ) -> tuple[Path, str]:
        base = self._resolve_base(app_id, root_id)
        target = self._safe_path(base, path)
        if not target.exists() or target.is_dir():
            raise NotFoundError("File not found.")
        return target, target.name

    def _upload_session_dir(self, upload_id: str) -> Path:
        root = Path(self._settings.file_upload_temp_dir)
        if not root.is_absolute():
            root = Path.cwd() / root
        return root / upload_id

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
        if root_id and root_id.startswith("discovered:"):
            slug = root_id.split(":", 1)[1]
            for item in self._runtime_discovery().discover():
                if item.id == slug:
                    return Path(item.root_path).resolve()
            raise AppException("Discovered application root not found.", code="invalid_root")
        if root_id and root_id.startswith("root:"):
            index = int(root_id.split(":", 1)[1])
            roots = self._hosting_roots()
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
