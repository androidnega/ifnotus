"""Stack filesystem detection and meta normalization (Phase D)."""

from __future__ import annotations

from pathlib import Path

from app.services.platform.stacks import (
    detect_stack_from_filesystem,
    normalize_stack_payload,
)


def test_detect_wordpress(tmp_path: Path) -> None:
    root = tmp_path / "site"
    root.mkdir()
    (root / "wp-config.php").write_text("<?php", encoding="utf-8")
    (root / "wp-content").mkdir()
    hit = detect_stack_from_filesystem(root)
    assert hit is not None
    assert hit["stack"] == "wordpress"
    assert hit["runtime"] == "php"


def test_detect_laravel(tmp_path: Path) -> None:
    root = tmp_path / "site"
    root.mkdir()
    (root / "artisan").write_text("#!/usr/bin/env php\n", encoding="utf-8")
    (root / "composer.json").write_text("{}", encoding="utf-8")
    (root / "public").mkdir()
    (root / "public" / "index.php").write_text("<?php", encoding="utf-8")
    hit = detect_stack_from_filesystem(root)
    assert hit is not None
    assert hit["stack"] == "laravel"


def test_detect_nodejs(tmp_path: Path) -> None:
    root = tmp_path / "site"
    root.mkdir()
    (root / "package.json").write_text('{"dependencies":{"express":"^4.0.0"}}', encoding="utf-8")
    (root / "server.js").write_text("console.log(1)", encoding="utf-8")
    hit = detect_stack_from_filesystem(root)
    assert hit is not None
    assert hit["stack"] == "nodejs"


def test_parking_page_is_not_a_stack(tmp_path: Path) -> None:
    root = tmp_path / "site"
    root.mkdir()
    (root / "index.html").write_text(
        "<html><body><h1>Your hosting is ready</h1></body></html>",
        encoding="utf-8",
    )
    assert detect_stack_from_filesystem(root) is None


def test_normalize_adds_display_fields() -> None:
    out = normalize_stack_payload({"stack": "wordpress"}, source="meta")
    assert out["stack_name"] == "WordPress"
    assert out["runtime"] == "php"
    assert out["status"] == "running"
    assert out["source"] == "meta"
