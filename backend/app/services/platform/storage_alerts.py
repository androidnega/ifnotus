"""Periodic storage usage scan + soft/hard quota notifications (PHASE 32)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.logging import get_logger
from app.models.platform import CustomerEnvironment, Notification, PlatformAuditLog
from app.services.platform.environment_storage import host_storage_pressure
from app.services.platform.usage import usage_snapshot

logger = get_logger(__name__)


class StorageUsageService:
    def __init__(self, settings: Settings, session: AsyncSession) -> None:
        self._settings = settings
        self._session = session

    async def scan_and_notify(self, *, limit: int = 200) -> dict:
        rows = (
            await self._session.execute(
                select(CustomerEnvironment)
                .where(CustomerEnvironment.status.in_(["active", "suspended"]))
                .order_by(CustomerEnvironment.updated_at.asc())
                .limit(limit)
            )
        ).scalars().all()

        summary: dict = {
            "checked": 0,
            "warning": 0,
            "high": 0,
            "critical": 0,
            "over": 0,
            "ok": 0,
            "notified": 0,
        }
        for env in rows:
            summary["checked"] += 1
            snap = usage_snapshot(env.document_root, env.storage_limit_gb)
            status = str(snap["storage_status"])
            if status in summary:
                summary[status] += 1
            elif status == "ok":
                summary["ok"] += 1
            if status == "ok":
                continue
            kind = f"storage_{status}"
            marker = f"env:{env.id}"
            if await self._recently_notified(env.customer_id, kind, marker):
                continue
            titles = {
                "over": "Storage full",
                "critical": "Storage critical",
                "high": "Storage high",
                "warning": "Storage almost full",
            }
            self._session.add(
                Notification(
                    customer_id=env.customer_id,
                    title=titles.get(status, "Storage alert"),
                    body=(
                        f"{env.domain or env.id}: {snap['message']} "
                        f"({snap['storage_used_gb']} / {snap['storage_limit_gb']} GB). [{marker}]"
                    ),
                    kind=kind,
                    channel="panel",
                )
            )
            summary["notified"] += 1
            logger.info(
                "storage_quota_alert",
                environment_id=str(env.id),
                domain=env.domain,
                status=status,
                pct=snap["storage_pct"],
            )
        await self._session.flush()
        host = self._alert_host_disk()
        summary["host_disk_pct"] = host.get("used_pct")
        summary["host_alert"] = host.get("level") if host.get("level") != "ok" else None
        summary["host_free_gb"] = host.get("free_gb")
        return summary

    def _alert_host_disk(self) -> dict:
        snap = host_storage_pressure(self._settings)
        level = str(snap.get("level") or "ok")
        if level == "ok":
            return snap
        stamp = Path("/var/tmp") / f"ifnotus-host-disk-{level}"
        try:
            if stamp.exists() and (datetime.now(UTC).timestamp() - stamp.stat().st_mtime) < 21600:
                return snap
            stamp.write_text(str(snap.get("used_pct")), encoding="utf-8")
        except OSError:
            pass
        logger.warning(
            "host_disk_alert",
            pct=snap.get("used_pct"),
            free_gb=snap.get("free_gb"),
            level=level,
        )
        phone = (self._settings.operator_alert_phone or self._settings.support_whatsapp or "").strip()
        if phone:
            from app.services.platform.delivery import MessageDelivery

            MessageDelivery(self._settings).send_sms(
                to=phone,
                body=(
                    f"IFNOTUS disk {snap.get('used_pct')}% ({level}), "
                    f"{snap.get('free_gb')} GB free. Provisioning "
                    f"{'BLOCKED' if snap.get('block_provisioning') else 'ok'}."
                )[:320],
            )
        self._session.add(
            PlatformAuditLog(
                customer_id=None,
                action=f"host.disk.{level}",
                target_type="host",
                target_id=str(snap.get("path") or "/"),
                result="alert",
                metadata_json=dict(snap),
            )
        )
        return snap

    async def _recently_notified(self, customer_id, kind: str, marker: str) -> bool:
        since = datetime.now(UTC) - timedelta(hours=24)
        row = (
            await self._session.execute(
                select(Notification.id)
                .where(
                    Notification.customer_id == customer_id,
                    Notification.kind == kind,
                    Notification.created_at >= since,
                    Notification.body.contains(marker),
                )
                .limit(1)
            )
        ).scalar_one_or_none()
        return row is not None
