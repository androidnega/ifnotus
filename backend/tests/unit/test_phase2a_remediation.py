"""Phase 2A-R: ownership mutation guards + PHP 2B design tests."""

from __future__ import annotations

import ast
from pathlib import Path
from uuid import UUID, uuid4
from unittest.mock import MagicMock

from app.services.platform.php_fpm_env_design import (
    HostnamePool,
    PHASE_2B_PHP_ENV_MASTER_DESIGN,
    assert_environments_never_share_instance,
    estimate_master_overhead,
    group_pools_by_environment,
    planned_fpm_service_name,
)
from app.services.platform.structural_ownership import (
    EXAMFLOW_OWNERSHIP_INCIDENT,
    ExplicitPathRepair,
    PathClass,
    classify_site_relative,
    repair_explicit_structural_paths,
)
from app.services.platform.workload_slices import (
    examflow_health_classification,
)


def _cli_source() -> str:
    return Path("app/cli/__main__.py").read_text(encoding="utf-8")


def test_resource_cli_uses_ensure_unix_account_not_apply_ownership() -> None:
    src = _cli_source()
    assert "reconcile-resource-slices" in src
    assert "ensure_unix_account_exists" in src
    # Must not call apply_ownership from CLI resource path
    tree = ast.parse(src)
    calls: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Attribute):
                calls.append(func.attr)
            elif isinstance(func, ast.Name):
                calls.append(func.id)
    assert "apply_ownership" not in calls
    assert "_chown_tree" not in calls
    assert "ensure_unix_account_exists" in calls


def test_ensure_unix_account_sets_apply_home_ownership_false(monkeypatch) -> None:
    from app.services.platform.unix_identity import UnixIdentityService

    captured: dict[str, object] = {}

    def fake_ensure(self, env, *, shell=None, actor="system", apply_home_ownership=True):
        captured["apply_home_ownership"] = apply_home_ownership
        captured["actor"] = actor
        return {"username": "ifn_test"}

    monkeypatch.setattr(UnixIdentityService, "ensure_identity", fake_ensure)
    svc = UnixIdentityService(MagicMock(), MagicMock())
    svc.ensure_unix_account_exists(MagicMock(), actor="phase2a-examflow")
    assert captured["apply_home_ownership"] is False


def test_examflow_non_root_and_tenant_slice() -> None:
    bad = examflow_health_classification(user="root", slice_path="/system.slice/x")
    assert bad["healthy"] is False
    good = examflow_health_classification(
        user="ifn_34a9a20e",
        slice_path="…/ifnotus-workloads-tenants-env-34a9a20e.slice/examflow",
    )
    assert good["healthy"] is True
    assert EXAMFLOW_OWNERSHIP_INCIDENT["files_content_changed"] is False
    assert EXAMFLOW_OWNERSHIP_INCIDENT["metadata_changed"] is True


def test_structural_repair_only_explicit_paths(tmp_path: Path) -> None:
    site = tmp_path / "site"
    site.mkdir()
    structural = site / "logs"
    structural.mkdir()
    # Pretend incorrect ownership; repair only this path in dry-run then apply
    plan = repair_explicit_structural_paths(
        [ExplicitPathRepair(path=str(structural), owner="root", group="root", mode=0o700)],
        dry_run=True,
        allowed_roots=[str(site)],
    )
    assert plan[0]["dry_run"] is True
    assert plan[0]["changed"] is False
    assert classify_site_relative("logs") == PathClass.SYSTEM_STRUCTURAL
    assert classify_site_relative("www", is_symlink=True) == PathClass.SYMLINK
    assert classify_site_relative("public_html") == PathClass.CUSTOMER_CONTENT_ROOT


def test_dry_run_resource_actions_are_systemd_only() -> None:
    from app.services.platform.workload_slices import WorkloadSliceReconciler

    rec = WorkloadSliceReconciler(slice_dir=Path("/tmp/ifnotus-test-slices-unused"))
    actions = rec.plan_hierarchy() + rec.plan_service_dropins()
    for act in actions:
        assert not act.path.startswith("/srv/apps/ifnotus-customers")
        assert act.action in {"write_slice", "write_dropin", "write_unit", "remove_legacy_slice"}


def test_php_pools_group_by_environment() -> None:
    env_a = uuid4()
    env_b = uuid4()
    pools = [
        HostnamePool("a.example", env_a, "pool-a", "/run/php/a.sock"),
        HostnamePool("b.example", env_a, "pool-b", "/run/php/b.sock"),
        HostnamePool("c.example", env_b, "pool-c", "/run/php/c.sock"),
    ]
    grouped = group_pools_by_environment(pools)
    assert len(grouped[env_a]) == 2
    assert len(grouped[env_b]) == 1
    assert planned_fpm_service_name(env_a) != planned_fpm_service_name(env_b)
    assert_environments_never_share_instance(grouped)
    assert PHASE_2B_PHP_ENV_MASTER_DESIGN["recommended_model"] == "ONE_FPM_MASTER_PER_CUSTOMER_ENVIRONMENT"
    est = estimate_master_overhead(environment_count=33, baseline_master_rss_kib=37360)
    assert est["estimated_total_rss_mib"] > 0
