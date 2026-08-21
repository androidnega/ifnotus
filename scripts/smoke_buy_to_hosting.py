#!/usr/bin/env python3
"""PHASE 21 — Buy-to-hosting smoke helper.

Safe by default (--dry-run): checks public catalog/health and prints the
manual steps. Write modes require --live-write plus tokens.

Usage:
  python scripts/smoke_buy_to_hosting.py --base-url https://ifnotus.space --dry-run
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from typing import Any


def _req(
    base: str,
    method: str,
    path: str,
    *,
    token: str | None = None,
    body: dict[str, Any] | None = None,
    timeout: float = 30.0,
) -> tuple[int, Any]:
    url = base.rstrip("/") + path
    data = None
    headers = {"Accept": "application/json"}
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
                payload = {"raw": raw[:500]}
            return int(resp.status), payload
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8") or "{}"
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            payload = {"raw": raw[:500]}
        return int(exc.code), payload


def _ok(label: str, cond: bool, detail: str = "") -> None:
    mark = "PASS" if cond else "FAIL"
    extra = f" — {detail}" if detail else ""
    print(f"[{mark}] {label}{extra}")
    if not cond:
        raise SystemExit(1)


def preflight(base: str) -> dict[str, Any]:
    code, health = _req(base, "GET", "/api/v1/health")
    _ok("health", code == 200 and (health.get("status") == "healthy"), str(health.get("status")))

    code, meta = _req(base, "GET", "/api/v1/catalog/meta")
    _ok("catalog meta", code == 200, f"student_zone={meta.get('student_zone')}")
    _ok(
        "student zone",
        meta.get("student_zone") == "serverlabsttu.space",
        str(meta.get("student_zone")),
    )

    code, plans = _req(base, "GET", "/api/v1/catalog/plans")
    _ok("catalog plans", code == 200)
    items = plans if isinstance(plans, list) else plans.get("plans") or plans.get("items") or []
    student = None
    for p in items:
        slug = str(p.get("slug") or "").lower()
        name = str(p.get("name") or "").lower()
        if "student" in slug or "student" in name:
            student = p
            break
    _ok("student plan present", student is not None, str((student or {}).get("slug") or (student or {}).get("name")))
    return {"meta": meta, "student_plan": student, "plans": items}


def print_manual_steps(plan: dict[str, Any] | None) -> None:
    plan_id = (plan or {}).get("id") or "<plan_id>"
    print(
        """
=== Manual / authenticated steps (see docs/phase21-buy-to-hosting-smoke.md) ===
1) Customer: phone OTP signup + progressive profile until can_order
2) POST /api/v1/customers/orders
   {"plan_id": "%s", "domain_kind": "student", "student_surname": "<surname>"}
3) POST /api/v1/customers/orders/{id}/momo  {"transaction_id": "<txn>"}
4) Staff: POST /api/v1/platform/orders/{id}/confirm-payment
5) Poll GET /api/v1/customers/dashboard until env.status=active
6) Assert unix_username, entitlements, SSL, https site, /hosting/{id}
"""
        % (plan_id,)
    )


def poll_dashboard(base: str, token: str, *, timeout_s: int = 180) -> dict[str, Any]:
    deadline = time.time() + timeout_s
    last: dict[str, Any] = {}
    while time.time() < deadline:
        code, dash = _req(base, "GET", "/api/v1/customers/dashboard", token=token)
        if code != 200:
            print(f"[WAIT] dashboard HTTP {code}")
            time.sleep(5)
            continue
        last = dash if isinstance(dash, dict) else {}
        envs = last.get("environments") or []
        if any(str(e.get("status")) == "active" for e in envs):
            return last
        print(
            "[WAIT] environments:",
            [(e.get("domain"), e.get("status"), e.get("provisioning_step"), e.get("unix_username")) for e in envs],
        )
        time.sleep(5)
    return last


def assert_active_env(dash: dict[str, Any]) -> None:
    envs = dash.get("environments") or []
    active = [e for e in envs if str(e.get("status")) == "active"]
    _ok("active environment exists", bool(active))
    env = active[0]
    print(
        json.dumps(
            {
                "domain": env.get("domain"),
                "status": env.get("status"),
                "provisioning_step": env.get("provisioning_step"),
                "unix_username": env.get("unix_username"),
                "unix_uid": env.get("unix_uid"),
                "storage_limit_gb": env.get("storage_limit_gb"),
            },
            indent=2,
        )
    )
    _ok("unix_username set", bool(env.get("unix_username")), str(env.get("unix_username")))
    domain = env.get("domain") or ""
    if domain.endswith("serverlabsttu.space"):
        print("[PASS] student zone hostname")
    elif domain:
        print(f"[INFO] domain={domain} (custom or legacy zone)")


def main() -> None:
    parser = argparse.ArgumentParser(description="IFNOTUS Phase 21 buy-to-hosting smoke")
    parser.add_argument("--base-url", default="https://ifnotus.space")
    parser.add_argument("--dry-run", action="store_true", default=False)
    parser.add_argument("--customer-token", default="")
    parser.add_argument("--staff-token", default="")
    parser.add_argument("--surname", default="smoke21")
    parser.add_argument("--plan-id", default="")
    parser.add_argument(
        "--through",
        choices=("preflight", "order", "momo", "confirm", "poll"),
        default="preflight",
    )
    parser.add_argument(
        "--live-write",
        action="store_true",
        help="Allow POST order/momo/confirm (dangerous on production).",
    )
    parser.add_argument("--momo-txn", default="")
    parser.add_argument("--amount", type=float, default=0.0)
    args = parser.parse_args()

    base = args.base_url.rstrip("/")
    print(f"Base URL: {base}")
    info = preflight(base)
    plan = info["student_plan"]
    if args.plan_id:
        plan = next((p for p in info["plans"] if str(p.get("id")) == args.plan_id), plan)

    if args.dry_run or args.through == "preflight":
        print_manual_steps(plan)
        if args.dry_run or not args.customer_token:
            print("[DONE] preflight/dry-run complete")
            return

    if not args.customer_token:
        raise SystemExit("--customer-token required beyond preflight")

    if args.through == "poll" and not args.live_write:
        dash = poll_dashboard(base, args.customer_token)
        assert_active_env(dash)
        print("[DONE] poll complete")
        return

    if not args.live_write:
        raise SystemExit("Refusing writes without --live-write")

    plan_id = args.plan_id or (plan or {}).get("id")
    if not plan_id:
        raise SystemExit("No student plan_id")

    if args.through in {"order", "momo", "confirm"}:
        code, order = _req(
            base,
            "POST",
            "/api/v1/customers/orders",
            token=args.customer_token,
            body={
                "plan_id": plan_id,
                "domain_kind": "student",
                "student_surname": args.surname,
            },
        )
        _ok("create order", code in {200, 201}, json.dumps(order)[:400])
        order_id = order.get("id") or (order.get("order") or {}).get("id")
        print("order_id=", order_id)

        if args.through == "order":
            return

        txn = args.momo_txn or f"SMOKE{int(time.time())}"
        code, momo = _req(
            base,
            "POST",
            f"/api/v1/customers/orders/{order_id}/momo",
            token=args.customer_token,
            body={"transaction_id": txn},
        )
        _ok("submit momo", code in {200, 201}, json.dumps(momo)[:400])
        if args.through == "momo":
            return

        if not args.staff_token:
            raise SystemExit("--staff-token required for confirm")
        amount = args.amount or float((plan or {}).get("price_monthly") or 0)
        code, conf = _req(
            base,
            "POST",
            f"/api/v1/platform/orders/{order_id}/confirm-payment",
            token=args.staff_token,
            body={"amount_received": amount, "notes": "phase21 smoke"},
        )
        _ok("staff confirm", code in {200, 201}, json.dumps(conf)[:400])

    dash = poll_dashboard(base, args.customer_token)
    assert_active_env(dash)
    print("[DONE] smoke through", args.through)


if __name__ == "__main__":
    main()
