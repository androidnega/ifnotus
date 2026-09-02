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
        CORE_SLICE,
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
    print(f"  core={CORE_SLICE}")
    print(f"  products={PRODUCTS_SLICE}")
    print(f"  tenants={TENANTS_SLICE}")

    reconciler = WorkloadSliceReconciler()
    actions = []
    actions.extend(reconciler.plan_hierarchy())
    actions.extend(reconciler.plan_service_dropins())
    actions.extend(reconciler.plan_quizsnap_schedule_units())

    async def _load_envs():
        container = create_container()
        session_factory = container.db_session_factory()
        from app.models.platform import CustomerEnvironment

        async with session_factory() as session:
            rows = (await session.execute(select(CustomerEnvironment))).scalars().all()
            return list(rows)

    envs = asyncio.run(_load_envs())
    for env in envs:
        cpu = float(env.cpu_limit or 0) or 0.25
        ram_gb = float(env.ram_limit_gb or 0) or 0.25
        mem_bytes = max(64 * 1024 * 1024, int(ram_gb * 1024 * 1024 * 1024))
        cpu_pct = max(5, min(400, int(round(cpu * 100))))
        # Only used as fallback when neither legacy nor new slice unit exists.
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
                CORE_SLICE,
                PRODUCTS_SLICE,
                TENANTS_SLICE,
            ]
        )
        print(f"systemd-analyze verify: {'OK' if ok else 'WARN/FAIL'}")
        if msg.strip():
            print(msg.strip()[:2000])
        from app.services.platform.workload_slices import WorkloadSliceReconciler as _W

        _W._systemctl("daemon-reload")
        for name in (WORKLOADS_ROOT, CORE_SLICE, PRODUCTS_SLICE, TENANTS_SLICE):
            _W._systemctl("start", name)
        for act in actions:
            if act.action == "write_slice" and "tenants-env-" in act.path:
                _W._systemctl("start", Path(act.path).name)
        # Restart only slice-assigned app services (not nginx/postgres/redis/php-fpm)
        restart_units = [
            "ifnotus-api.service",
            "ifnotus-worker.service",
            "votebridge.service",
            "votebridge-celery.service",
            "votebridge-daphne.service",
            "quizsnap.service",
            "quizsnap-reverb.service",
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
                restart_units.append("examflow-ifnotus.service")
            else:
                print("ExamFlow restart skipped (isolation drop-in not applied)")
        for unit in restart_units:
            print(f"Restarting {unit} …")
            proc = _W._systemctl("restart", unit)
            if proc.returncode != 0:
                print(f"  FAIL {unit}: {(proc.stderr or proc.stdout or '')[:300]}")
            else:
                print(f"  OK {unit}")
        _W._systemctl("enable", "--now", "quizsnap-schedule.timer")
        # Remove quizsnap from root crontab if timer enabled
        try:
            import subprocess

            cur = subprocess.run(["crontab", "-l"], capture_output=True, text=True, check=False)
            if cur.returncode == 0 and cur.stdout:
                lines = [
                    ln
                    for ln in cur.stdout.splitlines()
                    if "/srv/apps/quizsnap" not in ln and "quizsnap" not in ln.lower()
                ]
                # keep /srv/apps/quiz line unless it's clearly quizsnap
                new = "\n".join(lines) + ("\n" if lines else "")
                subprocess.run(["crontab", "-"], input=new, text=True, check=False)
                print("Updated root crontab (removed quizsnap schedule lines)")
        except Exception as exc:  # noqa: BLE001
            print(f"crontab update skipped: {exc}")
        print(f"Env slices reparented (writes): {report.env_reparented}")
    else:
        print("Dry-run complete. Re-run with --apply to write units and restart affected services.")


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


def run_php_fpm_environment_migrate(*, environment_id: str, apply: bool = False, allow_vps: bool = False) -> None:
    import json

    from app.services.platform.php_fpm_environment import PhpFpmEnvironmentService

    settings = get_settings()
    setup_logging(settings)
    env, extra = _load_environment(environment_id)
    if env is None:
        print(f"Environment not found: {environment_id}")
        sys.exit(1)
    svc = PhpFpmEnvironmentService()
    plan = svc.plan_migrate(env, extra_hostnames=extra, allow_vps=allow_vps)
    mode = "APPLY" if apply else "DRY-RUN"
    print(f"IFNOTUS php-fpm environment migrate [{mode}] env={plan.short_id} pools={len(plan.pools)}")
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

    p_php_st = subparsers.add_parser(
        "php-fpm-environment-status",
        help="Phase 2B: show per-environment PHP-FPM migration status",
    )
    p_php_st.add_argument("--environment", required=True, help="CustomerEnvironment UUID")

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
        )
    elif args.command == "php-fpm-environment-status":
        run_php_fpm_environment_status(environment_id=str(args.environment))
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
