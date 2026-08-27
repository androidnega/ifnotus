#!/usr/bin/env python3
"""IFNOTUS live full-system test harness.

Runs against production API from the VPS (or any host with app env).
Mints JWTs server-side (no password needed). Exercises:
  - public catalog/health/SPA
  - customer signup (OTP from Redis/file) + portal APIs
  - staff privilege matrix (superadmin + act_as roles)
  - AI settings / sessions
  - hosting env probes

Usage (on VPS):
  cd /srv/apps/ifnotus/backend && set -a && . .env && set +a
  ./.venv/bin/python /tmp/ifnotus_full_system_test.py
"""

from __future__ import annotations

import json
import os
import sys
import time
import traceback
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

PUBLIC_BASE = os.environ.get("IFNOTUS_PUBLIC_URL", "https://ifnotus.space").rstrip("/")
# Prefer local uvicorn for staff tests (admin IP lockdown applies to public edge).
BASE = os.environ.get("IFNOTUS_BASE_URL", "http://127.0.0.1:8010").rstrip("/")
API = f"{BASE}/api/v1"
RESULTS: list[dict[str, Any]] = []


def record(section: str, name: str, ok: bool, detail: str = "", *, fix_hint: str = "") -> None:
    RESULTS.append(
        {
            "section": section,
            "name": name,
            "ok": ok,
            "detail": detail[:500],
            "fix_hint": fix_hint,
        }
    )
    mark = "PASS" if ok else "FAIL"
    extra = f" — {detail[:180]}" if detail else ""
    print(f"[{mark}] {section} :: {name}{extra}")


def req(
    method: str,
    path: str,
    *,
    token: str | None = None,
    body: dict[str, Any] | None = None,
    timeout: float = 45.0,
) -> tuple[int, Any]:
    url = path if path.startswith("http") else f"{API}{path}"
    data = None
    headers = {
        "Accept": "application/json",
        "User-Agent": "ifnotus-full-system-test/1.0",
        "Connection": "close",
    }
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(url, data=data, headers=headers, method=method.upper())
    try:
        with urllib.request.urlopen(request, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8") or "{}"
            try:
                payload = json.loads(raw)
            except json.JSONDecodeError:
                payload = {"raw": raw[:400]}
            return int(resp.status), payload
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8") or "{}"
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            payload = {"raw": raw[:400]}
        return int(exc.code), payload
    except Exception as exc:  # noqa: BLE001
        return 0, {"error": str(exc)}


def expect_status(
    section: str,
    name: str,
    code: int,
    wanted: set[int] | int,
    payload: Any = None,
    *,
    fix_hint: str = "",
) -> bool:
    want = {wanted} if isinstance(wanted, int) else set(wanted)
    ok = code in want
    detail = f"HTTP {code}"
    if isinstance(payload, dict):
        msg = (
            (payload.get("error") or {}).get("message")
            if isinstance(payload.get("error"), dict)
            else payload.get("detail") or payload.get("message") or payload.get("status")
        )
        if msg:
            detail += f" · {msg}"
    record(section, name, ok, detail, fix_hint=fix_hint)
    return ok


# ─── token minting (in-process) ───────────────────────────────────────────────

def mint_tokens() -> dict[str, str]:
    """Import app settings and mint access tokens for known users."""
    # Ensure backend is on path
    sys.path.insert(0, "/srv/apps/ifnotus/backend")
    os.chdir("/srv/apps/ifnotus/backend")

    from app.core.config import get_settings
    from app.core.security import create_token_pair

    get_settings.cache_clear()
    settings = get_settings()

    # Fixed IDs from live DB (queried earlier / refreshed below)
    import asyncio
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine

    async def load_ids() -> dict[str, UUID]:
        eng = create_async_engine(str(settings.database_url))
        out: dict[str, UUID] = {}
        async with eng.connect() as c:
            rows = (
                await c.execute(text("select id, email, roles, is_superuser, is_active from users"))
            ).fetchall()
            for uid, email, roles, is_super, is_active in rows:
                out[str(email)] = uid
                if is_super and "superadmin" in (roles or []):
                    out["__superadmin__"] = uid
            # Prefer an active portal customer that still owns a hosting environment.
            # Never mint tokens for soft-deleted accounts (email starts with deleted+).
            cust_rows = (
                await c.execute(
                    text(
                        """
                        select u.id
                        from users u
                        join customers c on c.user_id = u.id
                        join customer_environments e on e.customer_id = c.id
                        where u.is_active is true
                          and u.roles::text like '%customer%'
                          and u.email not ilike 'deleted+%'
                        order by
                          case when u.email ilike '%demo30%' then 0 else 1 end,
                          e.created_at desc nulls last
                        limit 1
                        """
                    )
                )
            ).fetchall()
            if cust_rows:
                out["__customer_demo__"] = cust_rows[0][0]
            else:
                # Fallback: any active customer role (may have no env yet).
                fallback = (
                    await c.execute(
                        text(
                            """
                            select id from users
                            where is_active is true
                              and roles::text like '%customer%'
                              and email not ilike 'deleted+%'
                            order by created_at desc nulls last
                            limit 1
                            """
                        )
                    )
                ).fetchall()
                if fallback:
                    out["__customer_demo__"] = fallback[0][0]
        await eng.dispose()
        return out

    ids = asyncio.run(load_ids())
    tokens: dict[str, str] = {}

    super_id = ids.get("__superadmin__") or ids.get("admin@ifnotus.local")
    if not super_id:
        raise RuntimeError("No superadmin user found")

    tokens["superadmin"] = create_token_pair(settings, subject=super_id).access_token
    for role in ("admin", "operator", "viewer", "customer_care"):
        tokens[f"as_{role}"] = create_token_pair(
            settings, subject=super_id, act_as_role=role
        ).access_token

    cust = ids.get("__customer_demo__")
    if cust:
        tokens["customer"] = create_token_pair(settings, subject=cust).access_token

    # dual-role superadmin who also has customer profile (ahantapuls)
    dual = ids.get("ahantapuls@gmail.com")
    if dual:
        tokens["dual_super"] = create_token_pair(settings, subject=dual).access_token

    return tokens


def read_otp(*, phone: str, challenge_id: str | None = None) -> tuple[str, str] | None:
    """Return (challenge_id, code) from Redis or file store."""
    sys.path.insert(0, "/srv/apps/ifnotus/backend")
    from app.services.platform import phone_otp

    # Direct Redis lookup by challenge id
    try:
        import redis

        r = redis.Redis.from_url(os.environ.get("REDIS_URL", "redis://127.0.0.1:6379/0"), decode_responses=True)
        if challenge_id:
            raw = r.get(f"ifnotus:phone_otp:{challenge_id}")
            if raw:
                data = json.loads(raw)
                if not data.get("consumed"):
                    return data["challenge_id"], data["code"]
            # phone → challenge map
            mapped = r.get(f"ifnotus:phone_otp:phone:{phone}")
            if mapped:
                raw2 = r.get(f"ifnotus:phone_otp:{mapped}")
                if raw2:
                    data = json.loads(raw2)
                    if not data.get("consumed"):
                        return data["challenge_id"], data["code"]
        for key in r.scan_iter(match="ifnotus:phone_otp:*", count=200):
            if "attempts" in key or "cooldown" in key or key.endswith(f"phone:{phone}"):
                continue
            raw = r.get(key)
            if not raw:
                continue
            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if not isinstance(data, dict):
                continue
            if phone[-9:] in str(data.get("phone", "")) and not data.get("consumed"):
                return data["challenge_id"], data["code"]
    except Exception:  # noqa: BLE001
        pass

    challenges = phone_otp._load_file()  # noqa: SLF001
    if challenge_id and challenge_id in challenges:
        ch = challenges[challenge_id]
        if not ch.consumed and not ch.is_expired():
            return ch.challenge_id, ch.code
    for ch in sorted(challenges.values(), key=lambda c: c.created_at, reverse=True):
        if ch.phone.endswith(phone[-9:]) or phone in ch.phone:
            if not ch.consumed and not ch.is_expired():
                return ch.challenge_id, ch.code
    return None


# ─── test sections ────────────────────────────────────────────────────────────

def test_public() -> None:
    sec = "public"
    code, health = req("GET", "/health")
    expect_status(sec, "GET /health", code, 200, health)
    if code == 200:
        record(sec, "health.status", health.get("status") == "healthy", str(health.get("status")))

    code, meta = req("GET", "/catalog/meta")
    expect_status(sec, "GET /catalog/meta", code, 200, meta)
    if isinstance(meta, dict):
        record(
            sec,
            "student_zone",
            meta.get("student_zone") == "ifnotus.space",
            str(meta.get("student_zone")),
        )

    code, plans = req("GET", "/catalog/plans")
    expect_status(sec, "GET /catalog/plans", code, 200, plans)
    items = []
    if isinstance(plans, dict):
        items = plans.get("items") or plans.get("plans") or []
    elif isinstance(plans, list):
        items = plans
    live = []
    for p in items:
        card = p.get("catalog_card") if isinstance(p, dict) else None
        status = None
        if isinstance(card, dict):
            status = card.get("product_status")
        if not status and isinstance(p, dict):
            status = p.get("product_status") or ((p.get("capabilities") or {}).get("production") or {}).get(
                "product_status"
            )
        if str(status or "").lower() == "live":
            live.append(p)
    record(sec, "plans catalog_card.product_status=live", len(live) >= 1, f"{len(live)}/{len(items)} live")

    for path, label in [
        ("/", "SPA /"),
        ("/plans", "SPA /plans"),
        ("/login", "SPA /login"),
        ("/signup", "SPA /signup"),
        ("/admin_1", "SPA /admin_1"),
        ("/panel", "SPA /panel"),
        ("/account", "SPA /account"),
    ]:
        code, _ = req("GET", f"{PUBLIC_BASE}{path}")
        expect_status(sec, label, code, {200, 301, 302}, fix_hint="nginx frontend sync")

    code, _ = req("GET", "/platform/capacity")
    expect_status(sec, "unauth platform capacity blocked", code, {401, 403})


def test_customer(tokens: dict[str, str]) -> None:
    sec = "customer"
    tok = tokens.get("customer")
    if not tok:
        record(sec, "customer token", False, "demo30 user missing")
        return

    code, me = req("GET", "/auth/me", token=tok)
    expect_status(sec, "GET /auth/me", code, 200, me)
    if isinstance(me, dict):
        roles = me.get("roles") or []
        record(sec, "role=customer", "customer" in roles, str(roles))

    code, dash = req("GET", "/customers/dashboard", token=tok)
    expect_status(sec, "GET /customers/dashboard", code, 200, dash)

    code, envs = req("GET", "/customers/environments", token=tok)
    expect_status(sec, "GET /customers/environments", code, {200, 404}, envs)
    env_list = []
    if isinstance(envs, list):
        env_list = envs
    elif isinstance(envs, dict):
        env_list = envs.get("environments") or envs.get("items") or []

    if isinstance(dash, dict) and not env_list:
        env_list = dash.get("environments") or []

    if env_list:
        env = env_list[0]
        eid = env.get("id")
        record(sec, "has environment", True, f"id={eid} status={env.get('status')}")
        for path, label in [
            (f"/customers/environments/{eid}", "env detail"),
            (f"/customers/environments/{eid}/files?path=.", "files list"),
            (f"/customers/environments/{eid}/usage", "usage"),
            (f"/customers/environments/{eid}/backups", "backups"),
        ]:
            c, p = req("GET", path, token=tok)
            expect_status(sec, label, c, {200, 404, 403}, p)
    else:
        record(sec, "has environment", False, "no envs on demo customer", fix_hint="provision demo env")

    # staff panel must be blocked for pure customer
    for path, label in [
        ("/dashboard", "staff dashboard blocked"),
        ("/platform/customers", "platform customers blocked"),
        ("/ai/settings", "AI settings blocked"),
        ("/terminal/execute", "terminal blocked"),
    ]:
        c, p = req("GET" if "execute" not in path else "POST", path, token=tok, body={"command": "echo hi"} if "execute" in path else None)
        expect_status(sec, label, c, {401, 403, 404, 405}, p)


def test_signup_flow() -> str | None:
    """Full phone OTP signup with a disposable test number. Returns new access token if created."""
    sec = "signup"
    phone = f"+23320{int(time.time()) % 10000000:07d}"
    # Keep within Ghana mobile shape
    phone = "+233209998877"

    code, resp = req("POST", "/customers/phone/request-otp", body={"phone": phone})
    # May be rate-limited or validation
    if code not in (200, 201):
        # try alternate unused number
        phone = "+233208881122"
        code, resp = req("POST", "/customers/phone/request-otp", body={"phone": phone})

    expect_status(sec, "request-otp", code, {200, 201, 429}, resp, fix_hint="OTP limiter / SMS")
    if code == 429:
        record(sec, "signup continue", False, "rate limited — skipping live OTP verify")
        return None
    if code not in (200, 201):
        return None

    challenge_id = (resp or {}).get("challenge_id")
    # SMS debug mode intentionally returns debug_code so login works without SMS.
    dbg = (resp or {}).get("debug_code")
    sms_debug = os.environ.get("SMS_DEBUG_MODE", "").lower() in {"1", "true", "yes"}
    if sms_debug:
        record(sec, "sms debug_code present", bool(dbg), f"debug_code={dbg!r}")
    else:
        record(sec, "no debug_code leaked", not dbg, f"debug_code={dbg!r}")

    time.sleep(0.5)
    otp = read_otp(phone=phone, challenge_id=challenge_id)
    if not otp:
        record(
            sec,
            "read OTP from store",
            False,
            f"challenge_id={challenge_id} sms_sent={(resp or {}).get('sms_sent')}",
            fix_hint="SMS provider down; Redis challenge missing",
        )
        return None
    cid, otp_code = otp
    record(sec, "read OTP from store", True, f"challenge={cid} sms_sent={(resp or {}).get('sms_sent')}")

    code, login = req(
        "POST",
        "/customers/phone/verify-otp",
        body={"phone": phone, "challenge_id": cid, "code": otp_code},
    )
    expect_status(sec, "verify-otp", code, 200, login)
    if code != 200:
        return None

    token = (login or {}).get("access_token")
    if not token:
        record(sec, "access_token issued", False, str(login)[:200])
        return None
    record(sec, "access_token issued", True)

    # Progressive profile
    code, me = req("GET", "/customers/me", token=token)
    expect_status(sec, "GET /customers/me", code, 200, me)

    stamp = int(time.time())
    email = f"test.audit.{stamp}@ifnotus.space"
    code, patched = req(
        "PATCH",
        "/customers/me",
        token=token,
        body={
            "first_name": "Test",
            "last_name": "Audit",
            "email": email,
            "password": "TestAudit!23456",
        },
        timeout=90.0,
    )
    if code == 0:
        # Fallback: complete-profile endpoint
        code, patched = req(
            "POST",
            "/customers/me/complete-profile",
            token=token,
            body={
                "first_name": "Test",
                "last_name": "Audit",
                "email": email,
                "password": "TestAudit!23456",
            },
            timeout=90.0,
        )
        expect_status(sec, "POST /customers/me/complete-profile fallback", code, {200, 201}, patched)
    else:
        expect_status(sec, "PATCH /customers/me profile", code, {200, 201}, patched)

    code, me2 = req("GET", "/customers/me", token=token)
    if code == 200 and isinstance(me2, dict):
        record(
            sec,
            "can_order or missing_for_order present",
            "can_order" in me2 or "missing_for_order" in me2 or me2.get("profile_complete") is not None,
            f"can_order={me2.get('can_order')} stage={me2.get('onboarding_stage')} email={me2.get('email')}",
        )

    # Returning login with password
    code, relogin = req(
        "POST",
        "/customers/login",
        body={"email": email, "password": "TestAudit!23456"},
        timeout=60.0,
    )
    expect_status(sec, "customer password login", code, {200, 401, 403}, relogin)
    # 200 preferred; device challenge may return different status
    if code == 200 and (relogin or {}).get("access_token"):
        record(sec, "password login token", True)
    elif code == 200 and (relogin or {}).get("status") in ("device_challenge", "totp_required", "challenge"):
        record(sec, "password login challenge", True, str((relogin or {}).get("status")))

    return token


def test_staff_privileges(tokens: dict[str, str]) -> None:
    sec = "staff"

    # Endpoint → allowed roles (approximate from permissions)
    matrix: list[tuple[str, str, set[str]]] = [
        ("GET", "/auth/me", {"superadmin", "as_admin", "as_operator", "as_viewer", "as_customer_care"}),
        ("GET", "/dashboard", {"superadmin", "as_admin", "as_operator", "as_viewer"}),
        ("GET", "/monitoring", {"superadmin", "as_admin", "as_operator", "as_viewer"}),
        ("GET", "/monitoring/metrics", {"superadmin", "as_admin", "as_operator", "as_viewer"}),
        ("GET", "/server/overview", {"superadmin", "as_admin", "as_operator", "as_viewer"}),
        ("GET", "/applications", {"superadmin", "as_admin", "as_operator", "as_viewer"}),
        ("GET", "/domains", {"superadmin", "as_admin", "as_operator", "as_viewer"}),
        ("GET", "/files/roots", {"superadmin", "as_admin", "as_operator", "as_viewer"}),
        ("GET", "/databases", {"superadmin", "as_admin", "as_operator", "as_viewer"}),
        ("GET", "/mail/settings", {"superadmin"}),
        ("GET", "/ssl", {"superadmin", "as_admin", "as_operator", "as_viewer"}),
        ("GET", "/operations/overview", {"superadmin", "as_admin", "as_operator", "as_viewer"}),
        ("GET", "/security/blacklist", {"superadmin"}),
        ("GET", "/platform/customers", {"superadmin", "as_admin", "as_operator", "as_viewer", "as_customer_care"}),
        ("GET", "/platform/plans", {"superadmin", "as_admin", "as_operator", "as_viewer", "as_customer_care"}),
        # Orders require customers:manage (billing) — not operator/viewer.
        ("GET", "/platform/orders", {"superadmin", "as_admin", "as_customer_care"}),
        ("GET", "/platform/capacity", {"superadmin", "as_admin", "as_operator", "as_viewer", "as_customer_care"}),
        ("GET", "/support/tickets", {"superadmin", "as_admin", "as_operator", "as_viewer", "as_customer_care"}),
        ("GET", "/ai/settings", {"superadmin"}),
        ("GET", "/ai/sessions", {"superadmin", "as_admin", "as_operator", "as_viewer"}),
    ]

    role_keys = ["superadmin", "as_admin", "as_operator", "as_viewer", "as_customer_care"]
    for method, path, allowed in matrix:
        for role in role_keys:
            tok = tokens.get(role)
            if not tok:
                continue
            code, payload = req(method, path, token=tok)
            should_pass = role in allowed
            # Some paths may 404 if route differs — treat 404 as soft fail for path discovery
            if code == 404 and role == "superadmin":
                record(sec, f"{role} {method} {path}", False, "HTTP 404 route missing", fix_hint="check router mount")
                break
            want = set(range(200, 400)) if should_pass else {401, 403}
            # Unlock/password gates may return 401/422 for some tools — treat 401/403 as deny
            expect_status(
                sec,
                f"{role} {method} {path}",
                code,
                want if should_pass else {401, 403},
                payload,
                fix_hint="permission matrix mismatch",
            )

    # Privilege switch API
    tok = tokens["superadmin"]
    code, switched = req("POST", "/auth/privilege-switch", token=tok, body={"role": "operator"})
    expect_status(sec, "privilege-switch → operator", code, 200, switched)
    if code == 200 and (switched or {}).get("access_token"):
        op_tok = switched["access_token"]
        code2, me = req("GET", "/auth/me", token=op_tok)
        expect_status(sec, "me after privilege-switch", code2, 200, me)
        if isinstance(me, dict):
            record(
                sec,
                "privilege_viewing_as=operator",
                me.get("privilege_viewing_as") == "operator",
                str(me.get("privilege_viewing_as")),
            )
        code3, restored = req("POST", "/auth/privilege-restore", token=op_tok)
        expect_status(sec, "privilege-restore", code3, 200, restored)

    # customer_care must not access terminal
    care = tokens.get("as_customer_care")
    if care:
        code, p = req("POST", "/terminal/execute", token=care, body={"command": "id"})
        expect_status(sec, "customer_care terminal denied", code, {401, 403}, p)


def test_ai(tokens: dict[str, str]) -> None:
    sec = "ai"
    super_tok = tokens["superadmin"]
    code, settings = req("GET", "/ai/settings", token=super_tok)
    expect_status(sec, "GET /ai/settings", code, 200, settings)
    if isinstance(settings, dict):
        record(sec, "AI configured flag present", "configured" in settings, str(settings.get("configured")))

    code, sessions = req("GET", "/ai/sessions", token=super_tok)
    expect_status(sec, "GET /ai/sessions", code, {200, 404}, sessions)

    # Create session if endpoint exists
    code, created = req(
        "POST",
        "/ai/sessions",
        token=super_tok,
        body={"surface": "dashboard", "title": "system-test"},
    )
    expect_status(sec, "POST /ai/sessions", code, {200, 201, 404, 422}, created)

    # Customer care cannot read AI settings
    care = tokens.get("as_customer_care")
    if care:
        code, p = req("GET", "/ai/settings", token=care)
        expect_status(sec, "customer_care AI settings denied", code, {401, 403}, p)

    # Portal AI credits (customer) — canonical route is GET /customers/credits
    cust = tokens.get("customer")
    if cust:
        for path in ("/customers/credits", "/customers/dashboard"):
            code, p = req("GET", path, token=cust)
            if code == 200:
                record(sec, f"customer AI surface {path}", True, "HTTP 200")
                break
        else:
            record(sec, "customer AI credits endpoint", False, "no known path returned 200", fix_hint="check portal AI routes")


def test_platform_ops(tokens: dict[str, str]) -> None:
    sec = "platform"
    tok = tokens["superadmin"]
    code, customers = req("GET", "/platform/customers", token=tok)
    expect_status(sec, "list customers", code, 200, customers)

    code, plans = req("GET", "/platform/plans", token=tok)
    expect_status(sec, "list plans", code, 200, plans)

    code, orders = req("GET", "/platform/orders", token=tok)
    expect_status(sec, "list orders", code, 200, orders)

    code, cap = req("GET", "/platform/capacity", token=tok)
    expect_status(sec, "capacity", code, 200, cap)

    # Viewer cannot write plans
    viewer = tokens.get("as_viewer")
    if viewer and isinstance(plans, list) and plans:
        pid = plans[0].get("id")
        code, p = req("PATCH", f"/platform/plans/{pid}", token=viewer, body={"name": plans[0].get("name")})
        expect_status(sec, "viewer cannot write plans", code, {401, 403, 405}, p)


def test_infra() -> None:
    sec = "infra"
    import subprocess

    for svc in ("ifnotus-api", "ifnotus-worker", "nginx", "redis-server"):
        active = False
        detail = ""
        for _ in range(8):
            r = subprocess.run(["systemctl", "is-active", svc], capture_output=True, text=True)
            detail = (r.stdout or r.stderr or "").strip()
            active = detail == "active"
            if not active and svc == "redis-server":
                r2 = subprocess.run(["systemctl", "is-active", "redis"], capture_output=True, text=True)
                detail = (r2.stdout or r2.stderr or detail).strip()
                active = detail == "active"
            if active:
                break
            # Unit may briefly report "activating" during restart / job churn.
            if detail in {"activating", "reloading"}:
                time.sleep(1.5)
                continue
            break
        record(sec, f"service {svc}", active, detail)

    r = subprocess.run(
        ["bash", "/srv/apps/ifnotus/scripts/repair-tenant-dac.sh", "--prove"],
        capture_output=True,
        text=True,
        timeout=120,
    )
    out = (r.stdout or "") + (r.stderr or "")
    record(sec, "DAC prove", r.returncode == 0 and "DAC_PROVE_PASS" in out, out[-300:])

    code, _ = req("GET", "https://demo30.customers.ifnotus.space/")
    expect_status(sec, "demo30 HTTPS", code, {200, 301, 302})


def write_report(path: str) -> int:
    passed = sum(1 for r in RESULTS if r["ok"])
    failed = sum(1 for r in RESULTS if not r["ok"])
    lines = [
        "IFNOTUS — FULL SYSTEM TEST RESULTS",
        "=" * 60,
        f"Generated (UTC): {datetime.now(UTC).isoformat()}",
        f"Base URL: {BASE}",
        f"Totals: PASS={passed}  FAIL={failed}  TOTAL={len(RESULTS)}",
        "",
    ]
    by_sec: dict[str, list] = {}
    for r in RESULTS:
        by_sec.setdefault(r["section"], []).append(r)
    for sec, items in by_sec.items():
        lines.append(f"## {sec}")
        for r in items:
            mark = "PASS" if r["ok"] else "FAIL"
            lines.append(f"  [{mark}] {r['name']}: {r['detail']}")
            if not r["ok"] and r.get("fix_hint"):
                lines.append(f"         hint: {r['fix_hint']}")
        lines.append("")
    fails = [r for r in RESULTS if not r["ok"]]
    lines.append("## FAILURES TO FIX")
    if not fails:
        lines.append("  (none)")
    else:
        for r in fails:
            lines.append(f"  - [{r['section']}] {r['name']}: {r['detail']}")
    text = "\n".join(lines) + "\n"
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    print("\n" + text)
    return failed


def main() -> int:
    print(f"=== IFNOTUS full system test @ {BASE} ===\n")
    try:
        tokens = mint_tokens()
        record("bootstrap", "mint tokens", True, ",".join(tokens.keys()))
    except Exception as exc:  # noqa: BLE001
        record("bootstrap", "mint tokens", False, f"{exc}\n{traceback.format_exc()}")
        write_report("/tmp/IFNOTUS_FULL_SYSTEM_TEST.txt")
        return 1

    test_public()
    test_infra()
    test_customer(tokens)
    test_signup_flow()
    test_staff_privileges(tokens)
    test_ai(tokens)
    test_platform_ops(tokens)

    failed = write_report("/tmp/IFNOTUS_FULL_SYSTEM_TEST.txt")
    # also copy into docs on app tree if writable
    try:
        with open("/srv/apps/ifnotus/docs/IFNOTUS_FULL_SYSTEM_TEST.txt", "w", encoding="utf-8") as f:
            f.write(open("/tmp/IFNOTUS_FULL_SYSTEM_TEST.txt", encoding="utf-8").read())
    except OSError:
        pass
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
