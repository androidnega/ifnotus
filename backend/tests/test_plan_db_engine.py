from types import SimpleNamespace

from app.services.platform.plan_matrix import capabilities_for, default_db_engine


def _plan(slug: str, name: str = "", price: float = 0) -> SimpleNamespace:
    return SimpleNamespace(slug=slug, name=name or slug, features={}, price_monthly=price)


def test_managed_packs_default_to_mysql() -> None:
    assert default_db_engine(_plan("personal")) == "mysql"
    assert default_db_engine(_plan("student-starter")) == "mysql"
    assert default_db_engine(_plan("monster-cloud")) == "mysql"


def test_capabilities_expose_mysql_stack() -> None:
    caps = capabilities_for(_plan("student-starter"))
    assert caps["on"]["mysql"] is True
    assert caps["on"]["ai"] is True
    assert caps["on"]["docker"] is False
