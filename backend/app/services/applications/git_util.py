"""Shared helpers for running git against app repositories."""

from __future__ import annotations

from pathlib import Path

from app.services.monitoring.subprocess_util import run_command


async def run_git(repo: Path, *args: str, timeout: int = 60) -> tuple[int, str, str]:
    """Run a git command with safe.directory set for the repo path."""
    path = str(repo.resolve())
    return await run_command(
        "git",
        "-c",
        f"safe.directory={path}",
        "-C",
        path,
        *args,
        timeout=timeout,
    )
