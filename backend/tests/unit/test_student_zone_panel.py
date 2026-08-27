"""Panel / platform hostname helpers for student zone (PHASE 1)."""

from __future__ import annotations

from app.services.platform.panel_access import control_panel_hostname, is_platform_hostname


def test_platform_hostname_covers_control_and_student_zones() -> None:
    assert is_platform_hostname("ifnotus.space")
    assert is_platform_hostname("ready.ifnotus.space")
    assert is_platform_hostname("mensah.ifnotus.space")
    assert is_platform_hostname("mensah1.serverlabsttu.space")  # legacy student
    assert not is_platform_hostname("studio.online")
    assert not is_platform_hostname("shop.example.com")


def test_control_panel_hostname_skipped_for_student_zones() -> None:
    assert control_panel_hostname("mensah.serverlabsttu.space") is None
    assert control_panel_hostname("mensah.ifnotus.space") is None
    assert control_panel_hostname("studio.online") == "cpanel.studio.online"
