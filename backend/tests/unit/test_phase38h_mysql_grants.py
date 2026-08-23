"""PHASE 38H — MySQL grants follow remote-access entitlement."""

from __future__ import annotations


def test_localhost_plan_sql_has_no_percent_host() -> None:
    from app.services.hosting.databases import mysql_user_grant_sql

    sql = mysql_user_grant_sql(
        username="u_demo",
        password="secret",
        database="db_demo",
        allow_remote=False,
        escape=lambda s: s.replace("'", "''"),
    )
    joined = "\n".join(sql)
    assert "@'localhost'" in joined
    assert "@'%'" not in joined
    assert "FLUSH PRIVILEGES" in joined


def test_remote_plan_sql_includes_percent_host() -> None:
    from app.services.hosting.databases import mysql_user_grant_sql

    sql = mysql_user_grant_sql(
        username="u_demo",
        password="secret",
        database="db_demo",
        allow_remote=True,
        escape=lambda s: s,
    )
    joined = "\n".join(sql)
    assert "@'localhost'" in joined
    assert "@'%'" in joined


def test_revoke_remote_drops_percent_only() -> None:
    from app.services.hosting.databases import mysql_revoke_remote_sql

    sql = "\n".join(mysql_revoke_remote_sql(username="u_demo", escape=lambda s: s))
    assert "DROP USER IF EXISTS 'u_demo'@'%'" in sql
    assert "@'localhost'" not in sql
