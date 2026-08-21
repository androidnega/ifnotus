"""Live health probes for customer environments."""

from __future__ import annotations

import asyncio
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.logging import get_logger
from app.models.platform import CustomerEnvironment, Notification, PlatformAuditLog
from app.services.platform.enqueue import enqueue_task

logger = get_logger(__name__)

# healthy | degraded | unhealthy | checking | unknown | offline
_ACTIVE_STATUSES = frozenset({"active", "provisioning"})


class EnvironmentHealthService:
    def __init__(self, settings: Settings, session: AsyncSession) -> None:
        self._settings = settings
        self._session = session

    async def probe(self, env: CustomerEnvironment) -> dict[str, Any]:
        """Run checks and persist ``health_status`` on the environment."""
        checks: dict[str, Any] = {}
        previous = env.health_status or "unknown"

        if env.status in {"terminated", "terminating"}:
            status = "offline"
            summary = "Environment is terminated."
        elif env.status == "suspended":
            status = "offline"
            summary = "Environment is suspended."
        elif env.status == "provisioning":
            status = "checking"
            summary = "Still provisioning."
        else:
            status, summary, checks = await self._run_checks(env)

        env.health_status = status
        await self._session.flush()

        # Notify once when an active site flips to unhealthy.
        if (
            previous not in {"unhealthy", "offline"}
            and status == "unhealthy"
            and env.status == "active"
        ):
            self._session.add(
                Notification(
                    customer_id=env.customer_id,
                    title="Site health warning",
                    body=f"{env.domain or env.id} looks unhealthy: {summary}",
                    kind="health",
                    channel="panel",
                )
            )
            self._session.add(
                PlatformAuditLog(
                    customer_id=env.customer_id,
                    action="environment.unhealthy",
                    target_type="environment",
                    target_id=str(env.id),
                    result="unhealthy",
                    metadata_json={"summary": summary, "checks": checks},
                )
            )

        return {
            "environment_id": str(env.id),
            "domain": env.domain,
            "status": env.status,
            "health_status": status,
            "summary": summary,
            "checks": checks,
            "checked_at": datetime.now(UTC).isoformat(),
        }

    async def probe_by_id(self, environment_id: UUID) -> dict[str, Any]:
        env = await self._session.get(CustomerEnvironment, environment_id)
        if env is None:
            return {"ok": False, "error": "Environment not found"}
        return await self.probe(env)

    async def probe_all_active(self, *, limit: int = 200) -> dict[str, Any]:
        rows = (
            await self._session.execute(
                select(CustomerEnvironment)
                .where(CustomerEnvironment.status.in_(list(_ACTIVE_STATUSES | {"suspended"})))
                .order_by(CustomerEnvironment.updated_at.asc())
                .limit(limit)
            )
        ).scalars().all()
        results = []
        healthy = degraded = unhealthy = offline = 0
        for env in rows:
            try:
                result = await self.probe(env)
                results.append(result)
                hs = result["health_status"]
                if hs == "healthy":
                    healthy += 1
                elif hs == "degraded":
                    degraded += 1
                elif hs == "offline":
                    offline += 1
                else:
                    unhealthy += 1
            except Exception as exc:  # noqa: BLE001
                logger.warning("health_probe_failed", env_id=str(env.id), error=str(exc))
                env.health_status = "unknown"
                unhealthy += 1
        await self._session.flush()
        return {
            "checked": len(results),
            "healthy": healthy,
            "degraded": degraded,
            "unhealthy": unhealthy,
            "offline": offline,
            "results": results,
        }

    async def queue_probe(self, env: CustomerEnvironment) -> UUID | None:
        env.health_status = "checking"
        await self._session.flush()
        return await enqueue_task(
            self._settings,
            "health_check_environment",
            {"environment_id": str(env.id)},
        )

    async def _run_checks(self, env: CustomerEnvironment) -> tuple[str, str, dict[str, Any]]:
        checks: dict[str, Any] = {}
        root = Path(env.document_root) if env.document_root else None
        checks["docroot_exists"] = bool(root and root.is_dir())
        if root and root.is_dir():
            try:
                checks["docroot_has_files"] = any(root.iterdir())
            except OSError:
                checks["docroot_has_files"] = False
        else:
            checks["docroot_has_files"] = False

        if (env.isolation_type or "") == "docker":
            checks["container_running"] = await asyncio.to_thread(
                self._docker_running, env.container_id, str(env.id)
            )
        else:
            checks["container_running"] = None

        if env.container_port:
            checks["http_local"] = await self._http_ok(
                f"http://127.0.0.1:{int(env.container_port)}/"
            )
        else:
            checks["http_local"] = None

        if env.domain:
            checks["http_vhost"] = await self._http_ok(
                "http://127.0.0.1/",
                host=env.domain,
            )
            # Public reachability is soft — DNS/SSL may still be propagating.
            pub_https = await self._http_ok(f"https://{env.domain}/", verify_ssl=False)
            pub_http = await self._http_ok(f"http://{env.domain}/") if not pub_https else True
            checks["http_public"] = bool(pub_https or pub_http)
        else:
            checks["http_vhost"] = None
            checks["http_public"] = None

        return self._score(checks)

    @staticmethod
    def _score(checks: dict[str, Any]) -> tuple[str, str, dict[str, Any]]:
        if not checks.get("docroot_exists"):
            return "unhealthy", "Document root is missing.", checks

        local_ok = checks.get("http_local") is True or checks.get("http_vhost") is True
        public_ok = checks.get("http_public") is True
        container_down = checks.get("container_running") is False

        # Site responding is the source of truth. A stale container id should not
        # mark a working site Offline.
        if local_ok and public_ok:
            if container_down:
                return (
                    "degraded",
                    "Site responds, but the tracked container looks stopped.",
                    checks,
                )
            return "healthy", "Site responds locally and publicly.", checks
        if local_ok and not public_ok:
            if container_down:
                return (
                    "degraded",
                    "Site responds on the server. Container tracking looks stale, and public DNS/SSL may still be updating.",
                    checks,
                )
            return (
                "degraded",
                "Site responds on the server, but not publicly yet (DNS/SSL may still be updating).",
                checks,
            )
        if public_ok and not local_ok:
            return "degraded", "Public URL responds, but the local probe failed.", checks
        if container_down and not local_ok and not public_ok:
            return "unhealthy", "Container is not running.", checks
        if checks.get("docroot_has_files"):
            return (
                "degraded",
                "Files are present, but the site did not respond to HTTP yet.",
                checks,
            )
        return "unhealthy", "No HTTP response and document root looks empty.", checks

    @staticmethod
    def _docker_running(container_id: str | None, env_id: str) -> bool:
        names: list[str] = []
        if container_id:
            cid = str(container_id).strip()
            names.append(cid)
            # Short id form used by docker CLI
            if len(cid) > 12:
                names.append(cid[:12])
        # Provisioning names containers as ifnotus-env-{order_id_prefix}
        names.append(f"ifnotus-env-{env_id[:12]}")
        names.append(f"ifnotus-env-{env_id.replace('-', '')[:12]}")
        seen: set[str] = set()
        for name in names:
            if not name or name in seen:
                continue
            seen.add(name)
            try:
                result = subprocess.run(
                    ["docker", "inspect", "-f", "{{.State.Running}}", name],
                    capture_output=True,
                    text=True,
                    timeout=8,
                    check=False,
                )
                if result.returncode == 0 and result.stdout.strip().lower() == "true":
                    return True
            except (OSError, subprocess.TimeoutExpired):
                continue
        # Last resort: any running container labeled/named for this env id fragment
        try:
            result = subprocess.run(
                ["docker", "ps", "--format", "{{.ID}} {{.Names}}"],
                capture_output=True,
                text=True,
                timeout=8,
                check=False,
            )
            if result.returncode == 0:
                needle = env_id.replace("-", "")[:8]
                for line in result.stdout.splitlines():
                    low = line.lower()
                    if "ifnotus-env-" in low and (env_id[:8] in low or needle in low.replace("-", "")):
                        return True
                    if container_id and str(container_id)[:12] in low:
                        return True
        except (OSError, subprocess.TimeoutExpired):
            pass
        return False

    async def _http_ok(
        self,
        url: str,
        *,
        host: str | None = None,
        verify_ssl: bool = True,
    ) -> bool:
        headers = {"Host": host} if host else None
        try:
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(3.0, connect=2.0),
                follow_redirects=True,
                verify=verify_ssl,
            ) as client:
                resp = await client.get(url, headers=headers)
            # Anything short of connection failure that returns a response counts.
            return resp.status_code < 500
        except Exception:  # noqa: BLE001
            return False
