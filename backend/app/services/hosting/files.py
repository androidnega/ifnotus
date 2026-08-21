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
from app.services.applications.path_scanner import ApplicationPathScanner


class FileManagerService:
    def __init__(
        self,
        settings: Settings,
        *,
        admin_storage: bool = False,
        only_roots: list[Path] | None = None,
        storage_limit_gb: int | float | None = None,
    ) -> None:
        self._settings = settings
        self._admin_storage = admin_storage
        self._only_roots = [Path(p).resolve() for p in only_roots] if only_roots else None
        self._storage_limit_gb = storage_limit_gb
        self._apps = ApplicationRepository(settings)
        self._path_scanner = ApplicationPathScanner(settings)

    def _quota_root(self, base: Path) -> Path:
        if self._only_roots:
            return self._only_roots[0]
        return base

    def _assert_quota(self, base: Path, *, extra_bytes: int = 0) -> None:
        if self._storage_limit_gb is None:
            return
        from app.services.platform.usage import assert_write_allowed

        assert_write_allowed(
            self._quota_root(base),
            self._storage_limit_gb,
            extra_bytes=extra_bytes,
        )

    def _admin_storage_roots(self) -> list[Path]:
        """Privileged server storage roots exposed only to admin users."""
        if not self._admin_storage:
            return []
        candidates = [
            (Path("/srv"), "Server storage"),
            (Path("/var/www"), "Web storage"),
            (Path("/var/vmail"), "Mail storage"),
            (Path("/var/backups"), "Backups"),
        ]
        return [path.resolve() for path, _ in candidates if path.exists()]

    def allowed_roots(self) -> list[Path]:
        if self._only_roots is not None:
            return list(self._only_roots)
        roots: list[Path] = []
        roots.extend(self._admin_storage_roots())
        for raw in self._settings.hosting_allowed_paths:
            roots.append(Path(raw).resolve())
        for app in self._apps.list_all():
            root = self._app_root(app)
            if root.exists():
                roots.append(root)
        for item in self._path_scanner.unregistered_file_roots():
            path = Path(item.root_path)
            if path.exists():
                roots.append(path.resolve())
        if not roots:
            roots.append(Path.cwd().resolve())
        return list(dict.fromkeys(roots))

    async def list_roots(self) -> FileRootsResponse:
        roots: list[FileRootSchema] = []
        seen_paths: set[str] = set()

        if self._only_roots is not None:
            for index, path in enumerate(self._only_roots):
                roots.append(
                    FileRootSchema(
                        id=f"tenant:{index}",
                        label="My site",
                        # Never expose absolute host paths to tenant clients.
                        path=".",
                    )
                )
            return FileRootsResponse(roots=roots, timestamp=datetime.now(UTC))

        admin_labels = {
            "/srv": "Storage: Server (/srv)",
            "/var/www": "Storage: Web (/var/www)",
            "/var/vmail": "Storage: Mail (/var/vmail)",
            "/var/backups": "Storage: Backups (/var/backups)",
        }
        for index, path in enumerate(self._admin_storage_roots()):
            roots.append(
                FileRootSchema(
                    id=f"storage:{index}",
                    label=admin_labels.get(str(path), f"Storage: {path}"),
                    path=str(path),
                )
            )
            seen_paths.add(str(path))

        for index, path in enumerate(self._hosting_roots()):
            if str(path) in seen_paths:
                continue
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

        for item in self._path_scanner.unregistered_file_roots():
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
        new_bytes = len(content.encode("utf-8"))
        old_bytes = 0
        if target.exists() and target.is_file():
            try:
                old_bytes = target.stat().st_size
            except OSError:
                old_bytes = 0
        self._assert_quota(base, extra_bytes=new_bytes - old_bytes)
        target.parent.mkdir(parents=True, exist_ok=True)
        await asyncio.to_thread(target.write_text, content, encoding="utf-8")
        return OperationResult(success=True, message=f"Saved {path}")

    async def mkdir(self, path: str, *, app_id: str | None = None, root_id: str | None = None) -> OperationResult:
        base = self._resolve_base(app_id, root_id)
        # Empty dirs are free; still block when already hard-over so customers clean up first.
        self._assert_quota(base, extra_bytes=0)
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
        old_bytes = 0
        if target.exists() and target.is_file():
            try:
                old_bytes = target.stat().st_size
            except OSError:
                old_bytes = 0
        declared = None
        if file.size is not None:
            declared = int(file.size)
        elif file.headers.get("content-length"):
            try:
                declared = int(file.headers["content-length"])
            except (TypeError, ValueError):
                declared = None
        if declared is not None:
            self._assert_quota(base, extra_bytes=declared - old_bytes)

        from app.services.platform.usage import limit_bytes, measure_path_usage

        used_before, _ = measure_path_usage(self._quota_root(base))
        # Exclude bytes we are about to replace.
        used_base = max(0, used_before - old_bytes)
        limit = (
            limit_bytes(self._storage_limit_gb) if self._storage_limit_gb is not None else None
        )

        target.parent.mkdir(parents=True, exist_ok=True)
        written = 0
        with target.open("wb") as out:
            while chunk := await file.read(1024 * 1024):
                written += len(chunk)
                if limit is not None and used_base + written > limit:
                    out.close()
                    try:
                        target.unlink(missing_ok=True)
                    except OSError:
                        pass
                    from app.core.exceptions import ValidationError

                    raise ValidationError(
                        "Storage limit reached while uploading. Delete files or upgrade your plan.",
                        code="storage_quota_exceeded",
                    )
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
        base = self._resolve_base(app_id, root_id)
        self._assert_quota(base, extra_bytes=max(int(size_bytes), 0))
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
        if self._only_roots is not None:
            if root_id and root_id.startswith("tenant:"):
                index = int(root_id.split(":", 1)[1])
                if index < 0 or index >= len(self._only_roots):
                    raise AppException("Invalid root.", code="invalid_root")
                return self._only_roots[index]
            return self._only_roots[0]
        # Frontend may mis-send storage/root ids as app_id — normalize.
        if app_id and (
            app_id.startswith("storage:")
            or app_id.startswith("root:")
            or app_id.startswith("discovered:")
            or app_id.startswith("tenant:")
        ):
            root_id = app_id
            app_id = None
        if app_id:
            app = self._apps.get(app_id)
            return self._app_root(app)
        if root_id and root_id.startswith("storage:"):
            if not self._admin_storage:
                raise AppException("Admin storage access required.", code="forbidden")
            index = int(root_id.split(":", 1)[1])
            roots = self._admin_storage_roots()
            if index < 0 or index >= len(roots):
                raise AppException("Invalid storage root.", code="invalid_root")
            return roots[index]
        if root_id and root_id.startswith("discovered:"):
            slug = root_id.split(":", 1)[1]
            resolved = self._path_scanner.resolve_discovered_root(slug)
            if resolved is None:
                raise AppException("Discovered application root not found.", code="invalid_root")
            return resolved
        if root_id and root_id.startswith("root:"):
            index = int(root_id.split(":", 1)[1])
            roots = self._hosting_roots()
            if index < 0 or index >= len(roots):
                raise AppException("Invalid root.", code="invalid_root")
            return roots[index]
        return self.allowed_roots()[0]

    def _safe_path(self, base: Path, path: str) -> Path:
        base = base.resolve()
        allowed = [root.resolve() for root in self.allowed_roots()]
        if not any(base == root or base.is_relative_to(root) for root in allowed):
            raise AppException("Path not in allowed roots.", code="forbidden")
        raw = (path or ".").replace("\x00", "").strip() or "."
        # Never allow absolute inputs to escape the jail.
        if raw.startswith(("/", "\\")) or (len(raw) >= 2 and raw[1] == ":"):
            raise AppException("Path traversal denied.", code="forbidden")
        target = (base / raw).resolve()
        if not any(target == root or target.is_relative_to(root) for root in allowed):
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
        # Tenant portal: hide OS account names (layout hint) — keep for staff roots.
        if self._only_roots is not None:
            owner = group = None
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
