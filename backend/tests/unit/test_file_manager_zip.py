"""File manager ZIP safety, basename sanitization, and extract quota."""

from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

from app.core.config import Environment, Settings
from app.core.exceptions import ValidationError
from app.services.hosting.files import (
    FileManagerService,
    safe_upload_basename,
    zip_member_is_safe,
)


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    upload = tmp_path / "uploads"
    upload.mkdir()
    return Settings(
        secret_key="test-secret-key-at-least-32-characters-long",
        database_url="postgresql+asyncpg://ifnotus:ifnotus@localhost:5432/ifnotus_test",
        redis_url="redis://localhost:6379/1",
        environment=Environment.TESTING,
        debug=True,
        file_upload_temp_dir=str(upload),
        file_upload_chunk_size=1024,
        hosting_allowed_paths=[],
    )


def test_safe_upload_basename_strips_traversal() -> None:
    assert safe_upload_basename("../../etc/passwd") == "passwd"
    assert safe_upload_basename("foo/bar.zip") == "bar.zip"
    assert safe_upload_basename("") == "upload.bin"
    assert safe_upload_basename("..") == "upload.bin"


def test_zip_member_rejects_slip(tmp_path: Path) -> None:
    dest = tmp_path / "out"
    dest.mkdir()
    with pytest.raises(ValidationError) as exc:
        zip_member_is_safe("../evil.txt", dest)
    assert exc.value.code == "zip_slip"
    with pytest.raises(ValidationError):
        zip_member_is_safe("/tmp/x", dest)
    ok = zip_member_is_safe("ok/file.txt", dest)
    assert ok == (dest / "ok" / "file.txt").resolve()


@pytest.mark.asyncio
async def test_unzip_blocks_zip_slip(tmp_path: Path, settings: Settings) -> None:
    root = tmp_path / "site"
    root.mkdir()
    archive = root / "payload.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("../escape.txt", b"pwned")

    fm = FileManagerService(settings, only_roots=[root], storage_limit_gb=10)
    with pytest.raises(ValidationError) as exc:
        await fm.unzip("payload.zip")
    assert exc.value.code == "zip_slip"
    assert not (tmp_path / "escape.txt").exists()


@pytest.mark.asyncio
async def test_unzip_extract_here_and_folder(tmp_path: Path, settings: Settings) -> None:
    root = tmp_path / "site"
    root.mkdir()
    archive = root / "site.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("index.html", b"<h1>ok</h1>")

    fm = FileManagerService(settings, only_roots=[root], storage_limit_gb=10)
    await fm.unzip("site.zip")
    assert (root / "site" / "index.html").read_bytes() == b"<h1>ok</h1>"

    archive2 = root / "here.zip"
    with zipfile.ZipFile(archive2, "w") as zf:
        zf.writestr("hello.txt", b"hi")
    await fm.unzip("here.zip", extract_here=True)
    assert (root / "hello.txt").read_bytes() == b"hi"


@pytest.mark.asyncio
async def test_compress_creates_zip(tmp_path: Path, settings: Settings) -> None:
    root = tmp_path / "site"
    root.mkdir()
    (root / "a.txt").write_text("a", encoding="utf-8")
    fm = FileManagerService(settings, only_roots=[root], storage_limit_gb=10)
    result = await fm.compress(["a.txt"], archive_name="pack.zip")
    assert result.success
    assert (root / "pack.zip").is_file()
    with zipfile.ZipFile(root / "pack.zip") as zf:
        assert "a.txt" in zf.namelist()


@pytest.mark.asyncio
async def test_chunked_upload_rejects_path_filename(tmp_path: Path, settings: Settings) -> None:
    root = tmp_path / "site"
    root.mkdir()
    fm = FileManagerService(settings, only_roots=[root], storage_limit_gb=10)
    init = await fm.init_chunked_upload("../../evil.txt", ".", 5)
    await fm.upload_chunk(init.upload_id, 0, b"hello")
    result = await fm.complete_chunked_upload(init.upload_id)
    assert result.success
    assert (root / "evil.txt").read_bytes() == b"hello"
    assert not (tmp_path / "evil.txt").exists()


@pytest.mark.asyncio
async def test_copy_and_move(tmp_path: Path, settings: Settings) -> None:
    root = tmp_path / "site"
    root.mkdir()
    (root / "src.txt").write_text("data", encoding="utf-8")
    fm = FileManagerService(settings, only_roots=[root], storage_limit_gb=10)
    await fm.copy("src.txt", "copy.txt")
    assert (root / "copy.txt").read_text(encoding="utf-8") == "data"
    await fm.move("copy.txt", "moved.txt")
    assert (root / "moved.txt").exists()
    assert not (root / "copy.txt").exists()
