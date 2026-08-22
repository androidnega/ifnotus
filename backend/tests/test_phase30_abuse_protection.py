"""PHASE 30 — automated abuse protection."""

from __future__ import annotations

from app.services.platform.environment_abuse import AbuseSignal, EnvironmentAbuseService


def test_decide_actions_warns_before_critical() -> None:
    svc = EnvironmentAbuseService(settings=None, session=None)  # type: ignore[arg-type]
    signals = [
        AbuseSignal("disk_pressure", "warning", "high disk"),
        AbuseSignal("fork_bomb", "critical", "too many processes"),
    ]
    actions = svc.decide_actions(signals)
    kinds = [a.kind for a in actions]
    assert "warning" in kinds
    assert "suspend" in kinds
    assert "admin_alert" in kinds


def test_decide_actions_empty_when_no_signals() -> None:
    svc = EnvironmentAbuseService(settings=None, session=None)  # type: ignore[arg-type]
    assert svc.decide_actions([]) == []


def test_scan_public_content_flags_phishing(tmp_path) -> None:
    from app.services.platform.environment_abuse import _scan_public_content

    (tmp_path / "index.html").write_text(
        "<html><body>Verify your account immediately or it will be closed.</body></html>",
        encoding="utf-8",
    )
    hits = _scan_public_content(tmp_path)
    assert "index.html" in hits
