"""PHASE 38L — mail entitlements, suspend/restore, reserved locals."""

from __future__ import annotations

import pytest

from app.services.platform.environment_mail import (
    EnvironmentMailService,
    MailEntitlements,
    entitlements_for_plan,
)


class _Plan:
    def __init__(self, matrix_key: str) -> None:
        self.features = {"matrix_key": matrix_key}


def test_mailbox_limit_entitlement_starter() -> None:
    ent = entitlements_for_plan(_Plan("student-starter"))
    assert ent.enabled is True
    assert ent.mailboxes == 1
    assert ent.storage_mb == 512


def test_mailbox_limit_entitlement_pro() -> None:
    ent = entitlements_for_plan(_Plan("student-pro"))
    assert ent.mailboxes == 10


def test_default_quota_splits_storage() -> None:
    svc = object.__new__(EnvironmentMailService)
    ent = MailEntitlements(enabled=True, mailboxes=4, storage_mb=2048)
    assert svc._default_quota_mb(ent) == 512


def test_reserved_and_invalid_locals() -> None:
    with pytest.raises(Exception):
        EnvironmentMailService._validate_local_part("abuse")
    with pytest.raises(Exception):
        EnvironmentMailService._validate_local_part("Bad Name")
    EnvironmentMailService._validate_local_part("hello.world")


def test_unsuspend_method_exists() -> None:
    assert hasattr(EnvironmentMailService, "unsuspend_all_mailboxes")
    assert hasattr(EnvironmentMailService, "suspend_all_mailboxes")
