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
from app.core.exceptions import AppException, NotFoundError, ValidationError
from app.repositories.applications import ApplicationRepository
from app.schemas.hosting import (
    FileDetailSchema,
    FileRootSchema,
    FileRootsResponse,
    FileUploadInitResponse,
    TrashEntrySchema,
    TrashListResponse,
)
from app.schemas.operations import FileEntry, FileListResponse, OperationResult
from app.services.applications.path_scanner import ApplicationPathScanner


def safe_upload_basename(filename: str | None) -> str:
    """Strip directories from an upload name so it cannot escape the destination dir."""
    raw = (filename or "upload.bin").replace("\x00", "").strip()
    name = Path(raw).name.strip()
    if not name or name in {".", ".."} or "/" in name or "\\" in name:
        return "upload.bin"
    return name


def zip_member_is_safe(member_name: str, dest: Path) -> Path:
    """Resolve archive member under dest; raise on zip-slip / absolute / parent segments."""
    raw = (member_name or "").replace("\\", "/").strip()
    if not raw or raw.endswith("/"):
        # Directory entries are validated when children are written.
        target = (dest / raw).resolve() if raw else dest.resolve()
    else:
        target = (dest / raw).resolve()
    dest_resolved = dest.resolve()
    if raw.startswith("/") or (len(raw) >= 2 and raw[1] == ":"):
        raise ValidationError("Archive contains an absolute path.", code="zip_slip")
    parts = Path(raw).parts
    if any(p == ".." for p in parts):
        raise ValidationError("Archive contains a path traversal entry.", code="zip_slip")
    try:
        target.relative_to(dest_resolved)
    except ValueError as exc:
        raise ValidationError("Archive entry escapes the extract folder.", code="zip_slip") from exc
    return target


class FileManagerService:
    def __init__(
        self,
        settings: Settings,
        *,
        admin_storage: bool = False,
        only_roots: list[Path] | None = None,
        storage_limit_gb: int | float | None = None,
        owner_uid: int | None = None,
        owner_gid: int | None = None,
    ) -> None:
        self._settings = settings
        self._admin_storage = admin_storage
        self._only_roots = [Path(p).resolve() for p in only_roots] if only_roots else None
        self._storage_limit_gb = storage_limit_gb
        self._owner_uid = owner_uid
        self._owner_gid = owner_gid
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
                if child.name.startswith("."):
                    # For customer tenant views, hide internal platform metadata .ifnotus and hidden dotfiles
                    if not self._admin_storage:
                        continue
                    if child.name not in {".ifnotus"}:
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
        self._apply_owner(target)
        return OperationResult(success=True, message=f"Saved {path}")

    async def mkdir(self, path: str, *, app_id: str | None = None, root_id: str | None = None) -> OperationResult:
        base = self._resolve_base(app_id, root_id)
        # Empty dirs are free; still block when already hard-over so customers clean up first.
        self._assert_quota(base, extra_bytes=0)
        target = self._safe_path(base, path)
        target.mkdir(parents=True, exist_ok=True)
        self._apply_owner(target)
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
        self._apply_owner(dst.parent)
        shutil.move(str(src), str(dst))
        self._apply_owner(dst)
        return OperationResult(success=True, message=f"Moved to {destination}")

    async def copy(
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
        extra = self._path_size_bytes(src)
        self._assert_quota(base, extra_bytes=extra)
        dst.parent.mkdir(parents=True, exist_ok=True)
        self._apply_owner(dst.parent)
        if src.is_dir():
            if dst.exists():
                raise ValidationError("Destination already exists.", code="destination_exists")
            shutil.copytree(src, dst, symlinks=False)
        else:
            shutil.copy2(src, dst)
        self._apply_owner_tree(dst)
        return OperationResult(success=True, message=f"Copied to {destination}")

    async def delete(self, path: str, *, permanent: bool = False, deleted_by: str | None = None, app_id: str | None = None, root_id: str | None = None) -> OperationResult:
        base = self._resolve_base(app_id, root_id)
        target = self._safe_path(base, path)
        if not target.exists():
            raise NotFoundError("Path not found.")
        if not permanent:
            res = await self.move_to_trash([path], deleted_by=deleted_by, app_id=app_id, root_id=root_id)
            if res.get("moved", 0) > 0:
                return OperationResult(success=True, message=f"Moved {path} to Trash")
            raise AppException("Could not move item to Trash.", code="trash_failed")
        try:
            self._unlink_path(target)
        except PermissionError as exc:
            # Parking pages / root-owned files: reclaim then retry when API is privileged.
            try:
                self._reclaim_for_delete(target)
                self._unlink_path(target)
            except OSError as retry_exc:
                raise AppException(
                    "Could not delete this file (permission denied). Try again or contact support.",
                    code="delete_denied",
                ) from retry_exc
            except PermissionError as retry_exc:
                raise AppException(
                    "Could not delete this file (permission denied). Try again or contact support.",
                    code="delete_denied",
                ) from retry_exc
        except OSError as exc:
            raise AppException(
                f"Could not delete this file: {exc}",
                code="delete_failed",
            ) from exc
        return OperationResult(success=True, message=f"Deleted {path}")

    def _trash_root(self, base: Path) -> Path:
        base = base.resolve()
        if base.name in {"public_html", "web", "httpdocs"} and base.parent.exists() and base.parent.is_dir():
            trash_root = (base.parent / ".ifnotus-trash").resolve()
        else:
            trash_root = (base / ".ifnotus" / "trash").resolve()
        trash_root.mkdir(parents=True, exist_ok=True)
        try:
            trash_root.chmod(0o700)
            if self._owner_uid is not None:
                self._apply_owner(trash_root)
        except OSError:
            pass
        return trash_root

    def _read_trash_manifest(self, trash_root: Path) -> dict[str, dict]:
        manifest_file = trash_root / "manifest.json"
        if not manifest_file.exists():
            return {}
        try:
            return json.loads(manifest_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}

    def _write_trash_manifest(self, trash_root: Path, manifest: dict[str, dict]) -> None:
        manifest_file = trash_root / "manifest.json"
        manifest_file.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        try:
            manifest_file.chmod(0o600)
            if self._owner_uid is not None:
                self._apply_owner(manifest_file)
        except OSError:
            pass

    async def move_to_trash(
        self,
        paths: list[str] | str,
        *,
        deleted_by: str | None = None,
        app_id: str | None = None,
        root_id: str | None = None,
    ) -> dict:
        base = self._resolve_base(app_id, root_id)
        trash_root = self._trash_root(base)
        manifest = self._read_trash_manifest(trash_root)

        path_list = [paths] if isinstance(paths, str) else paths
        moved = 0
        failed = 0
        moved_items: list[dict] = []

        for p in path_list:
            if not p:
                continue
            try:
                target = self._safe_path(base, p)
                if not target.exists():
                    failed += 1
                    continue
                rel_path = str(target.relative_to(base)) if target != base else "."
                if rel_path in {".", ""}:
                    failed += 1
                    continue
                trash_id = str(uuid.uuid4())
                is_dir = target.is_dir()
                size_bytes = self._path_size_bytes(target) if is_dir else target.stat().st_size
                stored_name = f"{trash_id}__{target.name}"
                dest = trash_root / stored_name

                shutil.move(str(target), str(dest))
                manifest[trash_id] = {
                    "trash_id": trash_id,
                    "stored_name": stored_name,
                    "original_path": rel_path,
                    "display_name": target.name,
                    "item_type": "dir" if is_dir else "file",
                    "size_bytes": size_bytes,
                    "deleted_at": datetime.now(UTC).isoformat(),
                    "deleted_by": deleted_by,
                }
                moved_items.append(manifest[trash_id])
                moved += 1
            except Exception:
                failed += 1

        self._write_trash_manifest(trash_root, manifest)
        return {
            "success": moved > 0 or failed == 0,
            "moved": moved,
            "failed": failed,
            "items": moved_items,
            "message": f"Moved {moved} item(s) to Trash",
        }

    async def list_trash(
        self,
        *,
        app_id: str | None = None,
        root_id: str | None = None,
    ) -> TrashListResponse:
        base = self._resolve_base(app_id, root_id)
        trash_root = self._trash_root(base)
        manifest = self._read_trash_manifest(trash_root)

        entries: list[TrashEntrySchema] = []
        total_size = 0
        prune_needed = False

        for trash_id, item in list(manifest.items()):
            stored_path = trash_root / item.get("stored_name", "")
            if not stored_path.exists():
                manifest.pop(trash_id, None)
                prune_needed = True
                continue
            size = item.get("size_bytes")
            if size is None:
                try:
                    size = self._path_size_bytes(stored_path) if stored_path.is_dir() else stored_path.stat().st_size
                except OSError:
                    size = 0
            total_size += size or 0
            try:
                deleted_at = datetime.fromisoformat(item["deleted_at"])
            except Exception:
                deleted_at = datetime.now(UTC)

            entries.append(
                TrashEntrySchema(
                    trash_id=trash_id,
                    original_path=item.get("original_path", ""),
                    display_name=item.get("display_name", stored_path.name),
                    item_type=item.get("item_type", "dir" if stored_path.is_dir() else "file"),
                    size_bytes=size,
                    deleted_at=deleted_at,
                    deleted_by=item.get("deleted_by"),
                )
            )

        if prune_needed:
            self._write_trash_manifest(trash_root, manifest)

        entries.sort(key=lambda e: e.deleted_at, reverse=True)
        return TrashListResponse(entries=entries, total_size_bytes=total_size, count=len(entries))

    async def restore_from_trash(
        self,
        trash_id: str,
        *,
        conflict_mode: str = "copy",
        app_id: str | None = None,
        root_id: str | None = None,
    ) -> OperationResult:
        base = self._resolve_base(app_id, root_id)
        trash_root = self._trash_root(base)
        manifest = self._read_trash_manifest(trash_root)

        if trash_id not in manifest:
            raise NotFoundError("Trash item not found.")

        item = manifest[trash_id]
        stored_path = (trash_root / item["stored_name"]).resolve()
        if not stored_path.exists() or not stored_path.is_relative_to(trash_root):
            manifest.pop(trash_id, None)
            self._write_trash_manifest(trash_root, manifest)
            raise NotFoundError("Stored trash item file is missing.")

        target = self._safe_path(base, item["original_path"])
        if target.exists():
            if conflict_mode == "cancel":
                raise ValidationError(
                    f"A file or directory named '{item['display_name']}' already exists in target destination.",
                    code="conflict",
                )
            elif conflict_mode == "replace":
                self._unlink_path(target)
            elif conflict_mode == "copy":
                parent = target.parent
                is_file = item.get("item_type") != "dir" and not stored_path.is_dir()
                stem = target.stem if is_file else target.name
                suffix = target.suffix if is_file else ""
                idx = 1
                while True:
                    suffix_part = f" (restored{f' {idx}' if idx > 1 else ''})"
                    candidate_name = f"{stem}{suffix_part}{suffix}"
                    candidate_path = parent / candidate_name
                    if not candidate_path.exists():
                        target = candidate_path
                        break
                    idx += 1
            else:
                raise ValidationError("Invalid conflict mode.", code="invalid_conflict_mode")

        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(stored_path), str(target))
        self._apply_owner_tree(target)

        manifest.pop(trash_id, None)
        self._write_trash_manifest(trash_root, manifest)

        rel_dest = str(target.relative_to(base)) if target != base else "."
        return OperationResult(
            success=True,
            message=f"Restored {item['display_name']} to {rel_dest}",
        )

    async def permanent_delete_trash(
        self,
        trash_id: str,
        *,
        app_id: str | None = None,
        root_id: str | None = None,
    ) -> OperationResult:
        base = self._resolve_base(app_id, root_id)
        trash_root = self._trash_root(base)
        manifest = self._read_trash_manifest(trash_root)

        if trash_id not in manifest:
            raise NotFoundError("Trash item not found.")

        item = manifest[trash_id]
        stored_path = (trash_root / item["stored_name"]).resolve()
        if stored_path.exists() and stored_path.is_relative_to(trash_root):
            self._unlink_path(stored_path)

        manifest.pop(trash_id, None)
        self._write_trash_manifest(trash_root, manifest)
        return OperationResult(success=True, message=f"Permanently deleted {item.get('display_name', 'item')}")

    async def empty_trash(
        self,
        *,
        app_id: str | None = None,
        root_id: str | None = None,
    ) -> OperationResult:
        base = self._resolve_base(app_id, root_id)
        trash_root = self._trash_root(base)
        if trash_root.exists():
            for child in list(trash_root.iterdir()):
                if child.name != "manifest.json":
                    self._unlink_path(child)
        self._write_trash_manifest(trash_root, {})
        return OperationResult(success=True, message="Trash emptied.")

    def _unlink_path(self, target: Path) -> None:
        if target.is_dir():
            shutil.rmtree(target)
        else:
            target.unlink()

    def _reclaim_for_delete(self, target: Path) -> None:
        if hasattr(os, "geteuid") and os.geteuid() != 0:
            raise PermissionError("not privileged")
        uid = int(self._owner_uid) if self._owner_uid is not None else os.geteuid()
        gid = int(self._owner_gid) if self._owner_gid is not None else os.getegid()
        if target.is_dir():
            for child in [target, *target.rglob("*")]:
                try:
                    os.chown(child, uid, gid)
                    mode = child.stat().st_mode
                    os.chmod(child, mode | (stat.S_IWUSR if child.is_file() or child.is_dir() else 0))
                except OSError:
                    continue
        else:
            os.chown(target, uid, gid)
            os.chmod(target, 0o600)

    async def chmod(
        self, path: str, mode: str, *, app_id: str | None = None, root_id: str | None = None
    ) -> OperationResult:
        base = self._resolve_base(app_id, root_id)
        target = self._safe_path(base, path)
        if not target.exists():
            raise NotFoundError("Path not found.")
        try:
            mode_val = int(mode, 8) & 0o7777
        except ValueError:
            raise ValidationError("Invalid octal mode string.", code="invalid_mode")
        if mode_val & 0o6000:
            raise ValidationError("Setuid/setgid permissions are not permitted.", code="forbidden")
        if mode_val & 0o002:
            mode_val = mode_val & ~0o002
        os.chmod(target, mode_val)
        return OperationResult(success=True, message=f"chmod {oct(mode_val)[-3:]} {path}")

    async def upload(
        self, path: str, file: UploadFile, *, app_id: str | None = None, root_id: str | None = None
    ) -> OperationResult:
        base = self._resolve_base(app_id, root_id)
        dest = self._safe_path(base, path)
        filename = safe_upload_basename(file.filename)
        if dest.is_dir():
            target = (dest / filename).resolve()
        else:
            target = (dest.parent / safe_upload_basename(dest.name)).resolve()
        if not any(target == root or target.is_relative_to(root) for root in self.allowed_roots()):
            raise AppException("Path traversal denied.", code="forbidden")
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
        used_base = max(0, used_before - old_bytes)
        limit = (
            limit_bytes(self._storage_limit_gb) if self._storage_limit_gb is not None else None
        )

        target.parent.mkdir(parents=True, exist_ok=True)
        self._apply_owner(target.parent)
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
                    raise ValidationError(
                        "Storage limit reached while uploading. Delete files or upgrade your plan.",
                        code="storage_quota_exceeded",
                    )
                out.write(chunk)
        self._apply_owner(target)
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
        safe_name = safe_upload_basename(filename)
        self._assert_quota(base, extra_bytes=max(int(size_bytes), 0))
        chunk = chunk_size or self._settings.file_upload_chunk_size
        upload_id = str(uuid.uuid4())
        session_dir = self._upload_session_dir(upload_id)
        session_dir.mkdir(parents=True, exist_ok=True)
        total_chunks = max(1, math.ceil(max(int(size_bytes), 1) / chunk))
        meta = {
            "filename": safe_name,
            "path": path,
            "size_bytes": int(size_bytes),
            "chunk_size": chunk,
            "total_chunks": total_chunks,
            "app_id": app_id,
            "root_id": root_id,
            "bound_root": str(self._quota_root(base).resolve()),
        }
        (session_dir / "meta.json").write_text(json.dumps(meta), encoding="utf-8")
        return FileUploadInitResponse(upload_id=upload_id, chunk_size=chunk, total_chunks=total_chunks)

    async def upload_chunk(
        self,
        upload_id: str,
        chunk_index: int,
        data: bytes,
    ) -> OperationResult:
        session_dir = self._upload_session_dir(upload_id)
        meta_path = session_dir / "meta.json"
        if not meta_path.exists():
            raise NotFoundError("Upload session not found or expired.")
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        total_chunks = int(meta.get("total_chunks") or 0)
        if total_chunks and (chunk_index < 0 or chunk_index >= total_chunks):
            raise ValidationError("Chunk index out of range.", code="invalid_chunk")
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
        bound = meta.get("bound_root")
        if bound and bound != str(self._quota_root(base).resolve()):
            raise AppException("Upload session does not match this environment.", code="upload_bound_mismatch")

        dest_dir = self._safe_path(base, meta["path"])
        if not dest_dir.is_dir():
            dest_dir = dest_dir.parent
        filename = safe_upload_basename(meta.get("filename"))
        target = (dest_dir / filename).resolve()
        if not any(target == root or target.is_relative_to(root) for root in self.allowed_roots()):
            raise AppException("Path traversal denied.", code="forbidden")

        expected_size = int(meta.get("size_bytes") or 0)
        total_chunks = int(meta.get("total_chunks") or 0)
        chunks = []
        for index in range(total_chunks or 0):
            chunk_file = session_dir / f"chunk_{index:06d}"
            if not chunk_file.exists():
                raise AppException(f"Missing chunk {index}.", code="upload_incomplete")
            chunks.append(chunk_file)
        if not chunks:
            raise AppException("No chunks received.", code="upload_incomplete")

        old_bytes = 0
        if target.exists() and target.is_file():
            try:
                old_bytes = target.stat().st_size
            except OSError:
                old_bytes = 0
        self._assert_quota(base, extra_bytes=max(expected_size - old_bytes, 0))

        target.parent.mkdir(parents=True, exist_ok=True)
        self._apply_owner(target.parent)
        written = 0
        with target.open("wb") as out:
            for chunk_file in chunks:
                data = chunk_file.read_bytes()
                written += len(data)
                out.write(data)

        if expected_size and written != expected_size:
            try:
                target.unlink(missing_ok=True)
            except OSError:
                pass
            shutil.rmtree(session_dir, ignore_errors=True)
            raise AppException(
                f"Upload size mismatch ({written} != {expected_size}).",
                code="upload_size_mismatch",
            )

        self._apply_owner(target)
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
        # Reject path traversal in upload_id.
        clean = (upload_id or "").strip()
        if not clean or "/" in clean or "\\" in clean or ".." in clean or len(clean) > 80:
            raise ValidationError("Invalid upload id.", code="invalid_upload_id")
        root = Path(self._settings.file_upload_temp_dir)
        if not root.is_absolute():
            root = Path.cwd() / root
        return root / clean

    async def unzip(
        self,
        path: str,
        *,
        app_id: str | None = None,
        root_id: str | None = None,
        destination: str | None = None,
        extract_here: bool = False,
    ) -> OperationResult:
        """Extract a ZIP with zip-slip protection and quota checks.

        - extract_here=True → contents land in the archive's parent folder
        - destination set → relative extract folder under the jail
        - default → sibling folder named after the archive stem
        """
        base = self._resolve_base(app_id, root_id)
        target = self._safe_path(base, path)
        if not target.is_file() or target.suffix.lower() != ".zip":
            raise AppException("Only .zip archives can be extracted.", code="invalid_archive")

        if destination:
            dest = self._safe_path(base, destination)
        elif extract_here:
            dest = target.parent
        else:
            dest = self._safe_path(base, str(target.parent.relative_to(base) / target.stem) if target.parent != base else target.stem)

        return await asyncio.to_thread(self._extract_zip_sync, base, target, dest)

    def _extract_zip_sync(self, base: Path, archive: Path, dest: Path) -> OperationResult:
        dest.mkdir(parents=True, exist_ok=True)
        self._apply_owner(dest)
        with zipfile.ZipFile(archive, "r") as zf:
            # Validate every member first, then compute projected size.
            members = list(zf.infolist())
            projected = 0
            for info in members:
                zip_member_is_safe(info.filename, dest)
                if not info.is_dir():
                    projected += max(int(info.file_size or 0), 0)
            self._assert_quota(base, extra_bytes=projected)

            for info in members:
                member_dest = zip_member_is_safe(info.filename, dest)
                if info.is_dir():
                    member_dest.mkdir(parents=True, exist_ok=True)
                    self._apply_owner(member_dest)
                    continue
                member_dest.parent.mkdir(parents=True, exist_ok=True)
                with zf.open(info, "r") as src, member_dest.open("wb") as out:
                    shutil.copyfileobj(src, out, length=1024 * 1024)
                self._apply_owner(member_dest)
                # Re-verify after write in case of race / odd zip metadata.
                zip_member_is_safe(info.filename, dest)

        return OperationResult(success=True, message=f"Extracted to {dest.relative_to(base)}")

    async def compress(
        self,
        paths: list[str],
        *,
        archive_name: str | None = None,
        destination_dir: str | None = None,
        app_id: str | None = None,
        root_id: str | None = None,
    ) -> OperationResult:
        """Create a ZIP from one or more paths inside the jail."""
        if not paths:
            raise ValidationError("Select at least one file or folder.", code="empty_selection")
        base = self._resolve_base(app_id, root_id)
        sources = [self._safe_path(base, p) for p in paths]
        for src in sources:
            if not src.exists():
                raise NotFoundError(f"Path not found: {src.relative_to(base)}")

        dest_dir = self._safe_path(base, destination_dir or ".")
        if not dest_dir.is_dir():
            dest_dir = dest_dir.parent
        name = safe_upload_basename(archive_name or f"{sources[0].stem}.zip")
        if not name.lower().endswith(".zip"):
            name = f"{name}.zip"
        archive_path = (dest_dir / name).resolve()
        if not any(archive_path == root or archive_path.is_relative_to(root) for root in self.allowed_roots()):
            raise AppException("Path traversal denied.", code="forbidden")

        # Rough upper bound: sum of source sizes (ZIP usually smaller).
        projected = sum(self._path_size_bytes(s) for s in sources)
        self._assert_quota(base, extra_bytes=projected)

        def _build() -> None:
            dest_dir.mkdir(parents=True, exist_ok=True)
            self._apply_owner(dest_dir)
            with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
                for src in sources:
                    if src.is_dir():
                        for child in src.rglob("*"):
                            if child.is_symlink():
                                continue
                            if child.is_file():
                                arcname = str(child.relative_to(src.parent))
                                zf.write(child, arcname=arcname)
                    else:
                        zf.write(src, arcname=src.name)
            self._apply_owner(archive_path)

        await asyncio.to_thread(_build)
        return OperationResult(
            success=True,
            message=f"Created archive {archive_path.relative_to(base)}",
        )

    async def stat_file(
        self, path: str, *, app_id: str | None = None, root_id: str | None = None
    ) -> FileDetailSchema:
        base = self._resolve_base(app_id, root_id)
        target = self._safe_path(base, path)
        if not target.exists():
            raise NotFoundError("Path not found.")
        return self._file_detail(target, base)

    @staticmethod
    def _path_size_bytes(path: Path) -> int:
        if path.is_file():
            try:
                return int(path.stat().st_size)
            except OSError:
                return 0
        total = 0
        if path.is_dir():
            for child in path.rglob("*"):
                if child.is_file() and not child.is_symlink():
                    try:
                        total += int(child.stat().st_size)
                    except OSError:
                        continue
        return total

    def _apply_owner(self, path: Path) -> None:
        if self._owner_uid is None or self._owner_gid is None:
            return
        if hasattr(os, "geteuid") and os.geteuid() != 0:
            return
        try:
            os.chown(path, int(self._owner_uid), int(self._owner_gid))
        except OSError:
            pass

    def _apply_owner_tree(self, path: Path) -> None:
        self._apply_owner(path)
        if not path.is_dir():
            return
        for child in path.rglob("*"):
            self._apply_owner(child)

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

        # 1. Clean raw string
        raw = (path or ".").replace("\x00", "").strip()
        raw = raw.replace("\\", "/")

        # 2. Check for malicious traversal
        if "%2e" in raw.lower() or "/.." in raw or "../" in raw or raw == "..":
            raise AppException("Path traversal denied.", code="forbidden")
        if len(raw) >= 2 and raw[1] == ":":
            raise AppException("Path traversal denied.", code="forbidden")

        # Strip leading slashes to convert virtual root "/folder" into relative "folder"
        clean = raw.lstrip("/")
        if not clean or clean in {".", "./"}:
            clean = "."

        # Check Path parts for ..
        p_obj = Path(clean)
        if any(part == ".." for part in p_obj.parts):
            raise AppException("Path traversal denied.", code="forbidden")

        # 3. Handle document root alias (e.g. if requested 'public' or 'public_html' when base IS public_html)
        if clean in {"public", "public_html", "web"} and not (base / clean).exists():
            clean = "."

        target = (base / clean).resolve()

        # 4. Strict tenant jail: target must be inside base (and within allowed roots)
        if not (target == base or target.is_relative_to(base)):
            raise AppException("Path traversal denied.", code="forbidden")
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
