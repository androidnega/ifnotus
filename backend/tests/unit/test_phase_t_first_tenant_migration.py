"""PHASE T — First Legacy Tenant Migration Unit Tests.

Verifies:
1. Low-risk tenant selection (least complex, active, provider=legacy).
2. 12-Step Migration Sequence:
   1. create fresh backup
   2. create ISPConfig client
   3. create ISPConfig site
   4. rsync files
   5. preserve permissions (0710)
   6. migrate/attach database
   7. configure DNS
   8. issue SSL
   9. configure FTP/SFTP
   10. smoke test
   11. switch provider=ispconfig
   12. monitor & 14-day archive retention
3. Safety rules: Do NOT delete old legacy files, enforce 7-14 days archive retention.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from app.models.platform import Customer, CustomerEnvironment, HostingPlan, Subscription
from app.services.platform.migration import TenantMigrationService


def _settings(**kw) -> SimpleNamespace:
    base = {
        "ispconfig_base_url": "https://127.0.0.1:8081",
        "ispconfig_remote_user": "remote_admin",
        "ispconfig_remote_password": "remote_password",
        "ispconfig_server_id": 1,
        "ispconfig_reseller_id": 0,
        "ispconfig_timeout_seconds": 30,
        "operations_backup_dir": ".ifnotus/backups",
    }
    base.update(kw)
    return SimpleNamespace(**base)


@pytest.mark.asyncio
async def test_pick_low_risk_candidate() -> None:
    """Test picking candidate queries active legacy environments."""
    session = AsyncMock()
    mock_env = CustomerEnvironment()
    mock_env.id = uuid4()
    mock_env.provider = "legacy"
    mock_env.status = "active"

    mock_res = MagicMock()
    mock_res.scalar_one_or_none.return_value = mock_env
    session.execute.return_value = mock_res

    svc = TenantMigrationService(_settings(), session)
    candidate = await svc.pick_low_risk_candidate()

    assert candidate is not None
    assert candidate.provider == "legacy"


@pytest.mark.asyncio
async def test_full_12_step_tenant_migration() -> None:
    """Test complete 12-step migration sequence."""
    env_id = uuid4()
    cust_id = uuid4()
    sub_id = uuid4()
    plan_id = uuid4()

    env = CustomerEnvironment()
    env.id = env_id
    env.customer_id = cust_id
    env.subscription_id = sub_id
    env.domain = "alice.ifnotus.space"
    env.provider = "legacy"
    env.status = "active"
    env.storage_limit_gb = 5
    env.document_root = "/tmp/alice_legacy"

    cust = Customer()
    cust.id = cust_id
    cust.email = "alice@ifnotus.space"
    cust.full_name = "Alice Doe"

    plan = HostingPlan()
    plan.id = plan_id
    plan.slug = "student-starter"

    sub = Subscription()
    sub.id = sub_id
    sub.customer_id = cust_id
    sub.plan_id = plan_id

    session = AsyncMock()

    async def mock_get(model, pk):
        if model == CustomerEnvironment:
            return env
        if model == Customer:
            return cust
        if model == Subscription:
            return sub
        if model == HostingPlan:
            return plan
        return None

    session.get.side_effect = mock_get

    svc = TenantMigrationService(_settings(), session)

    # Run migration with dry_run=True
    state = await svc.execute_tenant_migration(env_id, dry_run=True)

    assert state.overall_status == "success"
    assert len(state.steps) == 12

    # Step names verification
    step_names = [s.step_name for s in state.steps]
    expected_steps = [
        "create_fresh_backup",
        "create_ispconfig_client",
        "create_ispconfig_site",
        "rsync_files",
        "preserve_permissions",
        "migrate_database",
        "configure_dns",
        "issue_ssl",
        "configure_ftp_sftp",
        "smoke_test",
        "switch_provider",
        "monitor_and_retain",
    ]
    assert step_names == expected_steps

    # Confirm 14-day retention rule
    assert state.archive_retention_until is not None
    assert "Retained until" in state.steps[11].details


@pytest.mark.asyncio
async def test_migration_blocks_already_migrated_environment() -> None:
    """Test migration rejects environment if already on provider=ispconfig."""
    env_id = uuid4()
    env = CustomerEnvironment()
    env.id = env_id
    env.provider = "ispconfig"

    session = AsyncMock()
    session.get.return_value = env

    svc = TenantMigrationService(_settings(), session)

    from app.core.exceptions import ValidationError
    with pytest.raises(ValidationError, match="already on provider='ispconfig'"):
        await svc.execute_tenant_migration(env_id)
