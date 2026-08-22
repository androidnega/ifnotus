"""PHASE 27 — multi-database entitlements and listing."""

from __future__ import annotations

from uuid import uuid4

from app.models.platform import HostingPlan
from app.services.platform.environment_databases import entitlements_for_plan
from app.services.platform.plan_matrix import MATRIX


class _Plan:
    def __init__(self, matrix_key: str) -> None:
        self.features = {"matrix_key": matrix_key}


def test_student_starter_mysql_only_quota() -> None:
    ent = entitlements_for_plan(_Plan("student-starter"))
    assert ent.mysql_databases == 1
    assert ent.postgres_databases == 0


def test_student_pro_allows_postgres() -> None:
    ent = entitlements_for_plan(_Plan("student-pro"))
    assert ent.mysql_databases == 2
    assert ent.postgres_databases == 1
    assert ent.database_storage_mb == 512


def test_plan_matrix_exposes_database_fields() -> None:
    feats = MATRIX["student-pro"]
    assert "mysql_databases" in feats
    assert "postgres_databases" in feats
    assert "remote_database_access" in feats


def test_legacy_id_helper() -> None:
    from app.services.platform.environment_databases import _is_legacy_id, _legacy_id

    env_id = uuid4()
    lid = _legacy_id(env_id)
    assert _is_legacy_id(lid)
    assert not _is_legacy_id(str(uuid4()))
