"""Git repository reader."""

from __future__ import annotations

import re
from pathlib import Path

from app.schemas.applications import GitStatusSchema
from app.services.monitoring.subprocess_util import run_command


class GitReader:
    """Reads live Git status from a repository path."""

    async def read(self, repo_path: str | Path | None) -> GitStatusSchema:
        if not repo_path:
            return GitStatusSchema(available=False, message="Git repository not configured.")

        path = Path(repo_path)
        git_dir = path / ".git"
        if not git_dir.exists():
            return GitStatusSchema(available=False, message=f"No git repository at {path}")

        try:
            branch_code, branch_out, _ = await run_command(
                "git", "-C", str(path), "rev-parse", "--abbrev-ref", "HEAD"
            )
            commit_code, commit_out, _ = await run_command(
                "git", "-C", str(path), "rev-parse", "--short", "HEAD"
            )
            msg_code, msg_out, _ = await run_command(
                "git", "-C", str(path), "log", "-1", "--pretty=%s"
            )
            dirty_code, dirty_out, _ = await run_command(
                "git", "-C", str(path), "status", "--porcelain"
            )
            remote_code, remote_out, _ = await run_command(
                "git", "-C", str(path), "remote", "get-url", "origin"
            )

            ahead = behind = None
            ab_code, ab_out, _ = await run_command(
                "git", "-C", str(path), "rev-list", "--left-right", "--count", "@{upstream}...HEAD"
            )
            if ab_code == 0 and ab_out:
                parts = ab_out.split()
                if len(parts) == 2:
                    behind, ahead = int(parts[0]), int(parts[1])

            return GitStatusSchema(
                available=True,
                branch=branch_out if branch_code == 0 else None,
                commit=commit_out if commit_code == 0 else None,
                commit_message=msg_out if msg_code == 0 else None,
                dirty=bool(dirty_out.strip()) if dirty_code == 0 else None,
                remote_url=remote_out if remote_code == 0 else None,
                ahead=ahead,
                behind=behind,
            )
        except Exception as exc:
            return GitStatusSchema(available=False, message=str(exc))
