"""PHASE 28 — email product entitlements."""

from __future__ import annotations

from app.models.platform import HostingPlan
from app.services.platform.environment_mail import (
    EnvironmentMailService,
    entitlements_for_plan,
)
from app.services.platform.plan_matrix import MATRIX, capabilities_for


class _Plan:
    def __init__(self, matrix_key: str) -> None:
        self.features = {"matrix_key": matrix_key}


def test_club_connect_mail_storage() -> None:
    ent = entitlements_for_plan(_Plan("club-connect"))
    assert ent.enabled is True
    assert ent.mailboxes == 5
    assert ent.storage_mb == 2048


def test_student_starter_single_mailbox() -> None:
    ent = entitlements_for_plan(_Plan("student-starter"))
    assert ent.mailboxes == 1
    assert ent.storage_mb == 512


def test_capabilities_expose_mail_object() -> None:
    caps = capabilities_for(_Plan("student-pro"))
    assert caps["mail"]["enabled"] is True
    assert caps["mail"]["mailboxes"] == 10
    assert caps["on"]["mail"] is True


def test_matrix_has_mail_fields() -> None:
    row = MATRIX["club-connect"]
    assert row["mail_enabled"] is True
    assert row["mail_storage_mb"] == 2048


def test_reserved_local_rejected() -> None:
    import pytest

    with pytest.raises(Exception, match="reserved"):
        EnvironmentMailService._validate_local_part("postmaster")
