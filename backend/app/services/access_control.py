"""Access control: IP blacklist/allowlist firewall, login tracing, action blocks."""

from __future__ import annotations

from typing import Any
import time
import ipaddress
import re
import subprocess
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppException, NotFoundError
from app.core.logging import get_logger
from app.models.access import AccessAttempt, BlockedAction, FirewallRule, SystemActionLog
from app.repositories.access import (
    AccessAttemptRepository,
    BlockedActionRepository,
    FirewallRuleRepository,
    IpBlacklistRepository,
    SystemActionLogRepository,
)
from app.services.log_watermarks import SSH_ATTEMPTS, default_watermarks
from app.services.security_actions import KNOWN_BLOCKABLE_ACTIONS, detect_source

logger = get_logger(__name__)

# CGNAT and shared mobile network safe defaults:
# High-frequency volumetric failures trigger temporary progressive lockout, not 3-day wide-subnet blocks.
CONSECUTIVE_FAIL_LIMIT = 10
AUTO_UNLOCK_MINUTES = 15
AUTO_UNLOCK_HOURS = 72  # Retained for manual administrative blocks

# Short-lived process cache so polling GETs don't hit the DB every request.
_firewall_cache: tuple[float, list[tuple[str, str]]] | None = None
_blocked_cache: tuple[float, set[str]] | None = None
_CACHE_TTL = 15.0


def invalidate_security_caches() -> None:
    global _firewall_cache, _blocked_cache
    _firewall_cache = None
    _blocked_cache = None


class IpBlockedError(AppException):
    status_code = 403
    code = "ip_blocked"
    message = "Access from this IP has been blocked due to repeated failed login attempts."


class NetworkDeniedError(AppException):
    status_code = 403
    code = "network_denied"
    message = "Access from this network is not allowed by the firewall policy."


class DeviceDeniedError(AppException):
    status_code = 403
    code = "device_denied"
    message = "This device is not authorized to access the admin panel."


class ActionBlockedError(AppException):
    status_code = 403
    code = "action_blocked"
    message = "This action has been disabled by an administrator."


@dataclass(frozen=True)
class AccessContext:
    ip_address: str
    user_agent: str | None = None
    device_fingerprint: str | None = None
    request_id: str | None = None
    source: str = "web"


class AccessControlService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._attempts = AccessAttemptRepository(session)
        self._blacklist = IpBlacklistRepository(session)
        self._firewall = FirewallRuleRepository(session)
        self._blocked = BlockedActionRepository(session)
        self._actions = SystemActionLogRepository(session)

    async def assert_network_allowed(self, ctx: AccessContext) -> None:
        """Enforce deny rules, login blacklist, then optional allowlist."""
        await self.assert_ip_allowed(ctx)
        await self.assert_admin_lockdown(ctx)

        # Local health checks / reverse-proxy loops must never be trapped by
        # DB allowlists that only contain public customer IPs.
        if ctx.ip_address in {"127.0.0.1", "::1", "localhost"}:
            return

        global _firewall_cache
        now = time.monotonic()
        rules_pairs: list[tuple[str, str]]
        if _firewall_cache and now - _firewall_cache[0] < _CACHE_TTL:
            rules_pairs = _firewall_cache[1]
        else:
            rules = await self._firewall.list_enabled()
            rules_pairs = [(r.action, r.cidr) for r in rules]
            _firewall_cache = (now, rules_pairs)

        if not rules_pairs:
            return

        ip = self._parse_ip(ctx.ip_address)
        if ip is None:
            raise NetworkDeniedError("Unable to determine client IP for firewall check.")

        deny_rules = [cidr for action, cidr in rules_pairs if action == "deny"]
        allow_rules = [cidr for action, cidr in rules_pairs if action == "allow"]

        for cidr in deny_rules:
            if self._ip_in_cidr(ip, cidr):
                raise NetworkDeniedError(
                    f"IP {ctx.ip_address} is denied by firewall rule {cidr}.",
                    details={"cidr": cidr, "action": "deny"},
                )

        if allow_rules:
            if any(self._ip_in_cidr(ip, cidr) for cidr in allow_rules):
                return
            raise NetworkDeniedError(
                f"IP {ctx.ip_address} is not on an allowed network.",
                details={"action": "allowlist"},
            )

    async def assert_admin_lockdown(self, ctx: AccessContext) -> None:
        """Require matching admin IP and/or device fingerprint when lockdown is on."""
        from app.core.config import get_settings

        settings = get_settings()
        if not settings.admin_lockdown_enabled:
            return

        allowed_ips = [item.strip() for item in settings.admin_allowed_ips if item.strip()]
        allowed_fps = {
            item.strip().lower() for item in settings.admin_allowed_fingerprints if item.strip()
        }

        if not allowed_ips and not allowed_fps:
            return

        # Always permit local loopback (health checks / local tooling).
        if ctx.ip_address in {"127.0.0.1", "::1", "localhost"}:
            return

        if allowed_ips:
            # Match login trust: .env allowlist or a DB firewall allow rule.
            # Login may update .env in one worker; other workers still see the DB rule.
            if not await self._is_trusted_admin_ip(ctx.ip_address):
                raise NetworkDeniedError(
                    "Access from this IP is not authorized for admin.",
                    details={"action": "admin_ip_allowlist", "ip": ctx.ip_address},
                )

        if allowed_fps and settings.admin_require_fingerprint:
            fp = (ctx.device_fingerprint or "").strip().lower()
            if not fp or fp not in allowed_fps:
                raise DeviceDeniedError(
                    "This browser/device fingerprint is not authorized for admin.",
                    details={"action": "admin_fingerprint_allowlist"},
                )
        elif allowed_fps:
            fp = (ctx.device_fingerprint or "").strip().lower()
            if fp and fp not in allowed_fps:
                logger.info("admin_unknown_device", ip=ctx.ip_address, fingerprint=fp[:16])

    async def assert_ip_allowed(self, ctx: AccessContext) -> None:
        entry = await self._blacklist.get_by_ip(ctx.ip_address)
        if entry is None or not entry.is_active:
            return

        now = datetime.now(UTC)
        if entry.blocked_until and entry.blocked_until <= now:
            await self._blacklist.unlock(
                entry,
                unlocked_by=None,
                note="system auto-expiry",
            )
            await self._session.commit()
            logger.info("ip_auto_unlocked", ip=ctx.ip_address)
            return

        raise IpBlockedError(
            "This IP address is blacklisted. Contact an administrator to unlock access.",
            details={
                "ip_address": ctx.ip_address,
                "blocked_at": entry.blocked_at.isoformat() if entry.blocked_at else None,
                "blocked_until": entry.blocked_until.isoformat() if entry.blocked_until else None,
            },
        )

    async def assert_action_allowed(self, action_key: str | None) -> None:
        if not action_key:
            return
        global _blocked_cache
        now = time.monotonic()
        if _blocked_cache and now - _blocked_cache[0] < _CACHE_TTL:
            blocked = _blocked_cache[1]
        else:
            blocked = await self._blocked.list_enabled_keys()
            _blocked_cache = (now, blocked)
        if action_key in blocked:
            raise ActionBlockedError(
                f"Action '{action_key}' is currently blocked by an administrator.",
                details={"action_key": action_key},
            )

    async def record_probe(self, ctx: AccessContext) -> None:
        await self._record(
            ctx,
            event_type="access_probe",
            success=False,
            failure_reason="page_view",
            username_or_email=None,
            user_id=None,
        )

    async def record_login_success(
        self,
        ctx: AccessContext,
        *,
        username_or_email: str,
        user_id: UUID,
        trust_ip: bool = True,
    ) -> None:
        await self._record(
            ctx,
            event_type="login_success",
            success=True,
            failure_reason=None,
            username_or_email=username_or_email,
            user_id=user_id,
        )
        # Successful staff auth → permanently trust this IP for panel + SSH.
        if trust_ip:
            await self.trust_authenticated_ip(ctx.ip_address, reason="login_success")

    async def trust_authenticated_ip(self, ip: str, *, reason: str = "authenticated") -> None:
        """Unlock blacklist and allow this IP for admin web + SSH."""
        ip = (ip or "").strip()
        if not ip or ip in {"unknown", "127.0.0.1", "::1", "localhost"}:
            return
        parsed = self._parse_ip(ip)
        if parsed is None or parsed.is_private or parsed.is_loopback:
            # Still clear local blacklist, but skip public allowlist/UFW for private.
            await self._unlock_blacklist_for_ip(ip, note=f"auto-unlock after {reason}")
            return

        await self._unlock_blacklist_for_ip(ip, note=f"auto-unlock after {reason}")
        await self._ensure_allow_firewall_rule(ip)
        self._append_admin_allowed_ip(ip)
        self._ensure_ssh_allow(ip)
        invalidate_security_caches()
        logger.info("authenticated_ip_trusted", ip=ip, reason=reason)

    async def _unlock_blacklist_for_ip(self, ip: str, *, note: str) -> None:
        entry = await self._blacklist.get_by_ip(ip)
        if entry is None or not entry.is_active:
            return
        await self._blacklist.unlock(entry, unlocked_by=None, note=note)
        await self._session.commit()

    async def _ensure_allow_firewall_rule(self, ip: str) -> None:
        cidr = f"{ip}/32"
        rules = await self._firewall.list_all()
        for rule in rules:
            if rule.action == "allow" and rule.cidr in {cidr, ip} and rule.enabled:
                return
        rule = FirewallRule(
            cidr=cidr,
            action="allow",
            note="auto-trusted after successful login",
            enabled=True,
            created_by_user_id=None,
        )
        await self._firewall.create(rule)
        await self._session.commit()

    @staticmethod
    def _append_admin_allowed_ip(ip: str) -> None:
        """Persist IP into ADMIN_ALLOWED_IPS in .env and refresh settings cache."""
        import os
        from pathlib import Path

        from app.core.config import get_settings

        settings = get_settings()
        current = [item.strip() for item in settings.admin_allowed_ips if item.strip()]
        if ip in current:
            # Keep process env + cache aligned even when already present.
            os.environ["ADMIN_ALLOWED_IPS"] = ",".join(current)
            get_settings.cache_clear()
            return

        candidates = [
            Path("/srv/apps/ifnotus/backend/.env"),
            Path(".env"),
            Path("../.env"),
        ]
        env_path = next((p for p in candidates if p.is_file()), None)
        if env_path is None:
            logger.warning("admin_allowed_ip_env_missing", ip=ip)
            # Still trust in-process for this runtime.
            merged = current + [ip]
            os.environ["ADMIN_ALLOWED_IPS"] = ",".join(merged)
            get_settings.cache_clear()
            return

        lines = env_path.read_text(encoding="utf-8", errors="replace").splitlines()
        updated = False
        out: list[str] = []
        merged = list(current)
        for line in lines:
            if line.startswith("ADMIN_ALLOWED_IPS="):
                existing = [p.strip() for p in line.split("=", 1)[1].split(",") if p.strip()]
                if ip not in existing:
                    existing.append(ip)
                merged = existing
                out.append("ADMIN_ALLOWED_IPS=" + ",".join(existing))
                updated = True
            else:
                out.append(line)
        if not updated:
            merged = current + [ip]
            out.append(f"ADMIN_ALLOWED_IPS={','.join(merged)}")
            out.append("ADMIN_LOCKDOWN_ENABLED=true")
        env_path.write_text("\n".join(out) + "\n", encoding="utf-8")
        # systemd EnvironmentFile values live in os.environ and beat .env on reload;
        # update the live process env so /auth/me works immediately after login.
        os.environ["ADMIN_ALLOWED_IPS"] = ",".join(merged)
        get_settings.cache_clear()
        logger.info("admin_allowed_ip_appended", ip=ip, total=len(merged))

    @staticmethod
    def _ensure_ssh_allow(ip: str) -> None:
        """Best-effort SSH allow. Prefer global rate-limit; avoid fragile UFW comments."""
        try:
            check = subprocess.run(
                ["ufw", "status"],
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )
            status = check.stdout or ""
            # If SSH is already open/limited to the world, nothing to do.
            if "22/tcp" in status and "Anywhere" in status:
                return
            # No comments: plain-text comments previously corrupted Contabo UFW.
            subprocess.run(
                ["ufw", "allow", "from", ip, "to", "any", "port", "22", "proto", "tcp"],
                capture_output=True,
                text=True,
                timeout=15,
                check=False,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            logger.warning("ssh_allow_failed", ip=ip, error=str(exc))

    async def record_login_failure(
        self,
        ctx: AccessContext,
        *,
        username_or_email: str,
        reason: str,
        user_id: UUID | None = None,
    ) -> None:
        await self._record(
            ctx,
            event_type="login_failure",
            success=False,
            failure_reason=reason,
            username_or_email=username_or_email,
            user_id=user_id,
        )
        await self._maybe_blacklist(ctx)

    async def _maybe_blacklist(self, ctx: AccessContext) -> None:
        # Never blacklist an already-trusted admin IP.
        if await self._is_trusted_admin_ip(ctx.ip_address):
            return

        recent = await self._attempts.list_for_ip(ctx.ip_address, limit=20)
        streak = 0
        for attempt in recent:
            if attempt.event_type != "login_failure":
                break
            streak += 1
        if streak < CONSECUTIVE_FAIL_LIMIT:
            return

        await self._blacklist.upsert_block(
            ip=ctx.ip_address,
            reason=f"{streak} consecutive failed login attempts (auto-throttle {AUTO_UNLOCK_MINUTES} mins)",
            failed_attempt_count=streak,
            blocked_until=datetime.now(UTC) + timedelta(minutes=AUTO_UNLOCK_MINUTES),
            fingerprint=ctx.device_fingerprint,
            user_agent=ctx.user_agent,
        )
        await self._session.commit()
        logger.warning(
            "ip_blacklisted",
            ip=ctx.ip_address,
            streak=streak,
            fingerprint=ctx.device_fingerprint,
        )

    async def _is_trusted_admin_ip(self, ip: str) -> bool:
        from app.core.config import get_settings

        settings = get_settings()
        allowed = [item.strip() for item in settings.admin_allowed_ips if item.strip()]
        parsed = self._parse_ip(ip)
        if parsed and any(self._ip_in_cidr(parsed, cidr) for cidr in allowed):
            return True
        rules = await self._firewall.list_enabled()
        if parsed and any(
            r.action == "allow" and self._ip_in_cidr(parsed, r.cidr) for r in rules
        ):
            return True
        return False

    async def _record(
        self,
        ctx: AccessContext,
        *,
        event_type: str,
        success: bool,
        failure_reason: str | None,
        username_or_email: str | None,
        user_id: UUID | None,
    ) -> AccessAttempt:
        attempt = AccessAttempt(
            ip_address=ctx.ip_address,
            username_or_email=username_or_email,
            user_id=user_id,
            event_type=event_type,
            success=success,
            failure_reason=failure_reason,
            device_fingerprint=ctx.device_fingerprint,
            user_agent=(ctx.user_agent or "")[:512] or None,
            request_id=ctx.request_id,
            source=ctx.source or detect_source(ctx.user_agent),
        )
        saved = await self._attempts.create(attempt)
        await self._session.commit()
        logger.info(
            "access_trace",
            event_type=event_type,
            ip=ctx.ip_address,
            source=saved.source,
            fingerprint=ctx.device_fingerprint,
            success=success,
            reason=failure_reason,
            identity=username_or_email,
        )
        return saved

    async def list_blacklist(self, *, active_only: bool = True):
        if active_only:
            return await self._blacklist.list_active()
        return await self._blacklist.list_all()

    async def list_attempts(self, limit: int = 100):
        await self._sync_ssh_attempts(limit=min(40, limit))
        rows = await self._attempts.list_recent(limit=limit)
        return rows

    async def _sync_ssh_attempts(self, *, limit: int = 40) -> None:
        """Persist recent SSH journal logins into access_attempts for full transparency."""
        ssh_rows = self._read_ssh_logins(limit=limit)
        cutoff = default_watermarks().get(SSH_ATTEMPTS)
        if cutoff:
            ssh_rows = [r for r in ssh_rows if r.attempted_at and r.attempted_at > cutoff]
        if not ssh_rows:
            return
        existing = await self._attempts.list_recent(limit=300)
        seen = {
            (
                a.source,
                a.ip_address,
                a.username_or_email or "",
                a.event_type,
                int(a.attempted_at.timestamp()) if a.attempted_at else 0,
            )
            for a in existing
            if a.source == "ssh"
        }
        created = 0
        for row in ssh_rows:
            key = (
                "ssh",
                row.ip_address,
                row.username_or_email or "",
                row.event_type,
                int(row.attempted_at.timestamp()) if row.attempted_at else 0,
            )
            if key in seen:
                continue
            row.request_id = f"ssh:{key[4]}:{key[1]}:{key[2]}:{key[3]}"
            await self._attempts.create(row)
            seen.add(key)
            created += 1
        if created:
            await self._session.commit()
            logger.info("ssh_attempts_synced", count=created)

    async def unlock_ip(self, entry_id: UUID, *, unlocked_by: UUID | None, note: str | None):
        entry = await self._blacklist.get_by_id(entry_id)
        if entry is None:
            raise NotFoundError("Blacklist entry not found.")
        entry = await self._blacklist.unlock(
            entry,
            unlocked_by=unlocked_by,
            note=note or "unlocked by administrator",
        )
        await self._session.commit()
        invalidate_security_caches()
        return entry

    async def block_ip(
        self,
        *,
        ip: str,
        reason: str,
        blocked_until: datetime | None,
        blocked_by: UUID | None,
        user_agent: str | None = None,
    ) -> object:
        entry = await self._blacklist.upsert_block(
            ip=ip.strip(),
            reason=reason or "Manual block by administrator",
            failed_attempt_count=0,
            blocked_until=blocked_until,
            fingerprint=None,
            user_agent=user_agent,
        )
        await self._session.commit()
        invalidate_security_caches()
        logger.warning("ip_manual_block", ip=ip, by=str(blocked_by), reason=reason)
        return entry

    async def list_firewall_rules(self) -> list[FirewallRule]:
        return await self._firewall.list_all()

    async def create_firewall_rule(
        self,
        *,
        cidr: str,
        action: str,
        note: str | None,
        created_by: UUID | None,
    ) -> FirewallRule:
        action = action.strip().lower()
        if action not in {"allow", "deny"}:
            raise AppException("action must be allow or deny", code="firewall_bad_action")
        cidr = cidr.strip()
        try:
            ipaddress.ip_network(cidr, strict=False)
        except ValueError as exc:
            raise AppException(f"Invalid CIDR: {cidr}", code="firewall_bad_cidr") from exc
        rule = FirewallRule(
            cidr=cidr,
            action=action,
            note=note,
            enabled=True,
            created_by_user_id=created_by,
        )
        saved = await self._firewall.create(rule)
        await self._session.commit()
        invalidate_security_caches()
        return saved

    async def delete_firewall_rule(self, rule_id: UUID) -> None:
        rule = await self._firewall.get(rule_id)
        if rule is None:
            raise NotFoundError("Firewall rule not found.")
        await self._firewall.delete(rule)
        await self._session.commit()
        invalidate_security_caches()

    async def list_blocked_actions(self) -> list[BlockedAction]:
        return await self._blocked.list_all()

    def known_blockable_actions(self) -> list[dict[str, str]]:
        return list(KNOWN_BLOCKABLE_ACTIONS)

    async def set_blocked_action(
        self,
        *,
        action_key: str,
        enabled: bool,
        reason: str | None,
        created_by: UUID | None,
        label: str | None = None,
    ) -> BlockedAction:
        known = {a["key"]: a["label"] for a in KNOWN_BLOCKABLE_ACTIONS}
        if action_key not in known and not action_key.replace(".", "").replace("_", "").isalnum():
            raise AppException("Invalid action key", code="blocked_action_invalid")
        entry = await self._blocked.upsert(
            action_key=action_key,
            label=label or known.get(action_key, action_key),
            reason=reason,
            enabled=enabled,
            created_by=created_by,
        )
        await self._session.commit()
        invalidate_security_caches()
        return entry

    async def unblock_action(self, action_key: str) -> None:
        deleted = await self._blocked.delete_by_key(action_key)
        if not deleted:
            raise NotFoundError("Blocked action not found.")
        await self._session.commit()
        invalidate_security_caches()

    async def list_action_logs(self, limit: int = 200) -> list[SystemActionLog]:
        return await self._actions.list_recent(limit=limit)

    async def clear_security_logs(
        self,
        *,
        clear_attempts: bool = True,
        clear_actions: bool = True,
        clear_terminal: bool = True,
        actor_user_id: UUID | None = None,
        actor_username: str | None = None,
        ip_address: str | None = None,
    ) -> dict[str, int]:
        """Delete persisted security audit rows. SSH journal events are not wiped."""
        from app.repositories.terminal_audit import TerminalAuditRepository

        counts = {"attempts": 0, "actions": 0, "terminal": 0}
        if clear_attempts:
            counts["attempts"] = await self._attempts.clear_all()
            # SSH logins are topped up from the host journal on every read, so
            # without a cutoff the rows just deleted come straight back.
            default_watermarks().set(SSH_ATTEMPTS)
        if clear_actions:
            counts["actions"] = await self._actions.clear_all()
        if clear_terminal:
            counts["terminal"] = await TerminalAuditRepository(self._session).clear_all()

        summary = (
            f"Security logs cleared — attempts {counts['attempts']}, "
            f"actions {counts['actions']}, terminal {counts['terminal']}"
        )
        self._session.add(
            SystemActionLog(
                actor_user_id=actor_user_id,
                actor_username=actor_username,
                source="web",
                method="POST",
                path="/api/v1/security/logs/clear",
                action_key="security.admin",
                status_code=200,
                ip_address=ip_address or "unknown",
                summary=summary,
                success=True,
            )
        )
        await self._session.commit()
        logger.warning(
            "security_logs_cleared",
            attempts=counts["attempts"],
            actions=counts["actions"],
            terminal=counts["terminal"],
        )
        return counts

    async def record_action_log(self, log: SystemActionLog) -> SystemActionLog:
        saved = await self._actions.create(log)
        await self._session.commit()
        return saved

    @staticmethod
    def _parse_ip(value: str) -> Any:
        raw = (value or "").strip().strip("[]")
        if "%" in raw:
            raw = raw.split("%", 1)[0]
        try:
            parsed = ipaddress.ip_address(raw)
        except ValueError:
            return None
        mapped = getattr(parsed, "ipv4_mapped", None)
        return mapped or parsed

    @staticmethod
    def _ip_in_cidr(ip: Any, cidr: str) -> bool:
        try:
            network = ipaddress.ip_network(cidr, strict=False)
        except ValueError:
            return False
        return ip in network

    def _read_ssh_logins(self, *, limit: int = 40) -> list[AccessAttempt]:
        """Best-effort parse of recent SSH auth events from the journal."""
        rows: list[AccessAttempt] = []
        try:
            proc = subprocess.run(
                [
                    "journalctl",
                    "-u",
                    "ssh",
                    "-u",
                    "sshd",
                    "-n",
                    "200",
                    "--no-pager",
                    "-o",
                    "short-iso",
                ],
                capture_output=True,
                text=True,
                timeout=4,
                check=False,
            )
            text = proc.stdout or ""
        except (OSError, subprocess.TimeoutExpired):
            return rows

        accepted = re.compile(
            r"^(?P<ts>\S+)\s+\S+\s+\S+:\s+Accepted\s+\S+\s+for\s+(?P<user>\S+)\s+from\s+(?P<ip>\S+)",
            re.I,
        )
        failed = re.compile(
            r"^(?P<ts>\S+)\s+\S+\s+\S+:\s+Failed\s+\S+\s+for\s+(?:invalid user\s+)?(?P<user>\S+)\s+from\s+(?P<ip>\S+)",
            re.I,
        )
        for line in reversed(text.splitlines()):
            m = accepted.search(line) or failed.search(line)
            if not m:
                continue
            success = bool(accepted.search(line))
            try:
                ts = datetime.fromisoformat(m.group("ts").replace("Z", "+00:00"))
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=UTC)
            except ValueError:
                ts = datetime.now(UTC)
            rows.append(
                AccessAttempt(
                    id=uuid4(),
                    attempted_at=ts,
                    ip_address=m.group("ip"),
                    username_or_email=m.group("user"),
                    user_id=None,
                    event_type="login_success" if success else "login_failure",
                    success=success,
                    failure_reason=None if success else "ssh_auth_failed",
                    device_fingerprint=None,
                    user_agent="sshd",
                    request_id=None,
                    source="ssh",
                )
            )
            if len(rows) >= limit:
                break
        return rows
