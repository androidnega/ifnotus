"""Git Version Control: path safety, clone, fast-forward pull, cleanup."""

from __future__ import annotations

import subprocess
from types import SimpleNamespace
from uuid import uuid4
from pathlib import Path

import pytest

from app.core.config import Environment, Settings
from app.core.exceptions import ValidationError
from app.services.platform.env_git import EnvironmentGitService


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
        customer_environments_root=str(tmp_path / "customers"),
        web_run_user="nobody",
    )


def _env(home: Path) -> SimpleNamespace:
    # Account home under customers/; primary web root may be nested.
    doc = home / "example.test" / "public_html"
    doc.mkdir(parents=True, exist_ok=True)
    return SimpleNamespace(
        id=uuid4(),
        document_root=str(doc),
        hosting_name="attahhost",
        unix_username="ifn_test",
        customer_id=uuid4(),
        domain="example.test",
        subscription_id=uuid4(),
        hosting_domain_id=None,
        ram_limit_gb=0.5,
    )


def _svc(settings: Settings) -> EnvironmentGitService:
    svc = EnvironmentGitService(settings, session=None)  # type: ignore[arg-type]

    async def _cap(_env: object) -> None:
        return None

    svc._plan_cap = _cap  # type: ignore[method-assign]
    return svc


def _git_init_with_file(work: Path, content: str, message: str) -> None:
    work.mkdir(parents=True, exist_ok=True)
    (work / "README.md").write_text(content, encoding="utf-8")
    subprocess.run(["git", "init", "-b", "main"], cwd=work, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "git-test@ifnotus.test"], cwd=work, check=True)
    subprocess.run(["git", "config", "user.name", "Git Test"], cwd=work, check=True)
    subprocess.run(["git", "add", "."], cwd=work, check=True)
    subprocess.run(["git", "commit", "-m", message], cwd=work, check=True)


def test_rejects_unsafe_repository_paths(tmp_path: Path, settings: Settings) -> None:
    home = tmp_path / "customers" / "acct"
    env = _env(home)
    svc = _svc(settings)
    with pytest.raises(ValidationError):
        svc.resolve_requested_path(env, "/home3/attahhost/../etc")
    with pytest.raises(ValidationError):
        svc.resolve_requested_path(env, "/home3/attahhost/my repo")
    with pytest.raises(ValidationError):
        svc.resolve_requested_path(env, "/home3/attahhost/bad;rm")


def test_maps_home3_display_path_into_site_home(tmp_path: Path, settings: Settings) -> None:
    home = tmp_path / "customers" / "acct"
    env = _env(home)
    svc = _svc(settings)
    real, display = svc.resolve_requested_path(env, "/home3/attahhost/apps/_ifnotus_git_smoke")
    assert real == (home / "apps" / "_ifnotus_git_smoke").resolve()
    assert display == "/home3/attahhost/apps/_ifnotus_git_smoke"


def test_allows_custom_folder_outside_public_html(tmp_path: Path, settings: Settings) -> None:
    home = tmp_path / "customers" / "acct"
    env = _env(home)
    svc = _svc(settings)
    real, display = svc.resolve_requested_path(env, "/home3/attahhost/try")
    assert real == (home / "try").resolve()
    assert display == "/home3/attahhost/try"
    # Mangled /home3t/try (missing slash after home3) still maps into the account.
    real2, display2 = svc.resolve_requested_path(env, "/home3t/try")
    assert real2 == (home / "try").resolve()
    assert display2 == "/home3/attahhost/try"


def test_detect_web_root_prefers_index_php(tmp_path: Path) -> None:
    repo = tmp_path / "try"
    repo.mkdir()
    (repo / "index.php").write_text("<?php echo 1;", encoding="utf-8")
    assert EnvironmentGitService.detect_web_root(repo) == repo.resolve()
    laravel = tmp_path / "laravel"
    (laravel / "public").mkdir(parents=True)
    (laravel / "artisan").write_text("#!/usr/bin/env php\n", encoding="utf-8")
    (laravel / "public" / "index.php").write_text("<?php\n", encoding="utf-8")
    assert EnvironmentGitService.detect_web_root(laravel) == (laravel / "public").resolve()


@pytest.mark.asyncio
async def test_clone_pull_fast_forward_then_delete(tmp_path: Path, settings: Settings, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.services.platform.env_git.fix_web_ownership", lambda *a, **k: None)
    monkeypatch.setattr("app.services.platform.fs_ownership.grant_tenant_traverse", lambda *a, **k: None)

    origin = tmp_path / "origin-work"
    _git_init_with_file(origin, "v1\n", "first")

    home = tmp_path / "customers" / "acct"
    env = _env(home)
    svc = _svc(settings)
    dest = "/home3/attahhost/apps/_ifnotus_git_smoke"

    created = await svc.create(
        env,
        name="smoke-test",
        repo_path=dest,
        clone=True,
        repo_url=f"file://{origin}",
        branch="main",
    )
    readme = home / "apps" / "_ifnotus_git_smoke" / "README.md"
    assert readme.read_text(encoding="utf-8") == "v1\n"
    assert created["configured"] or any(r["configured"] for r in created["repositories"])

    (origin / "README.md").write_text("v2\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=origin, check=True)
    subprocess.run(["git", "commit", "-m", "second"], cwd=origin, check=True)

    pulled = await svc.pull(env, repo_path=dest)
    assert readme.read_text(encoding="utf-8") == "v2\n"
    assert "Pulled" in pulled["message"]

    await svc.remove(env, repo_path=dest, delete_files=True)
    assert not (home / "apps" / "_ifnotus_git_smoke").exists()
