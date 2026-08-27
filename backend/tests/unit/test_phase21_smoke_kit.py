"""PHASE 21 — smoke script dry-run shape / checklist presence."""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]


def test_phase21_smoke_script_covers_student_zone() -> None:
    path = ROOT / "scripts" / "smoke_buy_to_hosting.py"
    assert path.is_file()
    text = path.read_text(encoding="utf-8")
    assert "unix_username" in text
    assert "confirm-payment" in text
    assert "ifnotus.space" in text or "student_zone" in text


def test_smoke_script_exists_and_has_safe_default() -> None:
    path = ROOT / "scripts" / "smoke_buy_to_hosting.py"
    assert path.is_file()
    text = path.read_text(encoding="utf-8")
    assert "--dry-run" in text
    assert "--live-write" in text
    assert "student_zone" in text


def test_environment_response_exposes_unix_fields() -> None:
    from app.schemas.platform import EnvironmentResponse

    fields = EnvironmentResponse.model_fields
    assert "unix_username" in fields
    assert "unix_uid" in fields
    assert "unix_gid" in fields
