"""Customer site Git (cPanel Version Control analogue) — clone / pull inside document root."""

from __future__ import annotations

import shutil
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.exceptions import AppException, ConflictError, ValidationError
from app.core.logging import get_logger
from app.models.platform import CustomerEnvironment
from app.services.applications.git_util import run_git
from app.services.monitoring.subprocess_util import run_command
from app.services.platform.fs_ownership import fix_web_ownership

logger = get_logger(__name__)


class EnvironmentGitService:
    def __init__(self, settings: Settings, session: AsyncSession) -> None:
        self._settings = settings
        self._session = session

    def _root(self, env: CustomerEnvironment) -> Path:
        if not env.document_root:
            raise ValidationError("This site has no folder yet.")
        root = Path(env.document_root).resolve()
        base = Path(self._settings.customer_environments_root).resolve()
        if base.exists() and not str(root).startswith(str(base)):
            raise AppException("Site folder is outside the customer area.")
        return root

    async def status(self, env: CustomerEnvironment) -> dict:
        root = self._root(env)
        if not (root / ".git").is_dir():
            return {
                "environment_id": str(env.id),
                "configured": False,
                "path": str(root),
                "message": "No Git repository in this site folder yet. Clone a remote repo below.",
            }
        _, branch, _ = await run_git(root, "rev-parse", "--abbrev-ref", "HEAD")
        _, commit, _ = await run_git(root, "rev-parse", "--short", "HEAD")
        _, remote, _ = await run_git(root, "config", "--get", "remote.origin.url")
        _, dirty_out, _ = await run_git(root, "status", "--porcelain")
        return {
            "environment_id": str(env.id),
            "configured": True,
            "path": str(root),
            "branch": (branch or "").strip() or None,
            "commit": (commit or "").strip() or None,
            "remote": (remote or "").strip() or None,
            "dirty": bool((dirty_out or "").strip()),
            "message": "Git is ready. Pull updates from the remote when you need them.",
        }

    async def clone(self, env: CustomerEnvironment, *, repo_url: str, branch: str | None = None) -> dict:
        from app.models.platform import HostingPlan, Subscription
        from app.services.platform.plan_matrix import feature_included, features_for, pack_denied_message

        sub = await self._session.get(Subscription, env.subscription_id)
        plan = await self._session.get(HostingPlan, sub.plan_id) if sub else None
        if not feature_included(plan, "git"):
            raise ValidationError(pack_denied_message("Git"))
        repos_cap = features_for(plan).get("repos")
        if repos_cap == 0:
            raise ValidationError(pack_denied_message("Git"))

        url = (repo_url or "").strip()
        if not url.startswith(("https://", "git@")):
            raise ValidationError("Use an https:// or git@ repository URL.")
        if any(ch.isspace() for ch in url):
            raise ValidationError("Invalid repository URL.")
        root = self._root(env)
        if (root / ".git").is_dir():
            raise ConflictError(
                "This site already has a Git repository. Pull instead of cloning."
                + (" This package allows 1 repository." if repos_cap == 1 else "")
            )
        entries = [p for p in root.iterdir() if p.name not in {".", ".."}]
        meaningful = [
            p
            for p in entries
            if p.name not in {"index.html", ".well-known", "favicon.ico"}
        ]
        if meaningful:
            raise ValidationError(
                "Site folder is not empty. Clear files first, or use Pull if Git is already set up."
            )
        tmp = root.parent / f".git-clone-{env.id.hex[:8]}"
        if tmp.exists():
            shutil.rmtree(tmp)
        cmd = ["git", "clone", "--depth", "1"]
        if branch and branch.strip():
            cmd += ["--branch", branch.strip()]
        cmd += [url, str(tmp)]
        code, out, err = await run_command(*cmd, timeout=180)
        if code != 0:
            shutil.rmtree(tmp, ignore_errors=True)
            raise AppException((err or out or "Git clone failed")[-400:])
        for item in tmp.iterdir():
            dest = root / item.name
            if dest.exists():
                if dest.is_dir():
                    shutil.rmtree(dest)
                else:
                    dest.unlink()
            shutil.move(str(item), str(dest))
        shutil.rmtree(tmp, ignore_errors=True)
        fix_web_ownership(root, user=self._settings.web_run_user)
        logger.info("env_git_cloned", environment_id=str(env.id), url=url)
        return await self.status(env)

    async def pull(self, env: CustomerEnvironment) -> dict:
        root = self._root(env)
        if not (root / ".git").is_dir():
            raise ValidationError("No Git repository yet. Clone one first.")
        code, out, err = await run_git(root, "pull", "--ff-only", timeout=120)
        if code != 0:
            raise AppException((err or out or "Git pull failed")[-400:])
        fix_web_ownership(root, user=self._settings.web_run_user)
        status = await self.status(env)
        status["message"] = "Pulled latest changes."
        return status
