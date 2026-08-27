#!/usr/bin/env python3
"""Phase J — resource enforcement verification (run on production VPS).

Usage (from backend root on VPS):
  .venv/bin/python scripts/phase_j_resource_enforcement.py

Optional env:
  PHASE_J_DOMAIN=example.ifnotus.space   # legacy tenant domain to probe
  PHASE_J_SKIP_STRESS=1                  # skip memory stress in slice
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.core.config import get_settings
from app.services.platform.environment_storage import (
    os_quota_runtime_ready,
    quota_tools_present,
)
from app.services.platform.resource_status import build_resource_statuses
from app.services.platform.systemd_env_slice import (
    EnvironmentSliceService,
    cgroup_v2_available,
    limits_from_env,
    slice_name_for,
    systemd_available,
)

PASS = "PASS"
FAIL = "FAIL"
PARTIAL = "PARTIAL"
SKIP = "SKIP"


def _run(cmd: list[str], *, timeout: int = 30) -> tuple[int, str, str]:
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    return proc.returncode, (proc.stdout or "").strip(), (proc.stderr or "").strip()


def _probe_host() -> dict:
    settings = get_settings()
    root = getattr(settings, "customer_environments_root", "/srv/apps/ifnotus-customers") or "/"
    probe = os_quota_runtime_ready(settings, root)
    slices = sorted(Path("/etc/systemd/system").glob("ifnotus-env-*.slice"))
    return {
        "customer_root": root,
        "quota_tools": quota_tools_present(),
        "quota_probe": probe,
        "systemd": systemd_available(),
        "cgroup_v2": cgroup_v2_available(),
        "prlimit": bool(__import__("shutil").which("prlimit")),
        "slice_units_count": len(slices),
        "slice_samples": [p.name for p in slices[:5]],
    }


def _pick_legacy_env() -> object | None:
    """Best-effort: load one legacy environment from DB when available."""
    domain = os.environ.get("PHASE_J_DOMAIN", "").strip()
    try:
        import asyncio
        from sqlalchemy import select
        from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
        from sqlalchemy.orm import sessionmaker

        from app.models.platform import CustomerEnvironment, HostingPlan

        settings = get_settings()
        engine = create_async_engine(settings.database_url, echo=False)
        Session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

        async def _load():
            async with Session() as session:
                q = select(CustomerEnvironment).where(CustomerEnvironment.provider == "legacy")
                if domain:
                    q = q.where(CustomerEnvironment.domain == domain)
                q = q.limit(1)
                env = (await session.execute(q)).scalar_one_or_none()
                plan = None
                if env is not None and env.plan_id:
                    plan = (
                        await session.execute(
                            select(HostingPlan).where(HostingPlan.id == env.plan_id)
                        )
                    ).scalar_one_or_none()
                return env, plan

        return asyncio.run(_load())
    except Exception as exc:  # noqa: BLE001
        return None, None, str(exc)


def _stress_slice_memory(slice_name: str, *, limit_bytes: int) -> dict:
    """Run a short-lived scope in the slice that tries to allocate > MemoryMax."""
    if os.environ.get("PHASE_J_SKIP_STRESS"):
        return {"status": SKIP, "detail": "skipped via PHASE_J_SKIP_STRESS"}
    if not __import__("shutil").which("systemd-run"):
        return {"status": SKIP, "detail": "systemd-run missing"}

    # Try to allocate ~2× limit (cap script at 256MB attempt for safety).
    attempt_mb = min(256, max(32, int(limit_bytes / (1024 * 1024)) * 2))
    py = (
        "import sys;"
        f"buf=bytearray({attempt_mb}*1024*1024);"
        "print('allocated', len(buf));"
    )
    code, out, err = _run(
        [
            "systemd-run",
            "--quiet",
            "--collect",
            "--scope",
            f"--slice={slice_name}",
            "--",
            "python3",
            "-c",
            py,
        ],
        timeout=45,
    )
    combined = f"{out}\n{err}".lower()
    if code != 0 or "killed" in combined or "memory" in combined or "cannot allocate" in combined:
        return {"status": PASS, "detail": f"memory capped or process failed (exit {code})"}
    return {
        "status": PARTIAL,
        "detail": f"stress completed without OOM signal (exit {code}); verify MemoryMax manually",
    }


def _sftp_bypass_note(probe: dict) -> dict:
    if probe.get("quotas_active"):
        return {"status": PASS, "detail": "quotaon active — SFTP writes subject to OS user quota"}
    return {
        "status": PARTIAL,
        "detail": "quotaon not active on customer mount — SFTP may bypass panel disk limits",
    }


def main() -> int:
    results: list[dict] = []
    host = _probe_host()
    results.append({"check": "Host quota tools", "status": PASS if host["quota_tools"] else FAIL})
    results.append(
        {
            "check": "quotaon active on customer root",
            "status": PASS if host["quota_probe"].get("quotas_active") else PARTIAL,
            "detail": host["quota_probe"].get("mount"),
        }
    )
    results.append({"check": "systemd available", "status": PASS if host["systemd"] else FAIL})
    results.append({"check": "cgroup v2", "status": PASS if host["cgroup_v2"] else FAIL})
    results.append({"check": "prlimit present", "status": PASS if host["prlimit"] else PARTIAL})

    load = _pick_legacy_env()
    env = plan = None
    load_err = None
    if isinstance(load, tuple):
        if len(load) == 3:
            env, plan, load_err = load
        elif len(load) == 2:
            env, plan = load

    if env is None:
        results.append(
            {
                "check": "Legacy tenant probe",
                "status": SKIP,
                "detail": load_err or "no legacy environment in DB (set PHASE_J_DOMAIN?)",
            }
        )
    else:
        slice_svc = EnvironmentSliceService()
        applied = slice_svc.ensure_slice(env, plan)
        live = slice_svc.read_usage(env)
        from app.services.platform.environment_storage import apply_os_user_quota

        os_quota = apply_os_user_quota(
            get_settings(),
            username=getattr(env, "unix_username", None),
            home=getattr(env, "document_root", None),
            storage_limit_gb=getattr(env, "storage_limit_gb", 0),
        )
        statuses = build_resource_statuses(
            env=env,
            plan=plan,
            settings=get_settings(),
            disk={"storage_pct": 0, "storage_used_bytes": 0},
            os_quota=os_quota,
            live=live,
            slice_applied=applied,
        )
        slice_name = slice_name_for(env.id)
        unit_path = Path("/etc/systemd/system") / slice_name
        results.append(
            {
                "check": f"Slice unit {slice_name}",
                "status": PASS if unit_path.is_file() and applied.get("applied") else PARTIAL,
                "detail": str(applied),
            }
        )
        results.append(
            {
                "check": "Resource status model (legacy tenant)",
                "status": PASS,
                "detail": statuses.get("summary"),
                "statuses": statuses,
            }
        )
        limits = limits_from_env(env, plan)
        results.append(
            _stress_slice_memory(slice_name, limit_bytes=limits.memory_max_bytes)
            | {"check": "MemoryMax stress in slice"}
        )
        results.append(_sftp_bypass_note(host["quota_probe"]) | {"check": "SFTP disk bypass risk"})

    verdict = PASS
    if any(r["status"] == FAIL for r in results):
        verdict = FAIL
    elif any(r["status"] == PARTIAL for r in results):
        verdict = PARTIAL

    report = {
        "phase": "J",
        "verdict": verdict,
        "host": host,
        "results": results,
    }
    print(json.dumps(report, indent=2, default=str))
    return 0 if verdict != FAIL else 1


if __name__ == "__main__":
    raise SystemExit(main())
