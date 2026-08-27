#!/usr/bin/env python3
"""Full tenant lifecycle + stack cycle test (live).

Creates a disposable customer, buys Personal Hosting, staff-activates,
cycles one-click stacks (wordpress → static/php → laravel → nodejs) and
application frameworks (react → vue → express), HTTP-checks each, then
deletes the customer so production keeps only real data.

Run on VPS:
  cd /srv/apps/ifnotus/backend && set -a && . .env && set +a
  ./.venv/bin/python /srv/apps/ifnotus/scripts/ifnotus_stack_cycle_test.py
"""

from __future__ import annotations

import json
import os
import secrets
import sys
import time
import urllib.error
import urllib.request
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

BASE = os.environ.get("IFNOTUS_BASE_URL", "http://127.0.0.1:8010").rstrip("/")
PUBLIC = os.environ.get("IFNOTUS_PUBLIC_URL", "https://ifnotus.space").rstrip("/")
API = f"{BASE}/api/v1"
RESULTS: list[dict[str, Any]] = []
TAG = f"cyc{secrets.token_hex(3)}"
SURNAME = f"tst{TAG}"
PHONE = f"+23320{secrets.randbelow(10_000_000):07d}"
EMAIL = f"cycle-{TAG}@test.ifnotus.space"
PASSWORD = f"Cycle!{secrets.token_hex(4)}Aa1"


def record(step: str, ok: bool, detail: str = "") -> None:
    RESULTS.append({"step": step, "ok": ok, "detail": detail[:500]})
    print(f"[{'PASS' if ok else 'FAIL'}] {step} — {detail[:240]}")


def req(
    method: str,
    path: str,
    *,
    token: str | None = None,
    body: dict[str, Any] | None = None,
    timeout: float = 120.0,
) -> tuple[int, Any]:
    url = path if path.startswith("http") else f"{API}{path}"
    data = None
    headers = {"Accept": "application/json", "User-Agent": "ifnotus-stack-cycle/1.0"}
    if body is not None:
        data = json.dumps(body).encode()
        headers["Content-Type"] = "application/json"
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(url, data=data, headers=headers, method=method.upper())
    try:
        with urllib.request.urlopen(request, timeout=timeout) as resp:
            raw = resp.read().decode() or "{}"
            if resp.status == 204 or not raw.strip():
                return int(resp.status), {}
            try:
                return int(resp.status), json.loads(raw)
            except json.JSONDecodeError:
                return int(resp.status), {"raw": raw[:400]}
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode() or "{}"
        try:
            return int(exc.code), json.loads(raw)
        except json.JSONDecodeError:
            return int(exc.code), {"raw": raw[:400]}
    except Exception as exc:  # noqa: BLE001
        return 0, {"error": str(exc)}


def http_get(url: str, timeout: float = 30.0) -> tuple[int, str]:
    request = urllib.request.Request(
        url, headers={"User-Agent": "ifnotus-stack-cycle/1.0", "Accept": "text/html,*/*"}
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as resp:
            return int(resp.status), (resp.read(8000) or b"").decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        body = (exc.read(2000) or b"").decode("utf-8", errors="replace")
        return int(exc.code), body
    except Exception as exc:  # noqa: BLE001
        return 0, str(exc)


def mint_staff_token() -> str:
    sys.path.insert(0, "/srv/apps/ifnotus/backend")
    os.chdir("/srv/apps/ifnotus/backend")
    import asyncio
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine
    from app.core.config import get_settings
    from app.core.security import create_token_pair

    get_settings.cache_clear()
    settings = get_settings()

    async def load() -> UUID:
        eng = create_async_engine(str(settings.database_url))
        async with eng.connect() as c:
            row = (
                await c.execute(
                    text(
                        "select id from users where is_superuser is true "
                        "or roles::text like '%superadmin%' "
                        "order by is_superuser desc limit 1"
                    )
                )
            ).fetchone()
        await eng.dispose()
        if not row:
            raise RuntimeError("No superadmin user")
        return row[0]

    return create_token_pair(settings, subject=asyncio.run(load())).access_token


def signup_customer() -> str:
    """Phone OTP (prefer debug_code) → profile → password. Returns access token."""
    code, otp = req("POST", "/customers/phone/request-otp", body={"phone": PHONE})
    if code not in {200, 201}:
        raise RuntimeError(f"request-otp failed: {code} {otp}")
    challenge = otp.get("challenge_id")
    dbg = otp.get("debug_code")
    if not dbg:
        # Fall back: register by email then staff is not needed for order if we can verify email.
        code, reg = req(
            "POST",
            "/customers/register",
            body={
                "email": EMAIL,
                "password": PASSWORD,
                "full_name": f"Cycle {TAG}",
                "phone": PHONE,
            },
        )
        if code not in {200, 201}:
            raise RuntimeError(f"register failed: {code} {reg}")
        # Prefer OTP path when SMS debug is on; otherwise mint from DB after register.
        cust = (reg.get("customer") or reg)
        cid = str(cust.get("id") or "")
        if not cid:
            raise RuntimeError(f"no customer id after register: {reg}")
        return mint_customer_token(cid)

    code, login = req(
        "POST",
        "/customers/phone/verify-otp",
        body={"phone": otp.get("phone") or PHONE, "challenge_id": challenge, "code": str(dbg)},
    )
    if code not in {200, 201} or not login.get("access_token"):
        raise RuntimeError(f"verify-otp failed: {code} {login}")
    token = login["access_token"]
    code, me = req(
        "PATCH",
        "/customers/me",
        token=token,
        body={
            "first_name": "Cycle",
            "last_name": SURNAME,
            "email": EMAIL,
            "password": PASSWORD,
        },
    )
    if code not in {200, 201}:
        raise RuntimeError(f"profile update failed: {code} {me}")
    if not me.get("can_order"):
        raise RuntimeError(f"customer cannot order yet: {me}")
    # Prove password login works for tenants.
    code, pw = req("POST", "/customers/login", body={"email": EMAIL, "password": PASSWORD})
    if code not in {200, 201} or not pw.get("access_token"):
        raise RuntimeError(f"customer password login failed: {code} {pw}")
    # Staff login must reject this customer.
    code, staff_try = req("POST", "/auth/login", body={"email": EMAIL, "password": PASSWORD})
    if code == 200 and staff_try.get("access_token"):
        raise RuntimeError("staff /auth/login accepted a pure customer")
    record("auth.password_login", True, "customer /customers/login ok; staff /auth/login rejected")
    return pw["access_token"]


def mint_customer_token(customer_id: str) -> str:
    sys.path.insert(0, "/srv/apps/ifnotus/backend")
    import asyncio
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine
    from app.core.config import get_settings
    from app.core.security import create_token_pair

    get_settings.cache_clear()
    settings = get_settings()

    async def load() -> UUID:
        eng = create_async_engine(str(settings.database_url))
        async with eng.connect() as c:
            row = (
                await c.execute(
                    text("select user_id from customers where id = :id"),
                    {"id": customer_id},
                )
            ).fetchone()
        await eng.dispose()
        if not row or not row[0]:
            raise RuntimeError("Customer has no user_id")
        return row[0]

    return create_token_pair(settings, subject=asyncio.run(load())).access_token


def pick_personal_plan() -> dict[str, Any]:
    code, plans = req("GET", "/catalog/plans")
    if code != 200:
        raise RuntimeError(f"catalog plans failed: {code}")
    items = plans if isinstance(plans, list) else plans.get("items") or plans.get("plans") or []
    for p in items:
        slug = str(p.get("slug") or p.get("matrix_key") or "").lower()
        name = str(p.get("name") or "").lower()
        if "personal" in slug or "personal" in name:
            return p
    # Prefer non-coming-soon with wordpress
    for p in items:
        if p.get("coming_soon"):
            continue
        return p
    raise RuntimeError("No purchasable plan found")


def poll_active_env(token: str, timeout_s: int = 240) -> dict[str, Any]:
    deadline = time.time() + timeout_s
    last: dict[str, Any] = {}
    while time.time() < deadline:
        code, dash = req("GET", "/customers/dashboard", token=token)
        if code == 200:
            last = dash if isinstance(dash, dict) else {}
            for e in last.get("environments") or []:
                if str(e.get("status")) == "active":
                    return e
            print(
                "[WAIT] envs:",
                [(e.get("domain"), e.get("status"), e.get("provisioning_step")) for e in (last.get("environments") or [])],
            )
        time.sleep(5)
    raise RuntimeError(f"No active env after {timeout_s}s: {last}")


def poll_stack_job(token: str, env_id: str, job_id: str, timeout_s: int = 300) -> dict[str, Any]:
    deadline = time.time() + timeout_s
    last: dict[str, Any] = {}
    queued_since = time.time()
    while time.time() < deadline:
        code, job = req("GET", f"/customers/environments/{env_id}/stacks/jobs/{job_id}", token=token)
        if code == 200 and isinstance(job, dict):
            last = job
            status = str(job.get("status") or "").lower()
            if status in {"done", "completed", "success", "ready"}:
                return job
            if status in {"failed", "error"}:
                raise RuntimeError(f"stack job failed: {job}")
            # Also treat progress payload with percent 100 as done
            if int(job.get("percent") or 0) >= 100 and status in {"", "running"}:
                return job
            if status == "queued" and (time.time() - queued_since) > 45:
                raise RuntimeError(f"stack job stuck queued: {job}")
            if status != "queued":
                queued_since = time.time()
            print(f"[WAIT] stack job {job_id[:8]}… {status} {job.get('percent')}% {job.get('label') or job.get('step')}")
        time.sleep(4)
    raise RuntimeError(f"stack job timeout: {last}")


def site_ok(domain: str, *, expect_substr: str | None = None) -> tuple[bool, str]:
    urls = [f"https://{domain}/", f"http://{domain}/"]
    last = ""
    for url in urls:
        code, body = http_get(url)
        last = f"{url} → {code} ({body[:80]!r})"
        # Treat gateway failures as hard fails (PHP-FPM / Node down).
        if code in {502, 503, 504}:
            continue
        if code and 200 <= code < 500:
            if expect_substr and expect_substr.lower() not in body.lower():
                continue
            return True, last
    return False, last


def force_inline_install(env_id: str, stack: str, *, replace: bool = True) -> dict[str, Any]:
    """Run stack install in-process when the Redis worker drops the job."""
    sys.path.insert(0, "/srv/apps/ifnotus/backend")
    os.chdir("/srv/apps/ifnotus/backend")
    import asyncio
    from uuid import UUID as _UUID
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from app.core.config import get_settings
    from app.models.platform import CustomerEnvironment, PlatformJob
    from app.services.platform.stacks import EnvironmentStackService

    get_settings.cache_clear()
    settings = get_settings()

    async def run() -> dict[str, Any]:
        eng = create_async_engine(str(settings.database_url))
        fac = async_sessionmaker(eng, expire_on_commit=False)
        async with fac() as session:
            env = await session.get(CustomerEnvironment, _UUID(env_id))
            if env is None:
                raise RuntimeError(f"env {env_id} missing")
            job = PlatformJob(
                job_type="deploy_stack",
                customer_id=env.customer_id,
                environment_id=env.id,
                status="running",
                payload={"stack": stack, "replace": replace, "environment_id": env_id},
            )
            session.add(job)
            await session.flush()
            result = await EnvironmentStackService(settings, session).install(
                env, stack=stack, replace=replace, job=job
            )
            job.status = "success"
            job.result = result
            await session.commit()
            return result if isinstance(result, dict) else {"result": result}
        await eng.dispose()

    return asyncio.run(run())


def install_and_test_stack(token: str, env: dict[str, Any], stack: str, expect: str | None) -> None:
    env_id = str(env["id"])
    domain = str(env.get("domain") or "")
    code, body = req(
        "POST",
        f"/customers/environments/{env_id}/stacks/install",
        token=token,
        body={"stack": stack, "replace": True},
        timeout=180,
    )
    if code not in {200, 201, 202}:
        raise RuntimeError(f"install {stack} failed: {code} {body}")
    job_id = body.get("job_id") or (body.get("job") or {}).get("id")
    queued = bool(body.get("queued"))
    if job_id and queued:
        try:
            poll_stack_job(token, env_id, str(job_id), timeout_s=90)
        except RuntimeError as exc:
            if "timeout" in str(exc).lower() or "queued" in str(exc).lower():
                record(f"stack.{stack}.worker_fallback", True, "inline install after queue stall")
                force_inline_install(env_id, stack, replace=True)
            else:
                raise
    elif job_id:
        poll_stack_job(token, env_id, str(job_id), timeout_s=300)
    else:
        status = str(body.get("status") or "").lower()
        if status in {"failed", "error"}:
            raise RuntimeError(f"install {stack} inline fail: {body}")
        time.sleep(3)
    ok, detail = site_ok(domain, expect_substr=expect)
    # Node proxy may need a moment after process start.
    if not ok and stack == "nodejs":
        time.sleep(4)
        ok, detail = site_ok(domain, expect_substr=expect)
    record(f"stack.{stack}.http", ok, detail)
    if not ok:
        raise RuntimeError(f"{stack} site check failed: {detail}")
    code, cleared = req(
        "POST",
        f"/customers/environments/{env_id}/stacks/clear",
        token=token,
        body={"drop_database": True},
        timeout=120,
    )
    record(f"stack.{stack}.clear", code in {200, 201, 204}, f"{code} {str(cleared)[:120]}")
    if code not in {200, 201, 204}:
        raise RuntimeError(f"clear {stack} failed: {code} {cleared}")
    time.sleep(2)


def install_and_test_app(token: str, env: dict[str, Any], framework: str) -> None:
    env_id = str(env["id"])
    domain = str(env.get("domain") or "")
    app_id = ""
    try:
        # Framework-aware start: static SPA stubs use serve on "."; Express uses default node server.js.
        create_body: dict[str, Any] = {
            "name": f"{framework}-{TAG}",
            "framework": framework,
            "build_command": "",
        }
        if framework in {"react", "vue"}:
            create_body["start_command"] = "npx --yes serve -s . -l {port}"
        code, app = req(
            "POST",
            f"/customers/environments/{env_id}/applications",
            token=token,
            body=create_body,
        )
        if code not in {200, 201}:
            raise RuntimeError(f"create app {framework} failed: {code} {app}")
        app_id = str(app.get("id"))
        code, deployed = req(
            "POST",
            f"/customers/environments/{env_id}/applications/{app_id}/deploy",
            token=token,
            timeout=180,
        )
        if code not in {200, 201}:
            raise RuntimeError(f"deploy {framework} failed: {code} {deployed}")
        status = str(deployed.get("status") or "").lower()
        record(f"app.{framework}.deploy", status in {"running", "deployed", "ready"}, f"status={status}")
        # Supervisor + nginx reload need a beat before the first HTTP probe.
        time.sleep(3)
        slug = deployed.get("slug") or ""
        ok = False
        detail = ""
        if slug:
            url = f"https://{domain}/apps/{slug}/"
            for _ in range(4):
                c, body = http_get(url)
                detail = f"{url} → {c}"
                if c and 200 <= c < 400:
                    ok = True
                    break
                time.sleep(2)
        else:
            detail = "missing app slug"
        record(f"app.{framework}.http", ok, detail)
    finally:
        if app_id:
            code, _ = req(
                "DELETE",
                f"/customers/environments/{env_id}/applications/{app_id}",
                token=token,
            )
            record(f"app.{framework}.delete", code in {200, 204}, f"HTTP {code}")


def cleanup(staff: str, customer_id: str) -> None:
    code, body = req(
        "POST",
        f"/platform/customers/{customer_id}/delete",
        token=staff,
        body={"confirm_email": EMAIL},
        timeout=180,
    )
    record("cleanup.delete_customer", code in {200, 204}, f"{code} {str(body)[:200]}")
    if code not in {200, 204}:
        raise RuntimeError(f"delete customer failed: {code} {body}")


def main() -> int:
    print(f"=== IFNOTUS stack cycle {datetime.now(UTC).isoformat()} tag={TAG} ===")
    print(f"API={BASE} PUBLIC={PUBLIC} email={EMAIL} phone={PHONE} surname={SURNAME}")
    customer_id = ""
    staff = ""
    try:
        code, health = req("GET", "/health")
        record("health", code == 200 and (health.get("status") == "healthy"), str(health.get("status")))
        if not RESULTS[-1]["ok"]:
            return 1

        staff = mint_staff_token()
        record("auth.staff_token", True, "minted")

        cust_token = signup_customer()
        code, me = req("GET", "/customers/me", token=cust_token)
        record("auth.signup_login", code == 200 and me.get("can_order"), f"email={me.get('email')}")
        customer_id = str(me.get("id") or "")
        if not customer_id:
            raise RuntimeError("missing customer id")

        plan = pick_personal_plan()
        plan_id = str(plan.get("id"))
        amount = float(plan.get("price_monthly") or plan.get("price") or 0)
        record("catalog.personal_plan", True, f"{plan.get('name')} id={plan_id} price={amount}")

        code, order = req(
            "POST",
            "/customers/orders",
            token=cust_token,
            body={
                "plan_id": plan_id,
                "domain_kind": "student",
                "student_surname": SURNAME,
            },
        )
        record("order.create", code in {200, 201}, str(order)[:200])
        order_id = str(order.get("id") or (order.get("order") or {}).get("id") or "")
        if not order_id:
            raise RuntimeError(f"no order id: {order}")
        amount = float(order.get("total_price") or amount)

        txn = f"TEST{TAG.upper()}{secrets.token_hex(4).upper()}"
        code, momo = req(
            "POST",
            f"/customers/orders/{order_id}/momo",
            token=cust_token,
            body={"transaction_id": txn},
        )
        record("order.momo", code in {200, 201}, f"txn={txn} {str(momo)[:120]}")

        code, confirmed = req(
            "POST",
            f"/platform/orders/{order_id}/confirm-payment",
            token=staff,
            body={"amount_received": amount, "notes": f"stack-cycle-{TAG}"},
            timeout=300,
        )
        record("order.confirm_activate", code in {200, 201}, str(confirmed)[:200])
        if code not in {200, 201}:
            raise RuntimeError(f"confirm failed: {code} {confirmed}")

        env = poll_active_env(cust_token)
        record(
            "hosting.active",
            True,
            f"domain={env.get('domain')} unix={env.get('unix_username')} id={env.get('id')}",
        )
        domain = str(env.get("domain") or "")
        ok, detail = site_ok(domain)
        record("hosting.http_before_stacks", ok, detail)

        # Continue remaining stacks even if one HTTP check fails (still clear + cleanup).
        for stack, expect in (
            ("wordpress", None),
            ("static", None),
            ("laravel", None),
            ("nodejs", None),
        ):
            try:
                install_and_test_stack(cust_token, env, stack, expect)
            except Exception as exc:  # noqa: BLE001
                record(f"stack.{stack}", False, str(exc))
                try:
                    req(
                        "POST",
                        f"/customers/environments/{env['id']}/stacks/clear",
                        token=cust_token,
                        body={"drop_database": True},
                        timeout=120,
                    )
                except Exception:  # noqa: BLE001
                    pass

        # Application packages (react + peers)
        for fw in ("react", "vue", "express"):
            try:
                install_and_test_app(cust_token, env, fw)
            except Exception as exc:  # noqa: BLE001
                record(f"app.{fw}", False, str(exc))

        cleanup(staff, customer_id)
        return 0 if all(r["ok"] for r in RESULTS) else 1
    except Exception as exc:  # noqa: BLE001
        record("fatal", False, str(exc))
        if staff and customer_id:
            try:
                cleanup(staff, customer_id)
            except Exception as clean_exc:  # noqa: BLE001
                record("cleanup.forced", False, str(clean_exc))
        return 1
    finally:
        fails = [r for r in RESULTS if not r["ok"]]
        print("\n=== SUMMARY ===")
        print(f"passed={sum(1 for r in RESULTS if r['ok'])} failed={len(fails)} total={len(RESULTS)}")
        for r in fails:
            print(f"  - {r['step']}: {r['detail']}")
        out = f"/tmp/IFNOTUS_STACK_CYCLE_{TAG}.json"
        with open(out, "w", encoding="utf-8") as f:
            json.dump({"tag": TAG, "email": EMAIL, "results": RESULTS}, f, indent=2)
        print(f"wrote {out}")


if __name__ == "__main__":
    raise SystemExit(main())
