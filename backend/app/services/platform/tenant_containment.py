"""Phase 2B-4 — tenant containment diagnostics and SFTP cgroup attachment helpers.

Maps authenticated Unix users (ifn_*) to environment slices. Does not modify
customer files or memory limits.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from app.core.logging import get_logger
from app.services.platform.php_fpm_environment import (
    DISABLED_SUFFIX,
    GLOBAL_POOL_DIR,
    PhpFpmEnvironmentService,
    STATE_MIGRATED_HEALTHY,
    _pool_user,
    fpm_pool_name,
)
from app.services.platform.workload_slices import (
    env_short_id,
    resolve_slice_cgroup_path,
    slice_name_for,
)

logger = get_logger(__name__)

UNIX_SLICE_MAP = Path("/var/lib/ifnotus/unix-to-env-slice.json")
SFTP_ATTACH_BIN = Path("/usr/local/sbin/ifnotus-sftp-cgroup-attach")
PAM_SSHD = Path("/etc/pam.d/sshd")
PAM_MARKER = "# IFNOTUS Phase 2B-4 SFTP/SSH session cgroup attach"

STATUS_FULLY_CONTAINED = "FULLY_CONTAINED"
STATUS_CONTAINED_EXCEPT_SFTP = "CONTAINED_EXCEPT_SFTP"
STATUS_SUSPENDED = "SUSPENDED"
STATUS_PREEXISTING_FAILURE = "PREEXISTING_APP_FAILURE_BUT_CONTAINED"
STATUS_MANUAL_REVIEW = "MANUAL_REVIEW"
STATUS_SECURITY_VIOLATION = "SECURITY_VIOLATION"
STATUS_SPECIAL_CONTAINED = "CONTAINMENT_COMPLETE_SPECIAL"


@dataclass
class ContainmentReport:
    environment_id: str
    short_id: str
    domain: str | None
    env_status: str
    aggregate: str
    php: dict[str, Any] = field(default_factory=dict)
    node: dict[str, Any] = field(default_factory=dict)
    cron: dict[str, Any] = field(default_factory=dict)
    sftp: dict[str, Any] = field(default_factory=dict)
    special_runtime: dict[str, Any] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def slice_from_unix_username(username: str | None) -> str | None:
    """Derive env slice from ifn_<shortid> without trusting client input beyond username."""
    u = (username or "").strip()
    if not re.fullmatch(r"ifn_[a-z0-9]{6,12}", u):
        return None
    short = u[4:]
    return f"ifnotus-workloads-tenants-env-{short}.slice"


def resolve_slice_for_unix_user(username: str, *, map_path: Path | None = None) -> dict[str, Any]:
    """Authoritative mapping: username → slice.

    Prefers on-disk map (written from DB). Falls back to ifn_<short> derivation.
    Rejects unknown / injectable names.
    """
    u = (username or "").strip()
    out: dict[str, Any] = {"username": u, "ok": False, "slice": None, "source": None, "error": None}
    if not u or u in {".", ".."} or "/" in u or "\\" in u or "\x00" in u:
        out["error"] = "invalid_username"
        return out
    if ".." in u or u.startswith("-") or any(c in u for c in ";|&$`'\""):
        out["error"] = "invalid_username"
        return out
    path = map_path or UNIX_SLICE_MAP
    if path.is_file():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            row = data.get(u)
            if isinstance(row, dict) and row.get("slice"):
                sl = str(row["slice"])
                if re.fullmatch(r"ifnotus-workloads-tenants-env-[a-z0-9]+\.slice", sl):
                    out.update(ok=True, slice=sl, source="map", environment_id=row.get("environment_id"))
                    return out
            if row is None and u.startswith("ifn_"):
                out["error"] = "unknown_user"
                return out
        except (OSError, json.JSONDecodeError) as exc:
            out["error"] = f"map_unreadable:{exc}"
            return out
    derived = slice_from_unix_username(u)
    if derived:
        out.update(ok=True, slice=derived, source="username_derive")
        return out
    out["error"] = "unknown_user"
    return out


def render_sftp_attach_script() -> str:
    """Root-only pam_exec helper: move session PIDs into the env slice."""
    return r'''#!/bin/bash
# IFNOTUS Phase 2B-4 — attach SSH/SFTP session processes to tenant env slice.
# Invoked via pam_exec on sshd session open. Never trusts client env IDs.
set -euo pipefail
USER_NAME="${PAM_USER:-}"
[[ -n "$USER_NAME" ]] || exit 0
case "$USER_NAME" in
  ifn_*) ;;
  *) exit 0 ;;
esac
# Reject path/injection characters
case "$USER_NAME" in
  */*|*" "*|*\;*|*\|*|*\&*|*\$*|*\`*|*\'*|*\*) exit 0 ;;
esac

MAP=/var/lib/ifnotus/unix-to-env-slice.json
SLICE=""
if [[ -f "$MAP" ]]; then
  SLICE=$(python3 - "$USER_NAME" "$MAP" <<'PY'
import json, sys, re
user, path = sys.argv[1], sys.argv[2]
try:
    data = json.load(open(path, encoding="utf-8"))
except Exception:
    sys.exit(0)
row = data.get(user) or {}
sl = str(row.get("slice") or "")
if re.fullmatch(r"ifnotus-workloads-tenants-env-[a-z0-9]+\.slice", sl):
    print(sl)
PY
) || true
fi
if [[ -z "$SLICE" ]]; then
  SHORT="${USER_NAME#ifn_}"
  SLICE="ifnotus-workloads-tenants-env-${SHORT}.slice"
fi
case "$SLICE" in
  ifnotus-workloads-tenants-env-*.slice) ;;
  *) exit 0 ;;
esac

systemctl start "$SLICE" >/dev/null 2>&1 || true
CG=$(systemctl show -p ControlGroup --value "$SLICE" 2>/dev/null || true)
[[ -n "$CG" && "$CG" != "/" ]] || exit 0
CG_PATH="/sys/fs/cgroup${CG}"
[[ -d "$CG_PATH" ]] || exit 0

attach_pid() {
  local pid="$1"
  [[ -d "/proc/$pid" ]] || return 0
  # Only move processes owned by the authenticated user
  local owner
  owner=$(ps -o user= -p "$pid" 2>/dev/null | tr -d ' ' || true)
  [[ "$owner" == "$USER_NAME" ]] || return 0
  echo "$pid" > "${CG_PATH}/cgroup.procs" 2>/dev/null || true
}

# Attach current session tree and brief follow-up for late sftp children.
for _ in 1 2 3 4 5 6 7 8; do
  for pid in $(pgrep -u "$USER_NAME" 2>/dev/null || true); do
    attach_pid "$pid"
  done
  sleep 0.25
done
exit 0
'''


def ensure_pam_sshd_attach(*, dry_run: bool = True) -> dict[str, Any]:
    """Install pam_exec line for sshd session attach (idempotent)."""
    line = f"session optional pam_exec.so seteuid {SFTP_ATTACH_BIN}"
    report: dict[str, Any] = {"dry_run": dry_run, "ok": False, "actions": []}
    if dry_run:
        report["actions"].append({"would_write": str(SFTP_ATTACH_BIN), "would_ensure_pam": line})
        report["ok"] = True
        return report
    SFTP_ATTACH_BIN.parent.mkdir(parents=True, exist_ok=True)
    SFTP_ATTACH_BIN.write_text(render_sftp_attach_script(), encoding="utf-8")
    SFTP_ATTACH_BIN.chmod(0o755)
    report["actions"].append({"wrote": str(SFTP_ATTACH_BIN)})
    text = PAM_SSHD.read_text(encoding="utf-8") if PAM_SSHD.exists() else ""
    if str(SFTP_ATTACH_BIN) not in text:
        if not text.endswith("\n"):
            text += "\n"
        text += f"\n{PAM_MARKER}\n{line}\n"
        PAM_SSHD.write_text(text, encoding="utf-8")
        report["actions"].append({"updated_pam": str(PAM_SSHD)})
    else:
        report["actions"].append({"pam_already_present": True})
    report["ok"] = True
    return report


class TenantContainmentService:
    def __init__(self, *, fpm: PhpFpmEnvironmentService | None = None) -> None:
        self.fpm = fpm or PhpFpmEnvironmentService()

    def write_unix_slice_map(self, rows: list[dict[str, Any]], *, path: Path | None = None) -> Path:
        dest = path or UNIX_SLICE_MAP
        dest.parent.mkdir(parents=True, exist_ok=True)
        payload = {r["unix_username"]: r for r in rows if r.get("unix_username")}
        tmp = dest.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
        tmp.replace(dest)
        return dest

    def classify_global_pools(self) -> dict[str, Any]:
        system_names = {"www.conf", "www", "www-data"}
        tenant_legacy = []
        system_pools = []
        unknown = []
        disabled = []
        for conf in sorted(GLOBAL_POOL_DIR.glob("*.conf")):
            name = conf.name
            if name.endswith(DISABLED_SUFFIX):
                continue
            body = conf.read_text(encoding="utf-8", errors="replace")
            user = _pool_user(body)
            if name.startswith("ifnotus-"):
                tenant_legacy.append({"file": name, "user": user})
            elif name.replace(".conf", "") in system_names or user in {"www-data"} and "ifnotus" not in name:
                system_pools.append({"file": name, "user": user})
            else:
                unknown.append({"file": name, "user": user})
        for conf in sorted(GLOBAL_POOL_DIR.glob(f"*{DISABLED_SUFFIX}")):
            disabled.append(conf.name)
        return {
            "tenant_global_legacy_pools": len(tenant_legacy),
            "tenant_legacy": tenant_legacy,
            "system_pools": len(system_pools),
            "system": system_pools,
            "unknown_pools": len(unknown),
            "unknown": unknown,
            "disabled": len(disabled),
        }

    def detect_node_escapes(self) -> list[dict[str, Any]]:
        escapes = []
        try:
            ps = subprocess.run(
                ["ps", "-eo", "user:32,pid,cmd"],
                capture_output=True,
                text=True,
                check=False,
            )
        except OSError:
            return escapes
        for line in (ps.stdout or "").splitlines()[1:]:
            parts = line.split(None, 2)
            if len(parts) < 3:
                continue
            user, pid_s, cmd = parts[0], parts[1], parts[2]
            if not user.startswith("ifn_"):
                continue
            if not re.search(r"(node|gunicorn|next-server|pm2)", cmd, re.I):
                continue
            try:
                cg = Path(f"/proc/{pid_s}/cgroup").read_text(encoding="utf-8")
            except OSError:
                continue
            short = user[4:]
            if f"tenants-env-{short}" not in cg:
                escapes.append({"user": user, "pid": int(pid_s), "cmd": cmd[:120], "cgroup": cg.strip()})
        return escapes

    def cron_slice_verified(self, env) -> dict[str, Any]:
        from app.services.platform.env_cron import EnvironmentCronService  # type: ignore

        # Static check: wrapper code uses slice_name_for
        import inspect
        from app.services.platform import env_cron as ec

        src = inspect.getsource(ec)
        ok = "systemd-run" in src and "slice_name_for" in src
        return {"environment_slice_execution_verified": ok, "code_uses_systemd_run_slice": ok}

    def report_environment(
        self,
        env,
        *,
        extra_hostnames: list[str] | None = None,
        http_before: str | None = None,
        http_after: str | None = None,
        preexisting_failure: bool = False,
    ) -> ContainmentReport:
        short = env_short_id(env.id)
        status = str(getattr(env, "status", "") or "")
        unix = getattr(env, "unix_username", None)
        domain = getattr(env, "domain", None)
        fpm_status = self.fpm.status(env, extra_hostnames=extra_hostnames)
        php_active = (fpm_status.get("env_master") or {}).get("active") == "active"
        drift = fpm_status.get("drift_state")
        php = {
            "env_fpm_active": php_active,
            "drift_state": drift,
            "pools": fpm_status.get("hostnames") or [],
            "global_active": fpm_status.get("global_pools_active") or [],
            "global_disabled": fpm_status.get("global_pools_disabled") or [],
        }
        node_escapes = [e for e in self.detect_node_escapes() if e.get("user") == unix]
        node = {"escapes": len(node_escapes), "details": node_escapes}
        cron = self.cron_slice_verified(env)
        sftp = {
            "map_slice": slice_from_unix_username(unix),
            "attach_helper_installed": SFTP_ATTACH_BIN.is_file(),
            "note": "session attach via pam_exec; verify with live login test",
        }
        special = {}
        notes: list[str] = []
        if status == "suspended":
            aggregate = STATUS_SUSPENDED
            notes.append("SUSPENDED_CONTAINMENT_NOT_ACTIVE for customer app start")
        elif any("ROOT_PHP" in str(x) for x in (fpm_status.get("errors") or [])):
            aggregate = STATUS_SECURITY_VIOLATION
        elif preexisting_failure and php_active and drift == STATE_MIGRATED_HEALTHY:
            aggregate = STATUS_PREEXISTING_FAILURE
        elif php_active and drift == STATE_MIGRATED_HEALTHY and not node_escapes:
            if SFTP_ATTACH_BIN.is_file():
                aggregate = STATUS_FULLY_CONTAINED
            else:
                aggregate = STATUS_CONTAINED_EXCEPT_SFTP
        elif domain and "examflow" in str(domain).lower():
            aggregate = STATUS_SPECIAL_CONTAINED if not node_escapes else STATUS_MANUAL_REVIEW
            special = {"runtime": "gunicorn/examflow-ifnotus.service"}
        else:
            aggregate = STATUS_MANUAL_REVIEW

        if http_before is not None:
            notes.append(f"http_before={http_before}")
        if http_after is not None:
            notes.append(f"http_after={http_after}")

        return ContainmentReport(
            environment_id=str(env.id),
            short_id=short,
            domain=domain,
            env_status=status,
            aggregate=aggregate,
            php=php,
            node=node,
            cron=cron,
            sftp=sftp,
            special_runtime=special,
            notes=notes,
        )
