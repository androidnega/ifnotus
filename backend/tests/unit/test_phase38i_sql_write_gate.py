"""PHASE 38I — Staff SQL studio read vs write / destructive classification."""

from __future__ import annotations

import pytest

from app.services.hosting.db_studio import DatabaseStudioService as S


@pytest.mark.parametrize(
    "sql,expected",
    [
        ("SELECT * FROM users", "read"),
        ("  show tables", "read"),
        ("EXPLAIN SELECT 1", "read"),
        ("INSERT INTO t VALUES (1)", "write"),
        ("UPDATE t SET a=1", "write"),
        ("DELETE FROM t WHERE id=1", "write"),
        ("DROP TABLE t", "destructive"),
        ("ALTER TABLE t ADD COLUMN x INT", "destructive"),
        ("TRUNCATE TABLE t", "destructive"),
        ("CREATE TABLE t (id INT)", "destructive"),
        ("GRANT ALL ON db.* TO 'u'@'%'", "destructive"),
        ("REVOKE ALL ON db.* FROM 'u'@'%'", "destructive"),
    ],
)
def test_sql_query_class(sql: str, expected: str) -> None:
    assert S.query_class(sql=sql) == expected


def test_select_permitted_without_write_flag() -> None:
    assert not S.is_write_sql("SELECT id FROM accounts LIMIT 10")
    assert S.query_class(sql="SELECT 1") == "read"


def test_insert_is_write_not_destructive() -> None:
    assert S.is_write_sql("INSERT INTO t (a) VALUES (1)")
    assert not S.is_destructive_sql("INSERT INTO t (a) VALUES (1)")


def test_drop_is_destructive() -> None:
    assert S.is_write_sql("DROP DATABASE foo")
    assert S.is_destructive_sql("DROP DATABASE foo")


def test_unknown_sql_fails_closed_as_write() -> None:
    assert S.is_write_sql("DO $$ BEGIN RAISE NOTICE 'x'; END $$")
    assert S.query_class(sql="DO $$ BEGIN NULL; END $$") == "write"


def test_mongo_find_is_read() -> None:
    assert S.query_class(script="db.getCollection('c').find().limit(10).toArray()", engine="mongodb") == "read"


def test_mongo_insert_is_write() -> None:
    assert S.query_class(script="db.c.insertOne({a:1})", engine="mongodb") == "write"


def test_mongo_drop_is_destructive() -> None:
    assert S.query_class(script="db.c.drop()", engine="mongodb") == "destructive"


def test_sql_verb_redacts_to_keyword_only() -> None:
    assert S.sql_verb("DROP TABLE secret_stuff") == "DROP"
    assert S.sql_verb("  insert into x values (1)") == "INSERT"
