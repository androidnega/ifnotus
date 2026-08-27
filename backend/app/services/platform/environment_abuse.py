"""PHASE 30 — per-environment automated abuse detection and response."""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.logging import get_logger
from app.models.platform import (
    ApplicationInstance,
    CustomerEnvironment,
    HostingPlan,
    Notification,
    PlatformAuditLog,
)
from app.services.platform.env_cron import EnvironmentCronService
from app.services.platform.environment_monitoring import _user_process_stats
from app.services.platform.plan_matrix import features_for
from app.services.platform.tenant import TenantService
from app.services.platform.usage import usage_snapshot

logger = get_logger(__name__)

_PHISHING_PATTERNS = re.compile(
    r"(?i)(verify.?your.?account|password.?expir|bank.?account|crypto.?wallet|"
    r"login.?immediately|confirm.?identity|wire.?transfer|urgent.?action)"
)
_SUSPICIOUS_FILES = ("index.html", "index.php", "default.html", "login.html")


@dataclass
class AbuseSignal:
    kind: str
    severity: str  # info | warning | critical
    message: str
    details: dict[str, Any] = field(default_factory=dict)


@dataclass
class AbuseAction:
    kind: str  # warning | throttle | stop_apps | suspend | admin_alert
    reason: str
    signals: list[AbuseSignal]


def _plan_limits(plan: HostingPlan | None) -> dict[str, int]:
    feats = features_for(plan)
    return {
        "max_processes": max(5, int(feats.get("max_processes") or 10)),
    }


def _count_outbound_connections(username: str | None) -> int:
    if not username:
        return 0
    try:
        import psutil
    except ImportError:
        return 0
    pids = set()
    for proc in psutil.process_iter(["pid", "username"]):
        try:
            if (proc.info.get("username") or "") == username:
                pids.add(proc.info["pid"])
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            continue
    count = 0
    for conn in psutil.net_connections(kind="inet"):
        try:
            if conn.pid in pids and conn.status == "ESTABLISHED" and conn.raddr:
                count += 1
        except (psutil.AccessDenied, AttributeError):
            continue
    return count


def _scan_public_content(root: str | Path | None) -> list[str]:
    if not root:
        return []
    base = Path(root)
    if not base.is_dir():
        return []
    hits: list[str] = []
    for name in _SUSPICIOUS_FILES:
        path = base / name
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")[:50000]
        except OSError:
            continue
        if _PHISHING_PATTERNS.search(text):
            hits.append(name)
    return hits


class EnvironmentAbuseService:
    """Detect abusive patterns and apply graduated responses (never delete data)."""

    def __init__(self, settings: Settings, session: AsyncSession) -> None:
        self._settings = settings
        self._session = session

    async def evaluate(self, env: CustomerEnvironment, plan: HostingPlan | None) -> list[AbuseSignal]:
        if env.status not in {"active", "provisioning"}:
            return []
        signals: list[AbuseSignal] = []
        limits = _plan_limits(plan)
        ram_limit_mb = float(env.ram_limit_gb or 0) * 1024
        cpu_limit = float(env.cpu_limit or 1)

        disk = usage_snapshot(env.document_root, env.storage_limit_gb)
        if disk.get("hard_exceeded"):
            signals.append(
                AbuseSignal(
                    "disk_exhaustion",
                    "critical",
                    "Site disk quota exceeded.",
                    {"storage_pct": disk.get("storage_pct")},
                )
            )
        elif disk.get("soft_warning"):
            signals.append(
                AbuseSignal(
                    "disk_pressure",
                    "warning",
                    "Site disk usage is high.",
                    {"storage_pct": disk.get("storage_pct")},
                )
            )

        proc = await asyncio.to_thread(_user_process_stats, env.unix_username)
        if proc.get("available"):
            mem_pct = (proc["memory_rss_mb"] / ram_limit_mb * 100) if ram_limit_mb else 0
            mem_thr = float(getattr(self._settings, "abuse_memory_pct_threshold", 95) or 95)
            if mem_pct >= mem_thr:
                signals.append(
                    AbuseSignal(
                        "memory_runaway",
                        "critical",
                        f"Memory usage {mem_pct:.0f}% of plan limit.",
                        {"rss_mb": proc["memory_rss_mb"], "limit_mb": ram_limit_mb},
                    )
                )
            cpu_thr = float(getattr(self._settings, "abuse_cpu_pct_threshold", 150) or 150)
            cpu_budget = max(cpu_limit * 100, 100)
            if proc["cpu_percent"] >= max(cpu_thr, cpu_budget * 1.5):
                signals.append(
                    AbuseSignal(
                        "cpu_abuse",
                        "warning" if proc["cpu_percent"] < cpu_budget * 2.5 else "critical",
                        f"CPU usage {proc['cpu_percent']:.0f}% for this account.",
                        {"cpu_percent": proc["cpu_percent"], "vcpu": cpu_limit},
                    )
                )
            proc_mult = float(getattr(self._settings, "abuse_process_multiplier", 3) or 3)
            if proc["process_count"] > limits["max_processes"] * proc_mult:
                signals.append(
                    AbuseSignal(
                        "fork_bomb",
                        "critical",
                        f"Process count {proc['process_count']} exceeds safe limit.",
                        {"process_count": proc["process_count"], "limit": limits["max_processes"]},
                    )
                )

        cron_jobs = EnvironmentCronService(self._settings, self._session).list_jobs(env)
        cron_max = int(getattr(self._settings, "abuse_cron_max_jobs", 15) or 15)
        if len(cron_jobs) > cron_max:
            signals.append(
                AbuseSignal(
                    "excessive_cron",
                    "warning",
                    f"{len(cron_jobs)} cron jobs configured (max recommended {cron_max}).",
                    {"job_count": len(cron_jobs)},
                )
            )
        recent_runs = sum(
            1
            for j in cron_jobs
            if j.get("last_run_at")
            and _parse_iso(j["last_run_at"]) > datetime.now(UTC) - timedelta(hours=1)
        )
        if recent_runs > int(getattr(self._settings, "abuse_cron_runs_per_hour", 30) or 30):
            signals.append(
                AbuseSignal(
                    "cron_burst",
                    "warning",
                    f"{recent_runs} cron runs in the last hour.",
                    {"runs_last_hour": recent_runs},
                )
            )

        apps = (
            await self._session.execute(
                select(ApplicationInstance).where(ApplicationInstance.environment_id == env.id)
            )
        ).scalars().all()
        failed = [a for a in apps if a.status in {"failed", "restarting", "crash_loop"}]
        if failed:
            signals.append(
                AbuseSignal(
                    "app_restart_loop",
                    "warning",
                    f"{len(failed)} application(s) in a restart/failed state.",
                    {"app_ids": [str(a.id) for a in failed]},
                )
            )

        outbound_thr = int(getattr(self._settings, "abuse_outbound_connections_threshold", 200) or 200)
        outbound = await asyncio.to_thread(_count_outbound_connections, env.unix_username)
        if outbound >= outbound_thr:
            signals.append(
                AbuseSignal(
                    "abnormal_outbound",
                    "critical",
                    f"{outbound} established outbound connections from this account.",
                    {"connections": outbound},
                )
            )

        suspicious = await asyncio.to_thread(_scan_public_content, env.document_root)
        if suspicious:
            signals.append(
                AbuseSignal(
                    "suspicious_content",
                    "warning",
                    "Possible phishing or scam wording in public site files.",
                    {"files": suspicious},
                )
            )

        return signals

    def decide_actions(self, signals: list[AbuseSignal]) -> list[AbuseAction]:
        if not signals:
            return []
        actions: list[AbuseAction] = []
        critical = [s for s in signals if s.severity == "critical"]
        warnings = [s for s in signals if s.severity == "warning"]

        if warnings:
            actions.append(AbuseAction("warning", "Usage warning", warnings))
        if critical:
            kinds = {s.kind for s in critical}
            if "disk_exhaustion" in kinds or "fork_bomb" in kinds or "abnormal_outbound" in kinds:
                actions.append(AbuseAction("suspend", "Critical abuse — environment suspended.", critical))
            elif "memory_runaway" in kinds or "cpu_abuse" in kinds:
                actions.append(AbuseAction("stop_apps", "Runaway workload — apps stopped.", critical))
                actions.append(AbuseAction("throttle", "Account temporarily locked.", critical))
            else:
                actions.append(AbuseAction("throttle", "Critical signal — account throttled.", critical))
            actions.append(AbuseAction("admin_alert", "Staff alert for critical abuse.", critical))
        return actions

    async def apply_actions(
        self,
        env: CustomerEnvironment,
        actions: list[AbuseAction],
    ) -> list[dict[str, Any]]:
        if not getattr(self._settings, "abuse_protection_enabled", True):
            return []
        if await self._recent_automation(env.id, minutes=15):
            return []

        results: list[dict[str, Any]] = []
        for action in actions:
            if await self._recent_action(env.id, action.kind, minutes=60):
                continue
            outcome = await self._execute(env, action)
            results.append(outcome)
        return results

    async def sweep_active(self, *, limit: int = 150) -> dict[str, Any]:
        rows = (
            await self._session.execute(
                select(CustomerEnvironment)
                .where(CustomerEnvironment.status == "active")
                .order_by(CustomerEnvironment.updated_at.asc())
                .limit(limit)
            )
        ).scalars().all()
        tenant = TenantService(self._session)
        summary = {"checked": 0, "signaled": 0, "actions": 0, "environments": []}
        for env in rows:
            summary["checked"] += 1
            plan = await tenant.plan_for_environment(env)
            signals = await self.evaluate(env, plan)
            if not signals:
                continue
            summary["signaled"] += 1
            actions = self.decide_actions(signals)
            applied = await self.apply_actions(env, actions)
            if applied:
                summary["actions"] += len(applied)
                summary["environments"].append(
                    {
                        "environment_id": str(env.id),
                        "domain": env.domain,
                        "signals": [s.kind for s in signals],
                        "actions": [a["action"] for a in applied],
                    }
                )
        await self._session.flush()
        return summary

    async def _execute(self, env: CustomerEnvironment, action: AbuseAction) -> dict[str, Any]:
        meta = {
            "action": action.kind,
            "reason": action.reason,
            "signals": [
                {"kind": s.kind, "severity": s.severity, "message": s.message, "details": s.details}
                for s in action.signals
            ],
        }
        result = {"action": action.kind, "ok": True}

        if action.kind == "warning":
            self._session.add(
                Notification(
                    customer_id=env.customer_id,
                    title="Resource usage warning",
                    body=f"{env.domain or env.id}: {action.reason}",
                    kind="abuse_warning",
                    channel="panel",
                )
            )

        elif action.kind == "throttle":
            try:
                from app.services.platform.unix_identity import UnixIdentityService

                UnixIdentityService(self._settings, self._session).lock(env, actor="abuse_protection")
            except Exception as exc:  # noqa: BLE001
                logger.warning("abuse_throttle_failed", env_id=str(env.id), error=str(exc))
                result["ok"] = False
                meta["error"] = str(exc)

        elif action.kind == "stop_apps":
            try:
                from app.services.platform.application_runtime import ApplicationRuntimeService

                runtime = ApplicationRuntimeService(self._settings, self._session)
                apps = (
                    await self._session.execute(
                        select(ApplicationInstance).where(
                            ApplicationInstance.environment_id == env.id,
                            ApplicationInstance.status.in_(["running", "failed", "restarting"]),
                        )
                    )
                ).scalars().all()
                stopped = 0
                for app in apps:
                    await runtime.stop(env, app.id)
                    stopped += 1
                meta["apps_stopped"] = stopped
            except Exception as exc:  # noqa: BLE001
                logger.warning("abuse_stop_apps_failed", env_id=str(env.id), error=str(exc))
                result["ok"] = False
                meta["error"] = str(exc)

        elif action.kind == "suspend":
            if getattr(self._settings, "abuse_auto_suspend_enabled", True):
                try:
                    from app.services.platform.lifecycle import EnvironmentLifecycleService

                    await EnvironmentLifecycleService(self._settings, self._session).suspend(
                        env.customer_id, env.id
                    )
                    self._session.add(
                        Notification(
                            customer_id=env.customer_id,
                            title="Hosting temporarily suspended",
                            body=(
                                f"{env.domain or env.id} was paused automatically due to "
                                f"resource abuse. Contact support — your files are safe."
                            ),
                            kind="abuse_suspend",
                            channel="panel",
                        )
                    )
                except Exception as exc:  # noqa: BLE001
                    logger.warning("abuse_suspend_failed", env_id=str(env.id), error=str(exc))
                    result["ok"] = False
                    meta["error"] = str(exc)
            else:
                result["ok"] = False
                meta["skipped"] = "auto_suspend_disabled"

        elif action.kind == "admin_alert":
            phone = (self._settings.operator_alert_phone or self._settings.support_whatsapp or "").strip()
            body = (
                f"Abuse alert: {env.domain or env.id} — {action.reason} "
                f"({', '.join(s.kind for s in action.signals)})"
            )
            from app.services.platform.delivery import MessageDelivery

            delivery = MessageDelivery(self._settings)
            if phone:
                delivery.send_sms(to=phone, body=body[:320])
            delivery.mirror_sms_to_email(
                to_email=getattr(self._settings, "support_email", None),
                sms_body=body,
                subject="Abuse alert",
            )
            logger.warning("abuse_admin_alert", environment_id=str(env.id), domain=env.domain, body=body)

        self._audit(env, action.kind, meta, success=result["ok"])
        return result

    def _audit(
        self,
        env: CustomerEnvironment,
        action: str,
        details: dict[str, Any],
        *,
        success: bool,
    ) -> None:
        self._session.add(
            PlatformAuditLog(
                customer_id=env.customer_id,
                action=f"abuse.{action}",
                target_type="environment",
                target_id=str(env.id),
                result="success" if success else "failed",
                metadata_json=details,
            )
        )

    async def _recent_automation(self, environment_id: UUID, *, minutes: int) -> bool:
        since = datetime.now(UTC) - timedelta(minutes=minutes)
        row = (
            await self._session.execute(
                select(PlatformAuditLog.id)
                .where(
                    PlatformAuditLog.target_id == str(environment_id),
                    PlatformAuditLog.action.like("abuse.%"),
                    PlatformAuditLog.occurred_at >= since,
                )
                .limit(1)
            )
        ).scalar_one_or_none()
        return row is not None

    async def _recent_action(self, environment_id: UUID, kind: str, *, minutes: int) -> bool:
        since = datetime.now(UTC) - timedelta(minutes=minutes)
        row = (
            await self._session.execute(
                select(PlatformAuditLog.id)
                .where(
                    PlatformAuditLog.target_id == str(environment_id),
                    PlatformAuditLog.action == f"abuse.{kind}",
                    PlatformAuditLog.occurred_at >= since,
                )
                .limit(1)
            )
        ).scalar_one_or_none()
        return row is not None


def _parse_iso(value: str) -> datetime:
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=UTC)
    except ValueError:
        return datetime.min.replace(tzinfo=UTC)
