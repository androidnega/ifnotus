"""IFNOTUS Management CLI — CLI commands for operations and infrastructure reconciliation."""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

from app.core.config import get_settings
from app.core.container import create_container
from app.core.logging import get_logger, setup_logging
from app.services.platform.reconciliation import EnvironmentReconciliationService
from sqlalchemy import select

logger = get_logger(__name__)


async def run_reconciliation(target_domain: str | None = None) -> None:
    settings = get_settings()
    setup_logging(settings)
    container = create_container()
    session_factory = container.db_session_factory()

    async with session_factory() as session:
        service = EnvironmentReconciliationService(settings, session)
        print("Starting IFNOTUS Hosting Environment Reconciliation...")
        if target_domain:
            from app.models.platform import CustomerEnvironment
            stmt = select(CustomerEnvironment).where(CustomerEnvironment.domain == target_domain)
            res = await session.execute(stmt)
            env = res.scalar_one_or_none()
            if env:
                results = [await service.reconcile_environment(env)]
            else:
                # Direct domain provision
                from app.services.platform.panel_access import find_letsencrypt_cert, is_platform_hostname
                dns_updated = False
                dns_err = None
                try:
                    if not is_platform_hostname(target_domain, settings=settings) and not target_domain.endswith(".customers.ifnotus.space"):
                        service._auth_dns.ensure_zone(target_domain)
                        dns_updated = True
                except Exception as exc:
                    dns_err = str(exc)

                cert_path, _ = find_letsencrypt_cert(target_domain)
                has_ssl = bool(cert_path)
                nginx_res = await service._nginx.provision(
                    hostname=target_domain,
                    document_root=f"/var/www/{target_domain}",
                    proxy_port=None,
                    force_https=has_ssl,
                    enabled=True,
                    create_docroot=True,
                    force_takeover=True,
                    ssl_certificate=cert_path if has_ssl else None,
                )
                results = [{
                    "domain": target_domain,
                    "fpanel_host": f"fpanel.{target_domain}",
                    "nginx_vhost_rendered": nginx_res.success,
                    "dns_updated": dns_updated,
                    "dns_error": dns_err,
                    "ssl_active": has_ssl,
                }]
        else:
            results = await service.reconcile_all_active_environments()
        print(f"Reconciled {len(results)} active hosting environments:")
        for res in results:
            domain = res.get("domain")
            fpanel = res.get("fpanel_host")
            nginx_ok = res.get("nginx_vhost_rendered")
            dns_ok = res.get("dns_updated")
            ssl_active = res.get("ssl_active")
            print(f" - [{domain}] fPanel: {fpanel} | Nginx Vhost: {'OK' if nginx_ok else 'FAILED'} | DNS: {'OK' if dns_ok else 'UNCHANGED'} | SSL: {'ACTIVE' if ssl_active else 'PENDING'}")
            if res.get("nginx_error"):
                print(f"   * Nginx Error: {res['nginx_error']}")
            if res.get("dns_error"):
                print(f"   * DNS Error: {res['dns_error']}")
        print("Reconciliation complete.")


def run_resource_policy_status(*, with_plans: bool = False) -> None:
    """Read-only resource governance policy dump (Phase 1). No system changes."""
    from app.services.platform.resource_policy import (
        PlanView,
        format_resource_policy_status,
        host_resource_policy_from_settings,
        resource_policy_status_report,
        validate_resource_policy,
    )

    settings = get_settings()
    setup_logging(settings)
    policy = host_resource_policy_from_settings(settings)
    plans: list[PlanView] = []

    if with_plans:
        async def _load_plans() -> list[PlanView]:
            container = create_container()
            session_factory = container.db_session_factory()
            from app.models.platform import HostingPlan

            async with session_factory() as session:
                result = await session.execute(select(HostingPlan).order_by(HostingPlan.price_monthly))
                rows = result.scalars().all()
                out: list[PlanView] = []
                for p in rows:
                    out.append(
                        PlanView(
                            slug=p.slug,
                            name=p.name,
                            price_monthly=float(p.price_monthly or 0),
                            ram_gb=float(p.ram_gb or 0),
                            storage_gb=float(p.storage_gb or 0),
                            features=dict(p.features or {}),
                        )
                    )
                return out

        plans = asyncio.run(_load_plans())

    report = resource_policy_status_report(policy=policy, plans=plans or None)
    print(format_resource_policy_status(report))
    validation = validate_resource_policy(policy)
    if not validation.ok:
        sys.exit(2)


def run_reconcile_resource_slices(*, apply: bool = False, fix_examflow: bool = False) -> None:
    """Phase 2A: hierarchy drop-ins + env slice re-parent (preserve legacy limits)."""
    from app.services.platform.unix_identity import UnixIdentityService
    from app.services.platform.workload_slices import (
        ADDITIONAL_FIRST_PARTY_UNITS,
        CORE_SLICE,
        FIRST_PARTY_UNITS,
        PLATFORM_CORE_UNITS,
        PRIORITY_CORE_SLICE,
        PRIORITY_PRODUCTS_SLICE,
        PRIORITY_MEMORY_HIGH,
        PRIORITY_SLICE,
        PRODUCTS_SLICE,
        TENANTS_SLICE,
        WORKLOADS_ROOT,
        ReconcileAction,
        WorkloadSliceReconciler,
        slice_name_for,
        systemd_analyze_verify,
    )

    settings = get_settings()
    setup_logging(settings)
    dry_run = not apply
    mode = "APPLY" if apply else "DRY-RUN"
    print(f"IFNOTUS resource slice reconciliation [{mode}]")
    print(f"  root={WORKLOADS_ROOT}")
    print(f"  priority={PRIORITY_SLICE} (MemoryHigh={PRIORITY_MEMORY_HIGH})")
    print(f"  core={PRIORITY_CORE_SLICE}")
    print(f"  products={PRIORITY_PRODUCTS_SLICE}")
    print(f"  tenants={TENANTS_SLICE}")

    reconciler = WorkloadSliceReconciler()
    actions = []
    actions.extend(reconciler.plan_hierarchy())
    actions.extend(reconciler.plan_service_dropins())
    actions.extend(reconciler.plan_quizsnap_schedule_units())
    actions.extend(reconciler.plan_quiz_legacy_schedule_units())
    actions.extend(reconciler.plan_retire_legacy_core_product_slices())

    async def _load_envs():
        container = create_container()
        session_factory = container.db_session_factory()
        from app.models.platform import CustomerEnvironment

        async with session_factory() as session:
            rows = (await session.execute(select(CustomerEnvironment))).scalars().all()
            return list(rows)

    envs = asyncio.run(_load_envs())
    # Phase 3B-1: do NOT rewrite env MemoryHigh/Max via reparent fallbacks — that would
    # regress Phase 2C 2/6/12 policy. Env reparent only when explicitly requested later.
    skip_env_reparent = True
    if not skip_env_reparent:
        for env in envs:
            cpu = float(env.cpu_limit or 0) or 0.25
            ram_gb = float(env.ram_limit_gb or 0) or 0.25
            mem_bytes = max(64 * 1024 * 1024, int(ram_gb * 1024 * 1024 * 1024))
            cpu_pct = max(5, min(400, int(round(cpu * 100))))
            actions.extend(
                reconciler.plan_env_reparent(
                    environment_id=env.id,
                    fallback_cpu_quota=f"{cpu_pct}%",
                    fallback_memory_max=str(mem_bytes),
                    fallback_tasks_max="40",
                )
            )

    examflow_note = None
    if fix_examflow:
        # Env id from Phase 0/2A audit — examflow.ifnotus.space
        examflow_id = None
        for env in envs:
            if (env.domain or "").lower() == "examflow.ifnotus.space":
                examflow_id = env.id
                break
        if examflow_id is None:
            examflow_note = "examflow.ifnotus.space environment not found"
        else:
            slice_name = slice_name_for(examflow_id)
            drop = reconciler.slice_dir / "examflow-ifnotus.service.d" / "10-ifnotus-isolation.conf"
            app_root = (
                "/srv/apps/ifnotus-customers/augustinedanqua/student-dev/"
                "public_html/ExamFlowPro"
            )

            async def _ensure_unix():
                container = create_container()
                session_factory = container.db_session_factory()
                from app.models.platform import CustomerEnvironment

                async with session_factory() as session:
                    env = await session.get(CustomerEnvironment, examflow_id)
                    if env is None:
                        return None
                    UnixIdentityService(settings, session).ensure_unix_account_exists(
                        env,
                        actor="phase2a-examflow",
                    )
                    await session.commit()
                    await session.refresh(env)
                    return {
                        "unix_username": env.unix_username,
                        "unix_uid": env.unix_uid,
                        "domain": env.domain,
                    }

            def _probe_writable(user: str, path: str) -> bool:
                import subprocess

                proc = subprocess.run(
                    ["sudo", "-u", user, "test", "-w", path],
                    capture_output=True,
                    check=False,
                )
                return proc.returncode == 0

            if dry_run:
                examflow_note = (
                    f"would ensure unix identity + probe logs/tmp writability; "
                    f"drop-in User=!root Slice={slice_name} only if probe passes "
                    f"(no recursive chown). Required if blocked: "
                    f"chown <ifn_*>:<ifn_*> {app_root}/logs {app_root}/tmp && "
                    f"chmod u+rwx {app_root}/logs {app_root}/tmp"
                )
                actions.append(
                    ReconcileAction(
                        action="write_dropin",
                        path=str(drop),
                        detail="ExamFlow isolation drop-in (preview; gated on permission probe)",
                        content=(
                            "[Service]\n"
                            f"# preview Slice={slice_name}\n"
                            "User=<ifn_*>\n"
                            f"Slice={slice_name}\n"
                        ),
                    )
                )
            else:
                info = asyncio.run(_ensure_unix())
                if not info or not info.get("unix_username"):
                    examflow_note = "FAILED to ensure unix identity for examflow"
                else:
                    user = info["unix_username"]
                    logs_ok = _probe_writable(user, f"{app_root}/logs")
                    tmp_ok = _probe_writable(user, f"{app_root}/tmp")
                    if not logs_ok or not tmp_ok:
                        # Phase 2A safety: do not chown/chmod tenant tree; stop subsection.
                        examflow_note = (
                            "BLOCKED RESOURCE_ISOLATION_VIOLATION dependency: "
                            f"Django handler errors_file needs write on {app_root}/logs "
                            f"(currently root-only 0700) and possibly {app_root}/tmp. "
                            f"Exact minimum (not applied): "
                            f"chown {user}:{user} {app_root}/logs {app_root}/tmp && "
                            f"chmod u+rwx {app_root}/logs {app_root}/tmp. "
                            "Then re-run with --fix-examflow. Root execution left unchanged."
                        )
                    else:
                        content = "\n".join(
                            [
                                "[Service]",
                                "# Phase 2A: remove root execution; place in tenant env slice",
                                f"User={user}",
                                f"Group={user}",
                                f"Slice={slice_name}",
                                "MemoryAccounting=yes",
                                "CPUAccounting=yes",
                                "TasksAccounting=yes",
                                "",
                            ]
                        )
                        actions.append(
                            ReconcileAction(
                                action="write_dropin",
                                path=str(drop),
                                detail=f"ExamFlow User={user} Slice={slice_name}",
                                content=content,
                            )
                        )
                        examflow_note = f"ExamFlow drop-in User={user} Slice={slice_name}"

    report = reconciler.apply_actions(actions, dry_run=dry_run)
    print(f"Planned actions: {len(actions)}")
    for act in actions[:12]:
        print(f"  - {act.action}: {act.path}")
    if len(actions) > 12:
        print(f"  … {len(actions) - 12} more")
    if examflow_note:
        print(f"ExamFlow: {examflow_note}")
    if report.errors:
        print("Errors:")
        for err in report.errors:
            print(f"  ! {err}")
        sys.exit(1)

    if apply:
        unit_paths = [a.path for a in actions if a.path.endswith((".slice", ".service", ".timer", ".conf"))]
        # systemd-analyze verify works best on unit names; verify key slices
        ok, msg = systemd_analyze_verify(
            [
                WORKLOADS_ROOT,
                PRIORITY_SLICE,
                PRIORITY_CORE_SLICE,
                PRIORITY_PRODUCTS_SLICE,
                TENANTS_SLICE,
            ]
        )
        print(f"systemd-analyze verify: {'OK' if ok else 'WARN/FAIL'}")
        if msg.strip():
            print(msg.strip()[:2000])
        from app.services.platform.workload_slices import WorkloadSliceReconciler as _W

        _W._systemctl("daemon-reload")
        for name in (WORKLOADS_ROOT, PRIORITY_SLICE, PRIORITY_CORE_SLICE, PRIORITY_PRODUCTS_SLICE, TENANTS_SLICE):
            _W._systemctl("start", name)
        for act in actions:
            if act.action == "write_slice" and "tenants-env-" in act.path:
                _W._systemctl("start", Path(act.path).name)
        # Restart only slice-assigned app services (not nginx/postgres/redis/php-fpm/mysql)
        # Phase 3B-1 migration order: core → VoteBridge → QuizSnap → additional first-party
        restart_batches = [
            list(PLATFORM_CORE_UNITS),
            [u for u in FIRST_PARTY_UNITS if u.startswith("votebridge")],
            [u for u in FIRST_PARTY_UNITS if u.startswith("quizsnap")],
            list(ADDITIONAL_FIRST_PARTY_UNITS),
        ]
        if fix_examflow:
            # Only restart ExamFlow when isolation drop-in was written this run.
            if any(
                a.path.endswith("examflow-ifnotus.service.d/10-ifnotus-isolation.conf")
                and a.action == "write_dropin"
                and a.content
                and "User=<ifn" not in (a.content or "")
                for a in actions
            ):
                restart_batches.append(["examflow-ifnotus.service"])
            else:
                print("ExamFlow restart skipped (isolation drop-in not applied)")
        for batch in restart_batches:
            for unit in batch:
                print(f"Restarting {unit} …")
                proc = _W._systemctl("restart", unit)
                if proc.returncode != 0:
                    print(f"  FAIL {unit}: {(proc.stderr or proc.stdout or '')[:300]}")
                else:
                    print(f"  OK {unit}")
                # Verify slice placement after each unit
                show = _W._systemctl("show", unit, "-p", "Slice", "-p", "ActiveState", "--value")
                print(f"  state/slice: {(show.stdout or '').strip()!r}")
        _W._systemctl("enable", "--now", "quizsnap-schedule.timer")
        _W._systemctl("enable", "--now", "quiz-schedule.timer")
        # Apply priority MemoryHigh=8G after migrations (Phase 3B-1: no MemoryMax/MemoryMin)
        _W._systemctl("set-property", PRIORITY_SLICE, f"MemoryHigh={PRIORITY_MEMORY_HIGH}", "MemoryMin=")
        print(f"Applied MemoryHigh={PRIORITY_MEMORY_HIGH} on {PRIORITY_SLICE}")
        # Remove quizsnap + legacy quiz schedule lines from root crontab (now timers)
        try:
            import subprocess

            cur = subprocess.run(["crontab", "-l"], capture_output=True, text=True, check=False)
            if cur.returncode == 0 and cur.stdout:
                lines = []
                for ln in cur.stdout.splitlines():
                    low = ln.lower()
                    if "/srv/apps/quizsnap" in ln or "quizsnap" in low:
                        continue
                    if "/srv/apps/quiz" in ln and "artisan schedule:run" in ln:
                        continue
                    lines.append(ln)
                new = "\n".join(lines) + ("\n" if lines else "")
                subprocess.run(["crontab", "-"], input=new, text=True, check=False)
                print("Updated root crontab (removed quiz/quizsnap schedule lines → systemd timers)")
        except Exception as exc:  # noqa: BLE001
            print(f"crontab update skipped: {exc}")
        print(f"Env slices reparented (writes): {report.env_reparented}")
    else:
        print("Dry-run complete. Re-run with --apply to write units and restart affected services.")


def run_host_safety_status() -> None:
    """Phase 3B-1: read-only host MemAvailable safety floor + emergency capacity."""
    import json

    from app.services.platform.host_safety import build_host_safety_snapshot
    from app.services.platform.workload_slices import (
        PRIORITY_SLICE,
        TENANTS_SLICE,
        read_cgroup_memory_current,
        resolve_slice_cgroup_path,
    )

    settings = get_settings()
    setup_logging(settings)
    tenant_cg = resolve_slice_cgroup_path(TENANTS_SLICE)
    priority_cg = resolve_slice_cgroup_path(PRIORITY_SLICE)
    snap = build_host_safety_snapshot(
        tenant_memory_current_bytes=read_cgroup_memory_current(tenant_cg) if tenant_cg else None,
        priority_memory_current_bytes=read_cgroup_memory_current(priority_cg) if priority_cg else None,
    )
    print(json.dumps(snap.to_dict(), indent=2))


def run_resource_governor_status(*, as_json: bool = False) -> None:
    """Phase 3B-2: print emergency governor status (read-only)."""
    import json

    from app.services.platform.resource_governor import ResourceEmergencyGovernor

    settings = get_settings()
    setup_logging(settings)
    gov = ResourceEmergencyGovernor(dry_run=True)
    gov.reconcile_from_kernel()
    snap = gov.snapshot()
    if as_json:
        print(json.dumps(snap.to_dict(), indent=2))
    else:
        print(gov.format_status(snap))


def run_resource_governor(
    *,
    dry_run: bool = True,
    run_loop: bool = False,
    apply_baseline: bool = False,
    grant: str | None = None,
    release: str | None = None,
    apply: bool = False,
) -> None:
    """Phase 3B-2 emergency governor: dry-run tick, controlled grant/release, or service loop."""
    from app.services.platform.resource_governor import (
        SAMPLE_INTERVAL_SEC,
        ResourceEmergencyGovernor,
    )

    settings = get_settings()
    setup_logging(settings)
    mutate = bool(apply) and not dry_run
    gov = ResourceEmergencyGovernor(dry_run=not mutate)

    if run_loop:
        # Service mode — always mutate unless --dry-run without --apply
        gov.dry_run = dry_run and not apply
        gov.run_loop(interval_sec=SAMPLE_INTERVAL_SEC, apply=not gov.dry_run)
        return

    gov.reconcile_from_kernel()
    if apply_baseline:
        planned = gov.ensure_priority_baseline(apply=mutate)
        print(f"baseline: {planned.action} reason={planned.reason} mutate={mutate}")
    if grant:
        snap = gov.force_grant(grant, apply=mutate)
        print(gov.format_status(snap))
        return
    if release:
        snap = gov.force_release(release, apply=mutate)
        print(gov.format_status(snap))
        return

    snap = gov.tick(apply=mutate)
    print(gov.format_status(snap))


def _load_environment(environment_id: str):
    from uuid import UUID

    from app.models.platform import CustomerEnvironment

    eid = UUID(environment_id)

    async def _load():
        container = create_container()
        session_factory = container.db_session_factory()
        async with session_factory() as session:
            from sqlalchemy import text

            env = await session.get(CustomerEnvironment, eid)
            if env is None:
                return None, []
            extra = []
            try:
                rows = await session.execute(
                    text("SELECT domain_name FROM customer_domains WHERE environment_id = :eid"),
                    {"eid": str(eid)},
                )
                extra = [r[0] for r in rows if r[0]]
            except Exception:  # noqa: BLE001
                extra = []
            return env, extra

    return asyncio.run(_load())


def run_php_fpm_environment_migrate(
    *,
    environment_id: str,
    apply: bool = False,
    allow_vps: bool = False,
    allow_legacy_www_data: bool = False,
    allow_excluded_domain: bool = False,
    require_tenant_unix_user: bool = False,
) -> None:
    import json

    from app.services.platform.php_fpm_environment import PhpFpmEnvironmentService

    settings = get_settings()
    setup_logging(settings)
    env, extra = _load_environment(environment_id)
    if env is None:
        print(f"Environment not found: {environment_id}")
        sys.exit(1)
    svc = PhpFpmEnvironmentService()
    plan = svc.plan_migrate(
        env,
        extra_hostnames=extra,
        allow_vps=allow_vps,
        require_tenant_unix_user=require_tenant_unix_user,
        allow_legacy_www_data=allow_legacy_www_data,
        allow_excluded_domain=allow_excluded_domain,
    )
    mode = "APPLY" if apply else "DRY-RUN"
    print(f"IFNOTUS php-fpm environment migrate [{mode}] env={plan.short_id} pools={len(plan.pools)}")
    if plan.warnings:
        print("Warnings:")
        for w in plan.warnings:
            print(f"  ~ {w}")
    if plan.errors:
        print("Errors:")
        for e in plan.errors:
            print(f"  ! {e}")
        sys.exit(2)
    print(json.dumps(plan.to_dict(), indent=2)[:4000])
    report = svc.apply_migrate(plan, dry_run=not apply)
    print(json.dumps(report, indent=2)[:4000])
    if not report.get("ok"):
        sys.exit(1)


def run_php_fpm_environment_status(*, environment_id: str) -> None:
    import json

    from app.services.platform.php_fpm_environment import PhpFpmEnvironmentService

    settings = get_settings()
    setup_logging(settings)
    env, extra = _load_environment(environment_id)
    if env is None:
        print(f"Environment not found: {environment_id}")
        sys.exit(1)
    status = PhpFpmEnvironmentService().status(env, extra_hostnames=extra)
    print(json.dumps(status, indent=2))


def run_php_fpm_environment_rollback(*, environment_id: str, apply: bool = False) -> None:
    """Restore global php8.3-fpm pools for one environment (Phase 2B-2 rollback test)."""
    import json

    from app.services.platform.php_fpm_environment import PhpFpmEnvironmentService

    settings = get_settings()
    setup_logging(settings)
    env, extra = _load_environment(environment_id)
    if env is None:
        print(f"Environment not found: {environment_id}")
        sys.exit(1)
    svc = PhpFpmEnvironmentService()
    plan = svc.plan_migrate(env, extra_hostnames=extra)
    mode = "APPLY" if apply else "DRY-RUN"
    print(f"IFNOTUS php-fpm environment rollback [{mode}] env={plan.short_id}")
    print(json.dumps({"rollback_steps": plan.rollback_steps, "pools": [p.pool_name for p in plan.pools]}, indent=2))
    if not apply:
        print("dry-run — no system changes")
        return
    report = svc.rollback(plan)
    print(json.dumps(report, indent=2)[:4000])
    if not report.get("ok"):
        sys.exit(1)


def _load_all_environments_with_plans():
    from sqlalchemy import text
    from app.models.platform import CustomerEnvironment

    async def _load():
        container = create_container()
        session_factory = container.db_session_factory()
        async with session_factory() as session:
            rows = await session.execute(
                text(
                    """
                    SELECT ce.id,
                           hp.slug, hp.name, hp.price_monthly, hp.features, hp.ram_gb
                    FROM customer_environments ce
                    JOIN subscriptions sub ON sub.id = ce.subscription_id
                    JOIN hosting_plans hp ON hp.id = sub.plan_id
                    ORDER BY ce.created_at
                    """
                )
            )
            plan_meta = {
                str(r[0]): {
                    "slug": r[1],
                    "name": r[2],
                    "price_monthly": float(r[3] or 0),
                    "features": r[4] or {},
                    "ram_gb": float(r[5] or 0),
                }
                for r in rows
            }
            envs = []
            for eid in plan_meta:
                env = await session.get(CustomerEnvironment, __import__("uuid").UUID(eid))
                if env is None:
                    continue
                erows = await session.execute(
                    text("SELECT domain_name FROM customer_domains WHERE environment_id = :eid"),
                    {"eid": eid},
                )
                extras = [r[0] for r in erows if r[0]]
                meta = plan_meta[eid]
                plan = type(
                    "PlanView",
                    (),
                    {
                        "name": meta["name"],
                        "slug": meta["slug"],
                        "price_monthly": meta["price_monthly"],
                        "ram_gb": meta["ram_gb"],
                        "features": meta["features"] or {},
                    },
                )()
                envs.append((env, extras, plan, meta))
            return envs

    return asyncio.run(_load())


def run_php_fpm_rollout(
    *,
    batch_size: int = 5,
    apply: bool = False,
    environment: str | None = None,
    exclude: list[str] | None = None,
    resume: bool = False,
    inventory_only: bool = False,
    batch_number: int | None = None,
) -> None:
    """Phase 2B-3 controlled shared PHP-FPM mass rollout (default: dry-run)."""
    import json
    from collections import Counter

    from app.services.platform.php_fpm_rollout import (
        CLASS_ALREADY_MIGRATED,
        CLASS_ELIGIBLE,
        CLASS_MANUAL,
        CLASS_NO_PHP,
        CLASS_POOL_MISMATCH,
        PhpFpmRolloutService,
        idle_fpm_stats,
        recommended_tasksmax,
    )
    from app.services.platform.workload_slices import (
        read_cgroup_memory_current,
        resolve_slice_cgroup_path,
        slice_name_for,
    )

    settings = get_settings()
    setup_logging(settings)
    svc = PhpFpmRolloutService()
    state = svc.checkpoint.load()
    if not resume and apply and state.get("stopped") and not environment:
        print(f"Checkpoint stopped: {state.get('stop_reason')}. Use --resume after review.")
        sys.exit(3)

    # Verify already-migrated first
    print("=== VERIFY EXISTING MIGRATED ===")
    rows_all = _load_all_environments_with_plans()
    inventory_rows = []
    migrated_ok = True
    for env, extra, plan, meta in rows_all:
        row = svc.classify_environment(
            env,
            extra_hostnames=extra,
            plan=plan,
            plan_slug=meta.get("slug"),
            plan_name=meta.get("name"),
            price_monthly=meta.get("price_monthly"),
            check_http=False,
        )
        inventory_rows.append(row)
        if row.classification == CLASS_ALREADY_MIGRATED:
            ver = svc.verify_migrated(env, extra_hostnames=extra)
            print(f"  {row.short_id} drift={ver.get('drift_state')} ok={ver.get('ok')}")
            if not ver.get("ok"):
                migrated_ok = False
    if not migrated_ok:
        print("STOP: existing migrated environment unhealthy")
        sys.exit(4)

    counts = Counter(r.classification for r in inventory_rows)
    print("=== INVENTORY ===")
    print(json.dumps(dict(counts), indent=2))
    print(
        json.dumps(
            {
                "total": len(inventory_rows),
                "eligible": counts.get(CLASS_ELIGIBLE, 0),
                "already_migrated": counts.get(CLASS_ALREADY_MIGRATED, 0),
                "no_php": counts.get(CLASS_NO_PHP, 0),
                "manual_or_mismatch": counts.get(CLASS_MANUAL, 0) + counts.get(CLASS_POOL_MISMATCH, 0),
            },
            indent=2,
        )
    )
    if inventory_only:
        print(json.dumps([r.to_dict() for r in inventory_rows], indent=2)[:8000])
        return

    eligible = [r for r in inventory_rows if r.classification == CLASS_ELIGIBLE]
    exclude_set = set(exclude or [])
    only = {environment} if environment else None

    # Batch plan: 1→5, 2→8, 3→rest unless batch_number/batch_size override
    batch_sizes = [5, 8, 10_000]
    if batch_number is not None:
        idx = max(1, batch_number) - 1
        batch_sizes = batch_sizes[idx : idx + 1] if idx < len(batch_sizes) else [batch_size]
    elif batch_size and batch_number is None and environment:
        batch_sizes = [1]
    elif batch_size != 5 and batch_number is None:
        # single custom batch size for one batch invocation
        batch_sizes = [batch_size]

    mode = "APPLY" if apply else "DRY-RUN"
    print(f"IFNOTUS php-fpm rollout [{mode}] batch_sizes={batch_sizes}")
    host_before = svc.host_memory_snapshot()
    print("host_before", json.dumps(host_before))

    batch_reports = []
    env_by_id = {str(env.id): (env, extra, plan, meta) for env, extra, plan, meta in rows_all}

    for bi, size in enumerate(batch_sizes, start=1):
        if state.get("stopped") and apply and resume:
            # clear stop only when resuming intentionally after operator review
            state["stopped"] = False
            state["stop_reason"] = None
            svc.checkpoint.save(state)
        if state.get("stopped") and apply:
            print(f"Stopped before batch {bi}: {state.get('stop_reason')}")
            break

        targets = svc.select_batch(
            eligible,
            batch_size=size,
            exclude=exclude_set,
            only=only,
            state=state,
        )
        if not targets:
            print(f"Batch {bi}: nothing to migrate")
            batch_reports.append({"batch": bi, "attempted": 0, "migrated": 0, "rolled_back": 0, "failed": 0, "status": "EMPTY"})
            continue

        print(f"=== BATCH {bi} targets={len(targets)} ===")
        for t in targets:
            print(f"  - {t.short_id} pools={t.pool_count} hosts={t.hostname_count}")

        attempted = migrated = rolled = failed = 0
        batch_status = "OK"
        for t in targets:
            attempted += 1
            env, extra, plan, meta = env_by_id[t.environment_id]
            print(f"--- migrate {t.short_id} ---")
            result = svc.migrate_one(
                env,
                extra_hostnames=extra,
                plan_class=None,
                dry_run=not apply,
                state=state,
            )
            state = result.get("state") or state
            if result.get("ok"):
                migrated += 1
                print(f"  OK phase={result.get('phase')}")
            elif result.get("phase") == "preflight":
                # Preflight rejects are explicit manual-review — continue batch.
                failed += 1
                svc.checkpoint.set_env(
                    state,
                    t.environment_id,
                    status="MANUAL_REVIEW",
                    short_id=t.short_id,
                    reject_codes=(result.get("preflight") or {}).get("reject_codes"),
                )
                svc.checkpoint.save(state)
                print(f"  SKIP preflight codes={(result.get('preflight') or {}).get('reject_codes')}")
            else:
                failed += 1
                if "roll" in str(result.get("phase")):
                    rolled += 1
                batch_status = "STOPPED"
                print(f"  FAIL phase={result.get('phase')} codes={result.get('preflight', {}).get('reject_codes')}")
                if apply:
                    break
            # global FPM quick check
            if apply and (svc._systemctl("is-active", "php8.3-fpm.service").stdout or "").strip() != "active":
                state["stopped"] = True
                state["stop_reason"] = "global_fpm_inactive"
                svc.checkpoint.save(state)
                batch_status = "STOPPED"
                print("STOP: global php8.3-fpm inactive")
                break

        # If preflight skips reduced successes, pull more eligible targets to fill batch.
        if apply and batch_status == "OK" and migrated < size and not environment:
            refill = svc.select_batch(
                eligible,
                batch_size=size - migrated,
                exclude=exclude_set,
                only=only,
                state=state,
            )
            for t in refill:
                if migrated >= size:
                    break
                attempted += 1
                env, extra, plan, meta = env_by_id[t.environment_id]
                print(f"--- refill migrate {t.short_id} ---")
                result = svc.migrate_one(
                    env,
                    extra_hostnames=extra,
                    plan_class=None,
                    dry_run=False,
                    state=state,
                )
                state = result.get("state") or state
                if result.get("ok"):
                    migrated += 1
                    print(f"  OK phase={result.get('phase')}")
                elif result.get("phase") == "preflight":
                    failed += 1
                    svc.checkpoint.set_env(
                        state,
                        t.environment_id,
                        status="MANUAL_REVIEW",
                        short_id=t.short_id,
                        reject_codes=(result.get("preflight") or {}).get("reject_codes"),
                    )
                    svc.checkpoint.save(state)
                    print(f"  SKIP preflight")
                else:
                    failed += 1
                    if "roll" in str(result.get("phase")):
                        rolled += 1
                    batch_status = "STOPPED"
                    print(f"  FAIL phase={result.get('phase')}")
                    break

        # Batch considered OK if no post-cutover failures (preflight skips allowed).
        if batch_status == "OK" and rolled == 0 and not state.get("stopped"):
            batch_status = "OK"
        elif rolled or state.get("stopped"):
            batch_status = "STOPPED"
        else:
            batch_status = "OK"

        # Batch validation
        services = svc.service_health()
        host_after = svc.host_memory_snapshot()
        print("services", json.dumps(services))
        print("host_after", json.dumps(host_after))
        if apply and host_before.get("mem_available_gb") and host_after.get("mem_available_gb") is not None:
            # stop if available memory collapses below 1.5 GiB absolute OS headroom
            if float(host_after["mem_available_gb"]) < 1.5:
                state["stopped"] = True
                state["stop_reason"] = "host_mem_available_low"
                svc.checkpoint.save(state)
                batch_status = "STOPPED"
                print("STOP: host MemAvailable < 1.5 GiB")

        batch_reports.append(
            {
                "batch": bi,
                "attempted": attempted,
                "migrated": migrated,
                "rolled_back": rolled,
                "failed": failed,
                "status": batch_status,
                "services": services,
            }
        )
        state.setdefault("batches", []).append(batch_reports[-1])
        svc.checkpoint.save(state)

        # Between batches require no hard stop
        if apply and state.get("stopped"):
            break
        if apply and rolled:
            break

    print("=== ROLLOUT SUMMARY ===")
    print(json.dumps({"batches": batch_reports, "checkpoint": str(svc.checkpoint.path)}, indent=2))


def run_tenant_containment_status(*, environment_id: str | None = None, as_json: bool = False) -> None:
    import json
    from collections import Counter

    from app.services.platform.tenant_containment import TenantContainmentService
    from app.services.platform.workload_slices import env_short_id

    settings = get_settings()
    setup_logging(settings)
    svc = TenantContainmentService()
    if environment_id:
        env, extra = _load_environment(environment_id)
        if env is None:
            print(f"Environment not found: {environment_id}")
            sys.exit(1)
        rep = svc.report_environment(env, extra_hostnames=extra)
        print(json.dumps(rep.to_dict(), indent=2))
        return

    rows = _load_all_environments_with_plans()
    reports = []
    for env, extra, _plan, _meta in rows:
        reports.append(svc.report_environment(env, extra_hostnames=extra).to_dict())
    counts = Counter(r["aggregate"] for r in reports)
    global_pools = svc.classify_global_pools()
    node_escapes = svc.detect_node_escapes()
    summary = {
        "total": len(reports),
        "aggregates": dict(counts),
        "global_fpm_tenant_legacy": global_pools.get("tenant_global_legacy_pools"),
        "node_cgroup_escapes": len(node_escapes),
        "sum_ok": len(reports) == 32 or len(reports) == sum(counts.values()),
    }
    print(json.dumps(summary, indent=2))
    if as_json:
        print(json.dumps({"environments": reports, "global_pools": global_pools}, indent=2)[:12000])


def run_reconcile_memory_policy(
    *,
    apply: bool = False,
    apply_parent: bool = False,
    environment: str | None = None,
    batch_size: int | None = None,
    json_out: bool = False,
) -> None:
    """Phase 2C: reconcile shared MemoryHigh/MemoryMax (default dry-run)."""
    from app.models.platform import CustomerEnvironment, HostingPlan, Order, Subscription
    from app.services.platform.memory_policy import (
        MemoryPolicyService,
        format_reconcile_report,
        plan_view_from_orm,
        read_live_slice_limits,
        tasksmax_warning,
    )
    from app.services.platform.resource_policy import gib_to_bytes, host_resource_policy_from_settings
    from app.services.platform.workload_slices import TENANTS_SLICE, slice_name_for
    import json

    settings = get_settings()
    setup_logging(settings)
    policy = host_resource_policy_from_settings(settings)
    svc = MemoryPolicyService(policy=policy)
    dry_run = not apply
    mode = "APPLY" if apply else "DRY-RUN"
    if not json_out:
        print(f"IFNOTUS memory policy reconciliation [{mode}]")

    async def _load() -> list[tuple[CustomerEnvironment, object | None, str, int]]:
        container = create_container()
        async with container.db_session_factory()() as session:
            envs = list((await session.execute(select(CustomerEnvironment))).scalars().all())
            out: list[tuple[CustomerEnvironment, object | None, str, int]] = []
            for env in envs:
                if environment:
                    eid = str(env.id)
                    short = eid.split("-")[0]
                    needle = environment.strip().lower()
                    if needle not in {eid.lower(), short.lower(), (env.domain or "").lower()}:
                        continue
                plan = None
                source = "subscription_plan"
                sub = await session.get(Subscription, env.subscription_id) if env.subscription_id else None
                if sub and sub.plan_id:
                    plan = await session.get(HostingPlan, sub.plan_id)
                if plan is None:
                    from sqlalchemy import desc

                    ord_row = (
                        await session.execute(
                            select(Order)
                            .where(Order.customer_id == env.customer_id)
                            .order_by(desc(Order.created_at))
                            .limit(1)
                        )
                    ).scalar_one_or_none()
                    if ord_row is not None and getattr(ord_row, "plan_id", None):
                        plan = await session.get(HostingPlan, ord_row.plan_id)
                        source = "order_plan"
                from sqlalchemy import func
                from app.models.platform import CustomerDomain

                dcount = (
                    await session.execute(
                        select(func.count()).select_from(CustomerDomain).where(CustomerDomain.environment_id == env.id)
                    )
                ).scalar() or 0
                out.append((env, plan, source, int(dcount)))
            return out

    rows_src = asyncio.run(_load())
    rows = []
    for env, plan, source, dcount in rows_src:
        row = svc.build_row(
            env_id=env.id,
            domain=env.domain,
            status=str(env.status or "active"),
            plan=plan_view_from_orm(plan),
            source=source,
            domain_count=dcount,
        )
        # TasksMax warning
        live = read_live_slice_limits(slice_name_for(env.id))
        tw = tasksmax_warning(
            tasks_current=None,
            tasks_max=int(live.get("TasksMax") or 0) or None,
        )
        if tw:
            row.warnings.append(tw)
        rows.append(row)

    # Optional batch limit (for controlled apply) — skip already-compliant rows.
    apply_rows = [r for r in rows if not r.skipped and r.drift != "POLICY_OK"]
    if batch_size is not None and apply:
        apply_rows = apply_rows[: max(0, int(batch_size))]

    applied = []
    if apply:
        for row in apply_rows:
            applied.append(svc.apply_row(row, dry_run=False))
    else:
        applied = rows

    parent = svc.read_parent_tenants()
    parent_report = None
    if apply_parent:
        parent_report = svc.apply_parent_tenants_memory_max(dry_run=dry_run)
        parent = parent_report.get("after") or svc.read_parent_tenants()

    payload = {
        "mode": mode,
        "rows": [r.to_dict() for r in (applied if apply else rows)],
        "parent": parent,
        "parent_apply": parent_report,
        "policy": {
            "tenant_parent_memory_max_gib": policy.tenant_normal_pool_gb,
            "shared_low_memory_high_gib": policy.tenant_low_plan_normal_gb,
            "shared_standard_memory_high_gib": policy.tenant_standard_plan_normal_gb,
            "shared_memory_max_gib": policy.tenant_individual_burst_max_gb,
            "parent_slice": TENANTS_SLICE,
            "parent_target_bytes": gib_to_bytes(policy.tenant_normal_pool_gb),
        },
    }
    if json_out:
        print(json.dumps(payload, indent=2, default=str))
    else:
        print(format_reconcile_report(applied if apply else rows, parent=parent))
        if parent_report:
            print(json.dumps({"parent_apply": parent_report}, indent=2, default=str))


def run_sftp_cgroup_attach_install(*, apply: bool = False, refresh_map: bool = False) -> None:
    import json

    from app.services.platform.tenant_containment import TenantContainmentService, ensure_pam_sshd_attach
    from app.services.platform.workload_slices import env_short_id, slice_name_for

    settings = get_settings()
    setup_logging(settings)
    svc = TenantContainmentService()
    if refresh_map or apply:
        rows = []
        for env, _extra, _plan, _meta in _load_all_environments_with_plans():
            unix = getattr(env, "unix_username", None)
            if not unix:
                continue
            rows.append(
                {
                    "unix_username": unix,
                    "environment_id": str(env.id),
                    "short_id": env_short_id(env.id),
                    "slice": slice_name_for(env.id),
                }
            )
        path = svc.write_unix_slice_map(rows)
        print(f"Wrote map entries={len(rows)} path={path}")
    report = ensure_pam_sshd_attach(dry_run=not apply)
    print(json.dumps(report, indent=2))
    if apply and not report.get("ok"):
        sys.exit(1)


def main() -> None:
    parser = argparse.ArgumentParser(description="IFNOTUS Infrastructure Management CLI")
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    p_recon = subparsers.add_parser("reconcile-hosting", help="Reconcile DNS zones, Nginx fPanel vhosts, and document roots")
    p_recon.add_argument("--domain", help="Optional specific domain to reconcile", default=None)
    subparsers.add_parser("reconcile-zones", help="Alias for reconcile-hosting")

    p_policy = subparsers.add_parser(
        "resource-policy-status",
        help="Print centralized resource policy snapshot (read-only; Phase 1)",
    )
    p_policy.add_argument(
        "--with-plans",
        action="store_true",
        help="Include live HostingPlan compatibility rows (DB read-only)",
    )

    p_slices = subparsers.add_parser(
        "reconcile-resource-slices",
        help="Phase 2A: create workload cgroup hierarchy and reparent env slices (default: dry-run)",
    )
    p_slices.add_argument("--dry-run", action="store_true", default=True, help="Plan only (default)")
    p_slices.add_argument("--apply", action="store_true", help="Write units, daemon-reload, restart affected services")
    p_slices.add_argument(
        "--fix-examflow",
        action="store_true",
        help="Also remove ExamFlow root execution and place in tenant slice",
    )

    p_php = subparsers.add_parser(
        "php-fpm-environment-migrate",
        help="Phase 2B: migrate one environment's PHP pools to ifnotus-php-fpm@ (default: dry-run)",
    )
    p_php.add_argument("--environment", required=True, help="CustomerEnvironment UUID")
    p_php.add_argument("--dry-run", action="store_true", default=True, help="Plan only (default)")
    p_php.add_argument("--apply", action="store_true", help="Perform cutover for this environment only")
    p_php.add_argument("--allow-vps", action="store_true", help="Allow VPS/VDS-style environments")
    p_php.add_argument(
        "--allow-legacy-www-data",
        action="store_true",
        help="Phase 2B-4: allow www-data pools without converting Unix identity",
    )
    p_php.add_argument(
        "--allow-excluded-domain",
        action="store_true",
        help="Phase 2B-4: allow domains on the special exclude list when PHP containment is intentional",
    )
    p_php.add_argument(
        "--require-tenant-unix-user",
        action="store_true",
        help="Require env unix_username ifn_* (legacy www-data still needs --allow-legacy-www-data)",
    )

    p_php_st = subparsers.add_parser(
        "php-fpm-environment-status",
        help="Phase 2B: show per-environment PHP-FPM migration status",
    )
    p_php_st.add_argument("--environment", required=True, help="CustomerEnvironment UUID")

    p_php_rb = subparsers.add_parser(
        "php-fpm-environment-rollback",
        help="Phase 2B: restore global php8.3-fpm pools for one environment (default: dry-run)",
    )
    p_php_rb.add_argument("--environment", required=True, help="CustomerEnvironment UUID")
    p_php_rb.add_argument("--dry-run", action="store_true", default=True, help="Plan only (default)")
    p_php_rb.add_argument("--apply", action="store_true", help="Perform rollback for this environment only")

    p_roll = subparsers.add_parser(
        "php-fpm-rollout",
        help="Phase 2B-3: controlled shared PHP-FPM mass rollout (default: dry-run)",
    )
    p_roll.add_argument("--batch-size", type=int, default=5, help="Max environments in this invocation batch")
    p_roll.add_argument("--batch", type=int, default=None, help="Run only batch N of the 1/2/3 strategy")
    p_roll.add_argument("--dry-run", action="store_true", default=True, help="Plan only (default)")
    p_roll.add_argument("--apply", action="store_true", help="Apply migrations sequentially")
    p_roll.add_argument("--environment", default=None, help="Limit to one environment UUID/short-id")
    p_roll.add_argument("--exclude", action="append", default=[], help="Exclude environment id/short-id (repeatable)")
    p_roll.add_argument("--resume", action="store_true", help="Resume after a previous stop")
    p_roll.add_argument("--inventory-only", action="store_true", help="Classify only; no migrate planning")

    p_tc = subparsers.add_parser(
        "tenant-containment-status",
        help="Phase 2B-4: read-only tenant containment status (PHP/Node/cron/SFTP)",
    )
    p_tc.add_argument("--environment", default=None, help="Optional single environment UUID")
    p_tc.add_argument("--json", action="store_true", help="Print full JSON")

    p_sftp = subparsers.add_parser(
        "sftp-cgroup-attach-install",
        help="Phase 2B-4: install pam_exec SFTP/SSH session cgroup attach helper (default: dry-run)",
    )
    p_sftp.add_argument("--dry-run", action="store_true", default=True)
    p_sftp.add_argument("--apply", action="store_true")
    p_sftp.add_argument("--refresh-map", action="store_true", help="Rewrite unix→slice map from DB")

    p_mem = subparsers.add_parser(
        "reconcile-memory-policy",
        help="Phase 2C: apply shared MemoryHigh/MemoryMax + optional parent 30GiB (default: dry-run)",
    )
    p_mem.add_argument("--dry-run", action="store_true", default=True)
    p_mem.add_argument("--apply", action="store_true", help="Apply child MemoryHigh/MemoryMax")
    p_mem.add_argument(
        "--apply-parent",
        action="store_true",
        help="Also set ifnotus-workloads-tenants.slice MemoryMax=30G",
    )
    p_mem.add_argument("--environment", default=None, help="Limit to one environment UUID/short-id/domain")
    p_mem.add_argument("--batch-size", type=int, default=None, help="Max environments to apply in this run")
    p_mem.add_argument("--json", action="store_true", help="Emit JSON report")

    subparsers.add_parser(
        "host-safety-status",
        help="Phase 3B-1: print host MemAvailable safety floor + safe emergency capacity (read-only)",
    )

    p_gov_status = subparsers.add_parser(
        "resource-governor-status",
        help="Phase 3B-2: print emergency governor host/tenant/priority/ledger status",
    )
    p_gov_status.add_argument("--json", action="store_true")

    p_gov = subparsers.add_parser(
        "resource-governor",
        help="Phase 3B-2: dry-run tick, controlled grant/release, baseline, or --run service loop",
    )
    p_gov.add_argument("--dry-run", action="store_true", default=True)
    p_gov.add_argument("--apply", action="store_true", help="Allow mutating MemoryMax")
    p_gov.add_argument("--run", action="store_true", help="Run continuous 10s polling loop (service)")
    p_gov.add_argument(
        "--apply-priority-baseline",
        action="store_true",
        help="Set priority MemoryMax=8GiB when usage is safely below 8GiB",
    )
    p_gov.add_argument("--grant", choices=["tenants", "priority"], default=None)
    p_gov.add_argument("--release", choices=["tenants", "priority"], default=None)

    args = parser.parse_args()

    if args.command in {"reconcile-hosting", "reconcile-zones"}:
        domain = getattr(args, "domain", None)
        asyncio.run(run_reconciliation(target_domain=domain))
    elif args.command == "resource-policy-status":
        run_resource_policy_status(with_plans=bool(getattr(args, "with_plans", False)))
    elif args.command == "reconcile-resource-slices":
        run_reconcile_resource_slices(
            apply=bool(getattr(args, "apply", False)),
            fix_examflow=bool(getattr(args, "fix_examflow", False)),
        )
    elif args.command == "php-fpm-environment-migrate":
        run_php_fpm_environment_migrate(
            environment_id=str(args.environment),
            apply=bool(getattr(args, "apply", False)),
            allow_vps=bool(getattr(args, "allow_vps", False)),
            allow_legacy_www_data=bool(getattr(args, "allow_legacy_www_data", False)),
            allow_excluded_domain=bool(getattr(args, "allow_excluded_domain", False)),
            require_tenant_unix_user=bool(getattr(args, "require_tenant_unix_user", False)),
        )
    elif args.command == "php-fpm-environment-status":
        run_php_fpm_environment_status(environment_id=str(args.environment))
    elif args.command == "php-fpm-environment-rollback":
        run_php_fpm_environment_rollback(
            environment_id=str(args.environment),
            apply=bool(getattr(args, "apply", False)),
        )
    elif args.command == "php-fpm-rollout":
        run_php_fpm_rollout(
            batch_size=int(getattr(args, "batch_size", 5) or 5),
            apply=bool(getattr(args, "apply", False)),
            environment=getattr(args, "environment", None),
            exclude=list(getattr(args, "exclude", []) or []),
            resume=bool(getattr(args, "resume", False)),
            inventory_only=bool(getattr(args, "inventory_only", False)),
            batch_number=getattr(args, "batch", None),
        )
    elif args.command == "tenant-containment-status":
        run_tenant_containment_status(
            environment_id=getattr(args, "environment", None),
            as_json=bool(getattr(args, "json", False)),
        )
    elif args.command == "sftp-cgroup-attach-install":
        run_sftp_cgroup_attach_install(
            apply=bool(getattr(args, "apply", False)),
            refresh_map=bool(getattr(args, "refresh_map", False)),
        )
    elif args.command == "reconcile-memory-policy":
        run_reconcile_memory_policy(
            apply=bool(getattr(args, "apply", False)),
            apply_parent=bool(getattr(args, "apply_parent", False)),
            environment=getattr(args, "environment", None),
            batch_size=getattr(args, "batch_size", None),
            json_out=bool(getattr(args, "json", False)),
        )
    elif args.command == "host-safety-status":
        run_host_safety_status()
    elif args.command == "resource-governor-status":
        run_resource_governor_status(as_json=bool(getattr(args, "json", False)))
    elif args.command == "resource-governor":
        run_resource_governor(
            dry_run=not bool(getattr(args, "apply", False)),
            run_loop=bool(getattr(args, "run", False)),
            apply_baseline=bool(getattr(args, "apply_priority_baseline", False)),
            grant=getattr(args, "grant", None),
            release=getattr(args, "release", None),
            apply=bool(getattr(args, "apply", False)),
        )
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
