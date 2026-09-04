"""Tests for customer-facing domain folder path display."""

from pathlib import Path

from app.services.platform.tenant import (
    customer_folder_relative,
    resolve_site_home,
    sanitize_relative_doc_root,
)


def test_sanitize_relative_doc_root_strips_traversal() -> None:
    assert sanitize_relative_doc_root("../etc/passwd", fallback="safe.com") == "etc/passwd"
    assert sanitize_relative_doc_root("/votebridge.online", fallback="x") == "votebridge.online"
    assert sanitize_relative_doc_root("", fallback="blog.example.com") == "blog.example.com"
    assert sanitize_relative_doc_root("apps/mysite", fallback="x") == "apps/mysite"


def test_customer_folder_relative_strips_web_leaves(tmp_path: Path) -> None:
    home = tmp_path / "csdttu.online"
    quiz = home / "quizsnap.online"
    vote = home / "votebridge.online"
    (quiz / "public").mkdir(parents=True)
    (vote / "frontend" / "dist").mkdir(parents=True)
    (home / "public_html").mkdir(parents=True)

    assert (
        customer_folder_relative(home, quiz / "public", fallback="quizsnap.online")
        == "/quizsnap.online"
    )
    assert (
        customer_folder_relative(home, quiz, fallback="quizsnap.online")
        == "/quizsnap.online"
    )
    assert (
        customer_folder_relative(
            home, vote / "frontend" / "dist", fallback="votebridge.online"
        )
        == "/votebridge.online"
    )
    assert (
        customer_folder_relative(home, home / "public_html", fallback="x")
        == "/public_html"
    )


def test_resolve_site_home_from_public_html(tmp_path: Path) -> None:
    home = tmp_path / "site"
    pub = home / "public_html"
    pub.mkdir(parents=True)
    assert resolve_site_home(pub) == home.resolve()
    assert resolve_site_home(home) == home.resolve()
