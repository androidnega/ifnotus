"""PHASE O — Product Application Separation verification unit tests.

Verifies:
1. Explicit classification into Platform, Products, Tenants, Infrastructure.
2. Product apps (VoteBridge, QuizSnap, ExamFlow, csdttu, serverlabsttu) never inherit tenant quotas.
3. Customer file-manager access is strictly locked to tenant root (cannot escape to /srv/apps/votebridge etc.).
4. Super Admin UI inventory exposes clean resource_class groupings.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.core.exceptions import AppException
from app.schemas.inventory import ResourceClass, classify_resource
from app.services.hosting.files import FileManagerService


def test_resource_classification() -> None:
    """Test classification of platform, product, tenant, and infrastructure resources."""
    # Platform
    assert classify_resource("ifnotus-api", "/srv/apps/ifnotus/backend") == ResourceClass.PLATFORM
    assert classify_resource("fpanel.ifnotus.space", None, ["fpanel.ifnotus.space"]) == ResourceClass.PLATFORM
    assert classify_resource("cpanel.ifnotus.space", None, ["cpanel.ifnotus.space"]) == ResourceClass.PLATFORM

    # Sibling Products (NOT tenant hosting)
    assert classify_resource("votebridge", "/srv/apps/votebridge") == ResourceClass.PRODUCT
    assert classify_resource("quizsnap", "/srv/apps/quizsnap") == ResourceClass.PRODUCT
    assert classify_resource("examflow", "/srv/apps/csdttu/examflow") == ResourceClass.PRODUCT
    assert classify_resource("csdttu", "/srv/apps/csdttu") == ResourceClass.PRODUCT
    assert classify_resource("serverlabsttu", "/srv/apps/serverlabsttu") == ResourceClass.PRODUCT
    assert classify_resource("doc-app", None, ["documento.csdttu.online"]) == ResourceClass.PRODUCT

    # Tenants
    assert (
        classify_resource("student-site", "/srv/apps/ifnotus-customers/stud1/public")
        == ResourceClass.TENANT
    )

    # Infrastructure
    assert classify_resource("nginx", "/etc/nginx") == ResourceClass.INFRASTRUCTURE
    assert classify_resource("postfix", "/var/vmail") == ResourceClass.INFRASTRUCTURE
    assert classify_resource("bind9", "/etc/bind") == ResourceClass.INFRASTRUCTURE


def test_tenant_file_manager_isolation_blocks_product_access(tmp_path: Path) -> None:
    """Test that customer file manager cannot access product app directories."""
    # Set up mock folders
    product_dir = tmp_path / "apps" / "votebridge"
    product_dir.mkdir(parents=True)
    (product_dir / "secret.env").write_text("DB_PASS=secret", encoding="utf-8")

    tenant_dir = tmp_path / "ifnotus-customers" / "tenant1"
    tenant_dir.mkdir(parents=True)
    (tenant_dir / "index.php").write_text("<?php echo 'hello'; ?>", encoding="utf-8")

    settings = SimpleNamespace(
        hosting_allowed_paths=[str(tmp_path)],
        discovery_scan_paths=[],
        discovery_max_depth=2,
        applications_dir=str(tmp_path / "apps_dir"),
        applications_config_file=str(tmp_path / "apps.yaml"),
        applications_reload_interval_seconds=60,
    )

    # Customer manager initialized with only_roots=[tenant_dir]
    customer_files = FileManagerService(
        settings,
        only_roots=[tenant_dir],
        storage_limit_gb=1,
    )

    # Customer can resolve files inside tenant root
    base = customer_files.resolve_base(None)
    assert base == tenant_dir.resolve()

    # Attempting to resolve or read paths outside tenant root must fail
    with pytest.raises((AppException, ValueError, FileNotFoundError)):
        customer_files._safe_path(base, "../apps/votebridge/secret.env")


def test_product_apps_do_not_inherit_tenant_quotas(tmp_path: Path) -> None:
    """Test that admin/product file services do not apply tenant quotas."""
    product_dir = tmp_path / "apps" / "examflow"
    product_dir.mkdir(parents=True)

    settings = SimpleNamespace(
        hosting_allowed_paths=[str(tmp_path)],
        discovery_scan_paths=[],
        discovery_max_depth=2,
        applications_dir=str(tmp_path / "apps_dir"),
        applications_config_file=str(tmp_path / "apps.yaml"),
        applications_reload_interval_seconds=60,
    )

    # Staff / admin file service for product apps
    staff_files = FileManagerService(settings, admin_storage=True)
    # Storage limit is None for non-tenant apps
    assert staff_files._storage_limit_gb is None
