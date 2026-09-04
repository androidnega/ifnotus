"""Unit tests for Customer File Manager path resolution, virtual root mapping, and tenant isolation."""

from __future__ import annotations

import os
from pathlib import Path
import pytest

from app.core.config import Environment, Settings
from app.core.exceptions import AppException, NotFoundError, ValidationError
from app.services.hosting.files import FileManagerService


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


@pytest.mark.asyncio
async def test_file_manager_root_maps_to_document_root(tmp_path: Path, settings: Settings) -> None:
    docroot = tmp_path / "public_html"
    docroot.mkdir()
    (docroot / "index.html").write_text("<h1>Hello</h1>")
    (docroot / "assets").mkdir()
    (docroot / "assets" / "style.css").write_text("body { color: red; }")

    fm = FileManagerService(settings, only_roots=[docroot], storage_limit_gb=10)

    # 1. Root listing with "."
    res_dot = await fm.list_files(".")
    assert res_dot.path == "."
    names = [e.name for e in res_dot.entries]
    assert "index.html" in names
    assert "assets" in names

    # 2. Root listing with "/"
    res_slash = await fm.list_files("/")
    assert res_slash.path == "."
    assert len(res_slash.entries) == len(res_dot.entries)

    # 3. Root listing with ""
    res_empty = await fm.list_files("")
    assert res_empty.path == "."

    # 4. Subfolder listing
    res_assets = await fm.list_files("assets")
    assert res_assets.path == "assets"
    assert res_assets.parent == "."
    assert any(e.name == "style.css" for e in res_assets.entries)


@pytest.mark.asyncio
async def test_public_alias_normalization_if_legacy(tmp_path: Path, settings: Settings) -> None:
    docroot = tmp_path / "public_html"
    docroot.mkdir()
    (docroot / "index.html").write_text("<h1>Hello</h1>")

    fm = FileManagerService(settings, only_roots=[docroot], storage_limit_gb=10)

    # When requesting "public" or "public_html" and no such subfolder exists, it maps safely to root
    res_public = await fm.list_files("public")
    assert res_public.path == "."
    assert any(e.name == "index.html" for e in res_public.entries)

    res_public_html = await fm.list_files("public_html")
    assert res_public_html.path == "."


@pytest.mark.asyncio
async def test_nonexistent_folder_returns_clean_404(tmp_path: Path, settings: Settings) -> None:
    docroot = tmp_path / "public_html"
    docroot.mkdir()

    fm = FileManagerService(settings, only_roots=[docroot], storage_limit_gb=10)

    with pytest.raises(NotFoundError) as exc:
        await fm.list_files("nonexistent_folder_xyz")
    assert "Path not found" in str(exc.value)


@pytest.mark.asyncio
async def test_path_traversal_denied(tmp_path: Path, settings: Settings) -> None:
    docroot = tmp_path / "public_html"
    docroot.mkdir()
    secret = tmp_path / "secret.txt"
    secret.write_text("SUPER_SECRET")

    fm = FileManagerService(settings, only_roots=[docroot], storage_limit_gb=10)

    for bad_path in ["..", "../", "../../secret.txt", "%2e%2e", "%2e%2e/secret.txt", "sub/../../secret.txt"]:
        with pytest.raises(AppException) as exc:
            await fm.list_files(bad_path)
        assert exc.value.code == "forbidden"


@pytest.mark.asyncio
async def test_symlink_escape_denied(tmp_path: Path, settings: Settings) -> None:
    docroot = tmp_path / "public_html"
    docroot.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "passwords.txt").write_text("passwords")

    symlink_dir = docroot / "evil_link"
    try:
        os.symlink(outside, symlink_dir)
    except OSError:
        pytest.skip("Symlink creation not permitted in this test environment")

    fm = FileManagerService(settings, only_roots=[docroot], storage_limit_gb=10)

    with pytest.raises(AppException) as exc:
        await fm.list_files("evil_link")
    assert exc.value.code == "forbidden"


@pytest.mark.asyncio
async def test_ifnotus_metadata_hidden_for_customer(tmp_path: Path, settings: Settings) -> None:
    docroot = tmp_path / "public_html"
    docroot.mkdir()
    (docroot / ".ifnotus").mkdir()
    (docroot / ".ifnotus" / "stack.json").write_text("{}")
    (docroot / "index.html").write_text("<h1>Hello</h1>")

    # Customer tenant mode (only_roots is set)
    customer_fm = FileManagerService(settings, only_roots=[docroot], storage_limit_gb=10)
    res_cust = await customer_fm.list_files(".")
    names_cust = [e.name for e in res_cust.entries]
    assert ".ifnotus" not in names_cust
    assert "index.html" in names_cust

    # Staff mode (admin_storage)
    staff_fm = FileManagerService(settings, only_roots=[docroot], admin_storage=True)
    res_staff = await staff_fm.list_files(".")
    names_staff = [e.name for e in res_staff.entries]
    assert ".ifnotus" in names_staff


@pytest.mark.asyncio
async def test_list_files_skips_broken_symlink(tmp_path: Path, settings: Settings) -> None:
    docroot = tmp_path / "public_html"
    docroot.mkdir()
    (docroot / "ok.txt").write_text("hello")
    try:
        (docroot / "broken").symlink_to(tmp_path / "missing-target")
    except OSError:
        pytest.skip("Symlink creation not permitted in this test environment")

    fm = FileManagerService(settings, only_roots=[docroot], storage_limit_gb=10)
    res = await fm.list_files(".")
    names = [e.name for e in res.entries]
    assert "ok.txt" in names
    assert "broken" not in names


@pytest.mark.asyncio
async def test_compress_symlink_destination(tmp_path: Path, settings: Settings) -> None:
    docroot = tmp_path / "public_html"
    docroot.mkdir()
    real = docroot / "ExamFlowPro"
    real.mkdir()
    (real / "hello.txt").write_text("hi")
    try:
        (docroot / "examsflow").symlink_to("ExamFlowPro")
    except OSError:
        pytest.skip("Symlink creation not permitted in this test environment")

    fm = FileManagerService(settings, only_roots=[tmp_path], storage_limit_gb=10)
    result = await fm.compress(
        ["public_html/ExamFlowPro/hello.txt"],
        destination_dir="public_html/examsflow",
    )
    assert result.success
    assert (docroot / "ExamFlowPro" / "hello.zip").exists()


@pytest.mark.asyncio
async def test_chmod_security_policy(tmp_path: Path, settings: Settings) -> None:
    docroot = tmp_path / "public_html"
    docroot.mkdir()
    f = docroot / "script.php"
    f.write_text("<?php echo 'ok';")

    fm = FileManagerService(settings, only_roots=[docroot], storage_limit_gb=10)

    # 1. Normal valid chmod
    res = await fm.chmod("script.php", "644")
    assert res.success is True

    # 2. Block setuid
    with pytest.raises(ValidationError):
        await fm.chmod("script.php", "4755")

    # 3. Sanitizes world-writable 777 to non-world-writable 775
    res777 = await fm.chmod("script.php", "777")
    assert res777.success is True
    assert "chmod 775" in res777.message


@pytest.mark.asyncio
async def test_delete_moves_file_to_trash(tmp_path: Path, settings: Settings) -> None:
    docroot = tmp_path / "public_html"
    docroot.mkdir()
    (docroot / "test.txt").write_text("Hello Trash")

    fm = FileManagerService(settings, only_roots=[docroot], storage_limit_gb=10)

    # 1. Normal delete moves to trash
    res = await fm.delete("test.txt", permanent=False)
    assert res.success is True
    assert "Moved" in res.message
    assert not (docroot / "test.txt").exists()

    # 2. Item is listed in trash
    trash = await fm.list_trash()
    assert trash.count == 1
    assert trash.entries[0].display_name == "test.txt"
    assert trash.entries[0].original_path == "test.txt"
    assert trash.entries[0].item_type == "file"


@pytest.mark.asyncio
async def test_delete_moves_folder_to_trash(tmp_path: Path, settings: Settings) -> None:
    docroot = tmp_path / "public_html"
    docroot.mkdir()
    assets = docroot / "assets"
    assets.mkdir()
    (assets / "logo.png").write_bytes(b"PNGDATA")

    fm = FileManagerService(settings, only_roots=[docroot], storage_limit_gb=10)

    res = await fm.delete("assets", permanent=False)
    assert res.success is True
    assert not assets.exists()

    trash = await fm.list_trash()
    assert trash.count == 1
    assert trash.entries[0].display_name == "assets"
    assert trash.entries[0].item_type == "dir"


@pytest.mark.asyncio
async def test_restore_returns_to_original_path(tmp_path: Path, settings: Settings) -> None:
    docroot = tmp_path / "public_html"
    docroot.mkdir()
    images = docroot / "images"
    images.mkdir()
    (images / "photo.jpg").write_text("IMAGE_BYTES")

    fm = FileManagerService(settings, only_roots=[docroot], storage_limit_gb=10)

    await fm.delete("images/photo.jpg", permanent=False)
    assert not (images / "photo.jpg").exists()

    trash = await fm.list_trash()
    assert trash.count == 1
    trash_id = trash.entries[0].trash_id

    # Restore item
    restored = await fm.restore_from_trash(trash_id)
    assert restored.success is True
    assert (images / "photo.jpg").exists()
    assert (images / "photo.jpg").read_text() == "IMAGE_BYTES"

    # Trash is now empty
    trash_after = await fm.list_trash()
    assert trash_after.count == 0


@pytest.mark.asyncio
async def test_restore_conflict_does_not_overwrite(tmp_path: Path, settings: Settings) -> None:
    docroot = tmp_path / "public_html"
    docroot.mkdir()
    (docroot / "config.php").write_text("ORIGINAL")

    fm = FileManagerService(settings, only_roots=[docroot], storage_limit_gb=10)

    await fm.delete("config.php", permanent=False)
    trash = await fm.list_trash()
    trash_id = trash.entries[0].trash_id

    # Recreate config.php in the original location
    (docroot / "config.php").write_text("NEW_CONTENT")

    # 1. Conflict mode "cancel" raises ValidationError
    with pytest.raises(ValidationError) as exc:
        await fm.restore_from_trash(trash_id, conflict_mode="cancel")
    assert exc.value.code == "conflict"
    assert (docroot / "config.php").read_text() == "NEW_CONTENT"

    # 2. Conflict mode "copy" creates copy without overwriting
    res_copy = await fm.restore_from_trash(trash_id, conflict_mode="copy")
    assert res_copy.success is True
    assert (docroot / "config.php").read_text() == "NEW_CONTENT"
    assert (docroot / "config (restored).php").exists()
    assert (docroot / "config (restored).php").read_text() == "ORIGINAL"


@pytest.mark.asyncio
async def test_permanent_delete_and_empty_trash(tmp_path: Path, settings: Settings) -> None:
    docroot = tmp_path / "public_html"
    docroot.mkdir()
    (docroot / "file1.txt").write_text("1")
    (docroot / "file2.txt").write_text("2")

    fm = FileManagerService(settings, only_roots=[docroot], storage_limit_gb=10)

    await fm.delete("file1.txt", permanent=False)
    await fm.delete("file2.txt", permanent=False)

    trash = await fm.list_trash()
    assert trash.count == 2

    # Permanent delete of one item
    await fm.permanent_delete_trash(trash.entries[0].trash_id)
    trash_mid = await fm.list_trash()
    assert trash_mid.count == 1

    # Empty trash
    await fm.empty_trash()
    trash_end = await fm.list_trash()
    assert trash_end.count == 0


@pytest.mark.asyncio
async def test_cross_tenant_trash_isolation(tmp_path: Path, settings: Settings) -> None:
    tenant_a_root = tmp_path / "tenant_a" / "public_html"
    tenant_a_root.mkdir(parents=True)
    (tenant_a_root / "secret_a.txt").write_text("A_SECRET")

    tenant_b_root = tmp_path / "tenant_b" / "public_html"
    tenant_b_root.mkdir(parents=True)
    (tenant_b_root / "secret_b.txt").write_text("B_SECRET")

    fm_a = FileManagerService(settings, only_roots=[tenant_a_root], storage_limit_gb=10)
    fm_b = FileManagerService(settings, only_roots=[tenant_b_root], storage_limit_gb=10)

    await fm_a.delete("secret_a.txt", permanent=False)
    trash_a = await fm_a.list_trash()
    assert trash_a.count == 1
    trash_id_a = trash_a.entries[0].trash_id

    # Tenant B cannot see or restore Tenant A's trash item
    trash_b = await fm_b.list_trash()
    assert trash_b.count == 0

    with pytest.raises(NotFoundError):
        await fm_b.restore_from_trash(trash_id_a)

    with pytest.raises(NotFoundError):
        await fm_b.permanent_delete_trash(trash_id_a)

