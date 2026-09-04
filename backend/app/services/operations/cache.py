"""Server and application cache refresh / clear operations."""

from __future__ import annotations

import asyncio
import shutil
from pathlib import Path
from typing import Any

from app.core.config import Settings
from app.core.logging import get_logger
from app.repositories.applications import ApplicationRepository
from app.schemas.applications import ApplicationType
from app.schemas.operations import OperationResult
from app.services.applications.config import ApplicationDefinition
from app.services.hosting.nginx_sites import NginxSiteManager
from app.services.monitoring.subprocess_util import resolve_binary

logger = get_logger(__name__)

SAFE_CACHE_DIR_NAMES = {
    "cache",
    ".cache",
    "tmp",
    "temp",
    ".tmp",
    "bootstrap/cache",
    "storage/framework/cache",
    "storage/framework/views",
    "storage/framework/sessions",
    "storage/logs",
    ".next/cache",
    "node_modules/.cache",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    "var/cache",
}

CLEARABLE_SCAN_PATHS = [
    ("tmp", "tmp"),
    ("temp", "temp"),
    (".tmp", ".tmp"),
    ("cache", "cache"),
    (".cache", ".cache"),
    ("bootstrap/cache", "Laravel bootstrap cache"),
    ("storage/framework/cache", "Laravel framework cache"),
    ("storage/framework/cache/data", "Laravel cache data"),
    ("storage/framework/views", "Laravel compiled views"),
    ("storage/framework/sessions", "Laravel sessions"),
    ("storage/logs", "Application logs"),
    (".next/cache", "Next.js cache"),
    ("node_modules/.cache", "Node module cache"),
    ("var/cache", "Var cache"),
    (".pytest_cache", "Pytest cache"),
    (".mypy_cache", "Mypy cache"),
]


def _dir_size_bytes(path: Path) -> int:
    total = 0
    try:
        if path.is_file():
            return path.stat().st_size
        for child in path.rglob("*"):
            try:
                if child.is_file():
                    total += child.stat().st_size
            except OSError:
                continue
    except OSError:
        return 0
    return total


def measure_clearable_paths(root: Path) -> tuple[list, int]:
    """Return clearable cache/temp paths under an app root and total bytes."""
    from app.schemas.applications import ClearablePathSchema

    if not root.exists():
        return [], 0
    root = root.resolve()
    found: list[ClearablePathSchema] = []
    total = 0
    seen: set[str] = set()

    for rel, label in CLEARABLE_SCAN_PATHS:
        target = (root / rel).resolve()
        try:
            target.relative_to(root)
        except ValueError:
            continue
        if not target.exists():
            continue
        key = str(target)
        if key in seen:
            continue
        seen.add(key)
        size = _dir_size_bytes(target)
        if size <= 0:
            continue
        found.append(ClearablePathSchema(path=rel, label=label, bytes=size))
        total += size

    # Bounded __pycache__ scan (cap visited nodes).
    pycache_bytes = 0
    visited = 0
    try:
        for path in root.rglob("__pycache__"):
            visited += 1
            if visited > 400:
                break
            if path.is_dir():
                pycache_bytes += _dir_size_bytes(path)
    except OSError:
        pass
    if pycache_bytes > 0:
        found.append(
            ClearablePathSchema(path="**/__pycache__", label="Python bytecode caches", bytes=pycache_bytes)
        )
        total += pycache_bytes

    found.sort(key=lambda p: p.bytes, reverse=True)
    return found, total


class CacheOperationsService:
    """Clear platform and application caches; refresh live server state."""

    def __init__(self, settings: Settings, monitoring: Any | None = None) -> None:
        self._settings = settings
        self._monitoring = monitoring
        self._apps = ApplicationRepository(settings)
        self._nginx = NginxSiteManager(settings)

    async def refresh_server(self, *, reload_nginx: bool = True) -> OperationResult:
        """Clear monitoring/redis caches, reload registry, optionally reload nginx."""
        details = await self._clear_central(reload_nginx=reload_nginx)
        ok = True
        messages = ["Server refreshed."]
        if details.get("nginx") and not details["nginx"].get("success", True):
            ok = False
            messages.append(f"Nginx: {details['nginx'].get('message')}")
        return OperationResult(success=ok, message=" ".join(messages), details=details)

    async def clear_central(self, *, reload_nginx: bool = False) -> OperationResult:
        details = await self._clear_central(reload_nginx=reload_nginx)
        return OperationResult(
            success=True,
            message="Central server cache cleared.",
            details=details,
        )

    async def clear_app(self, app_id: str) -> OperationResult:
        app = self._apps.get(app_id)
        before_paths, before_bytes = measure_clearable_paths(Path(app.paths.root))
        steps = await self._clear_app_caches(app)
        after_paths, after_bytes = measure_clearable_paths(Path(app.paths.root))
        freed = max(0, before_bytes - after_bytes)
        failed = [s for s in steps if not s.get("success")]
        return OperationResult(
            success=len(failed) == 0,
            message=(
                f"Cache cleared for '{app_id}' (≈{freed / (1024 * 1024):.1f} MB freed)."
                if not failed
                else f"Cache clear for '{app_id}' finished with {len(failed)} issue(s)."
            ),
            details={
                "app_id": app_id,
                "steps": steps,
                "clearable_before_bytes": before_bytes,
                "clearable_after_bytes": after_bytes,
                "bytes_freed": freed,
                "paths_before": [p.model_dump() for p in before_paths],
            },
        )

    async def clear_all_apps(self) -> OperationResult:
        results: list[dict[str, Any]] = []
        for app in self._apps.list_all():
            if not app.enabled:
                continue
            try:
                steps = await self._clear_app_caches(app)
                results.append({"app_id": app.id, "success": all(s.get("success") for s in steps), "steps": steps})
            except Exception as exc:  # noqa: BLE001
                results.append({"app_id": app.id, "success": False, "error": str(exc)})
        failed = sum(1 for r in results if not r.get("success"))
        return OperationResult(
            success=failed == 0,
            message=f"Cleared caches for {len(results)} app(s); {failed} with issues.",
            details={"apps": results},
        )

    async def _clear_central(self, *, reload_nginx: bool) -> dict[str, Any]:
        details: dict[str, Any] = {}

        if self._monitoring is not None:
            try:
                details["monitoring_cache"] = self._monitoring.clear_cache()
            except Exception as exc:  # noqa: BLE001
                details["monitoring_cache"] = {"error": str(exc)}

        details["redis"] = await self._clear_redis_namespace()
        details["php_opcache"] = await self._clear_php_opcache()

        apps = self._apps.reload()
        details["applications_reloaded"] = len(apps)

        if reload_nginx:
            nginx_result = await self._nginx.reload()
            details["nginx"] = {
                "success": nginx_result.success,
                "message": nginx_result.message,
            }

        return details

    async def _clear_redis_namespace(self) -> dict[str, Any]:
        try:
            from redis.asyncio import Redis

            redis = Redis.from_url(str(self._settings.redis_url), decode_responses=True)
            deleted = 0
            async for key in redis.scan_iter(match="ifnotus:cache:*", count=200):
                await redis.delete(key)
                deleted += 1
            await redis.aclose()
            return {"success": True, "deleted_keys": deleted}
        except Exception as exc:  # noqa: BLE001
            return {"success": False, "error": str(exc)}

    async def _run(self, *args: str, cwd: Path | None = None, timeout: float = 60) -> tuple[int, str, str]:
        proc = await asyncio.create_subprocess_exec(
            *args,
            cwd=str(cwd) if cwd else None,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except TimeoutError:
            proc.kill()
            await proc.communicate()
            return 1, "", "timeout"
        return proc.returncode or 0, stdout.decode().strip(), stderr.decode().strip()

    async def _clear_laravel(self, root: Path) -> list[dict[str, Any]]:
        artisan = root / "artisan"
        php = resolve_binary("php")
        if not artisan.exists() or not php:
            return [await self._clear_named_dirs(root, ["bootstrap/cache", "storage/framework/cache", "storage/framework/views"])]

        steps: list[dict[str, Any]] = []
        for cmd in ("optimize:clear", "cache:clear", "config:clear", "route:clear", "view:clear"):
            code, stdout, stderr = await self._run(php, "artisan", cmd, cwd=root, timeout=90)
            steps.append(
                {
                    "action": f"artisan {cmd}",
                    "success": code == 0,
                    "message": (stdout or stderr or "")[:300],
                }
            )
        return steps

    async def _clear_django(self, root: Path) -> list[dict[str, Any]]:
        manage = root / "manage.py"
        python = resolve_binary("python3") or resolve_binary("python")
        steps: list[dict[str, Any]] = []
        if manage.exists() and python:
            code, stdout, stderr = await self._run(
                python, "manage.py", "clear_cache", cwd=root, timeout=60
            )
            if code == 0:
                steps.append({"action": "manage.py clear_cache", "success": True, "message": stdout[:300]})
            else:
                steps.append(
                    {
                        "action": "manage.py clear_cache",
                        "success": True,
                        "skipped": True,
                        "message": (stderr or stdout or "command unavailable")[:300],
                    }
                )
        steps.append(await self._clear_python(root))
        return steps

    async def _clear_php_opcache(self) -> dict[str, Any]:
        php = resolve_binary("php")
        if not php:
            return {"success": True, "skipped": True, "reason": "php not found"}
        code, stdout, stderr = await self._run(
            php,
            "-r",
            "echo function_exists('opcache_reset') && opcache_reset() ? 'ok' : 'noop';",
            timeout=15,
        )
        return {
            "success": code == 0,
            "output": stdout or stderr,
        }

    async def _clear_app_caches(self, app: ApplicationDefinition) -> list[dict[str, Any]]:
        root = Path(app.paths.root)
        if not root.exists():
            return [{"action": "root", "success": False, "message": f"Root missing: {root}"}]

        steps: list[dict[str, Any]] = []
        app_type = app.type if isinstance(app.type, ApplicationType) else ApplicationType(str(app.type))

        if app_type == ApplicationType.LARAVEL:
            steps.extend(await self._clear_laravel(root))
        elif app_type == ApplicationType.DJANGO:
            steps.extend(await self._clear_django(root))
        elif app_type == ApplicationType.FASTAPI:
            steps.append(await self._clear_python(root))
        elif app_type == ApplicationType.NODEJS:
            steps.extend(await self._clear_nodejs(root))
        else:
            steps.append(await self._clear_named_dirs(root, ["cache", ".cache", "tmp"]))

        steps.append(
            await self._clear_named_dirs(
                root,
                [
                    "bootstrap/cache",
                    "storage/framework/cache/data",
                    "storage/framework/views",
                    ".next/cache",
                    "node_modules/.cache",
                    "var/cache",
                    "__pycache__",
                ],
            )
        )
        return steps

    async def _clear_python(self, root: Path) -> dict[str, Any]:
        removed = 0

        def _walk() -> int:
            count = 0
            for path in root.rglob("__pycache__"):
                if path.is_dir():
                    shutil.rmtree(path, ignore_errors=True)
                    count += 1
            for path in root.rglob("*.pyc"):
                try:
                    path.unlink(missing_ok=True)
                    count += 1
                except OSError:
                    pass
            return count

        removed = await asyncio.to_thread(_walk)
        return {"action": "python bytecode", "success": True, "removed": removed}

    async def _clear_nodejs(self, root: Path) -> list[dict[str, Any]]:
        return [
            await self._clear_named_dirs(
                root,
                [".next/cache", "node_modules/.cache", ".nuxt", ".output", "dist/.cache", ".vite"],
            )
        ]

    async def _clear_named_dirs(self, root: Path, relative_paths: list[str]) -> dict[str, Any]:
        cleared: list[str] = []
        errors: list[str] = []

        def _clear() -> None:
            for rel in relative_paths:
                target = (root / rel).resolve()
                try:
                    # Stay inside app root
                    target.relative_to(root.resolve())
                except ValueError:
                    errors.append(f"refused outside root: {rel}")
                    continue
                if not target.exists():
                    continue
                try:
                    if target.is_dir():
                        # Only wipe known cache folder names / paths
                        name = target.name.lower()
                        if (
                            rel.replace("\\", "/") in SAFE_CACHE_DIR_NAMES
                            or name in {"cache", ".cache", "tmp", "temp", "__pycache__", "views", "sessions", "data"}
                            or any(part in {"cache", ".cache", "__pycache__"} for part in target.parts)
                        ):
                            for child in target.iterdir():
                                if child.is_dir():
                                    shutil.rmtree(child, ignore_errors=True)
                                else:
                                    child.unlink(missing_ok=True)
                            cleared.append(rel)
                        else:
                            errors.append(f"skipped unsafe dir: {rel}")
                    elif target.is_file() and target.suffix in {".cache", ".tmp"}:
                        target.unlink(missing_ok=True)
                        cleared.append(rel)
                except OSError as exc:
                    errors.append(f"{rel}: {exc}")

        await asyncio.to_thread(_clear)
        return {
            "action": "filesystem caches",
            "success": len(errors) == 0,
            "cleared": cleared,
            "errors": errors,
        }

    async def clear_tenant_docroot(self, root: Path) -> OperationResult:
        """Clear cache/temp folders under a customer site document root.

        Also clears under ``public_html`` when ``root`` is the account home, and
        under the parent home when ``root`` is already ``public_html``.
        """
        site_root = root.resolve()
        if not site_root.exists():
            return OperationResult(success=False, message="Site folder not found.")

        candidates: list[Path] = [site_root]
        if site_root.name in {"public_html", "public", "web"}:
            candidates.append(site_root.parent)
        else:
            ph = site_root / "public_html"
            if ph.is_dir():
                candidates.append(ph)

        before_paths, before_bytes = measure_clearable_paths(site_root)
        from app.services.platform.stacks import detect_stack_from_filesystem

        steps: list[dict[str, Any]] = []
        stacks_seen: list[str] = []

        for candidate in candidates:
            detected = detect_stack_from_filesystem(candidate) or {}
            stack = str(detected.get("stack") or "").lower()
            if stack:
                stacks_seen.append(stack)

            if stack == "laravel":
                steps.extend(await self._clear_laravel(candidate))
            elif stack == "django":
                steps.extend(await self._clear_django(candidate))
            elif stack == "wordpress":
                steps.append(
                    await self._clear_named_dirs(
                        candidate,
                        ["wp-content/cache", "wp-content/uploads/cache", "wp-content/upgrade"],
                    )
                )
            elif stack == "nodejs":
                steps.extend(await self._clear_nodejs(candidate))
            else:
                steps.append(
                    await self._clear_named_dirs(candidate, ["cache", ".cache", "tmp", "temp"])
                )

            steps.append(
                await self._clear_named_dirs(
                    candidate,
                    [
                        "bootstrap/cache",
                        "storage/framework/cache/data",
                        "storage/framework/views",
                        ".next/cache",
                        "node_modules/.cache",
                        "var/cache",
                        "wp-content/cache",
                    ],
                )
            )

        steps.append(await self._clear_php_opcache())

        after_paths, after_bytes = measure_clearable_paths(site_root)
        freed = max(0, before_bytes - after_bytes)
        failed = [s for s in steps if not s.get("success")]
        stack_label = stacks_seen[0] if stacks_seen else None
        return OperationResult(
            success=len(failed) == 0,
            message=(
                f"Site cache cleared (≈{freed / (1024 * 1024):.1f} MB freed)."
                if not failed
                else f"Cache clear finished with {len(failed)} issue(s)."
            ),
            details={
                "stack": stack_label,
                "roots": [str(c) for c in candidates],
                "steps": steps,
                "clearable_before_bytes": before_bytes,
                "clearable_after_bytes": after_bytes,
                "bytes_freed": freed,
                "paths_before": [p.model_dump() for p in before_paths],
            },
        )
