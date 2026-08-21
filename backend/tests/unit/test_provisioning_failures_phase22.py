"""PHASE 22 — Provisioning failure classification and idempotency."""

from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

from app.services.platform.provisioning import (
    HARD_FAIL_STEPS,
    SOFT_FAIL_STEPS,
    classify_provision_failure,
    docker_downgrade_allowed,
)
from app.services.platform.unix_identity import UnixIdentityService


def test_hard_fail_steps_never_include_active() -> None:
    assert "ACTIVE" not in HARD_FAIL_STEPS
    assert "CONFIGURING_WEB" in HARD_FAIL_STEPS
    assert "CREATING_ISOLATION" in HARD_FAIL_STEPS


def test_ssl_is_soft_fail_category() -> None:
    info = classify_provision_failure("CONFIGURING_SSL", RuntimeError("certbot failed"))
    assert info["category"] == "ssl"
    assert info["step"] == "CONFIGURING_SSL"
    # SSL step itself is soft in SOFT_FAIL_STEPS; hard_fail may still be false via step
    assert "CONFIGURING_SSL" in SOFT_FAIL_STEPS


def test_nginx_failure_is_hard() -> None:
    info = classify_provision_failure("CONFIGURING_WEB", RuntimeError("nginx provision failed: syntax"))
    assert info["category"] == "nginx"
    assert info["hard_fail"] is True
    assert info["expected_env_status"] == "provisioning_failed"


def test_docker_required_failure_is_hard() -> None:
    info = classify_provision_failure(
        "CREATING_ISOLATION",
        RuntimeError("Failed to start Docker container for a plan that requires docker isolation."),
    )
    assert info["category"] == "docker"
    assert info["hard_fail"] is True


def test_capacity_failure_is_hard() -> None:
    info = classify_provision_failure(
        "ALLOCATING_NODE",
        RuntimeError("Insufficient capacity for this plan."),
    )
    assert info["category"] == "capacity"
    assert info["hard_fail"] is True


def test_unix_transfer_failure_is_hard() -> None:
    info = classify_provision_failure(
        "CONFIGURING_TRANSFER",
        RuntimeError("unix identity / transfer provision failed: useradd denied"),
    )
    assert info["category"] == "unix_or_transfer"
    assert info["hard_fail"] is True


def test_dns_classified() -> None:
    info = classify_provision_failure("HEALTH_CHECK", RuntimeError("DNS lookup failed"))
    assert info["category"] == "dns"


def test_duplicate_hostname_classified() -> None:
    info = classify_provision_failure("CONFIGURING_WEB", RuntimeError("duplicate hostname conflict"))
    assert info["category"] == "domain"
    assert info["hard_fail"] is True


def test_unix_username_stable_across_retries() -> None:
    """Retries must reuse ifn_<id>, never ifn_<id>_2."""
    env_id = uuid4()
    env = SimpleNamespace(id=env_id, unix_username=None, sftp_username=None)
    svc = UnixIdentityService.__new__(UnixIdentityService)
    first = UnixIdentityService.username_for(svc, env)
    env.unix_username = first
    second = UnixIdentityService.username_for(svc, env)
    assert first == second
    assert first.startswith("ifn_")
    assert "_2" not in first
    assert first.count("_") == 1


def test_fail_job_markers_contract() -> None:
    """Document expected statuses after hard failure (used by worker + ops)."""
    info = classify_provision_failure("CONFIGURING_WEB", "boom")
    assert info["expected_env_status"] == "provisioning_failed"


def test_docker_policy_still_blocks_silent_downgrade() -> None:
    plan = SimpleNamespace(slug="macho-power", name="Macho Power", price_monthly=300, features=None)
    assert docker_downgrade_allowed(plan, "docker") is False
