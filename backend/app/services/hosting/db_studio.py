"""Interactive database studio — browse, query, edit MySQL/PostgreSQL/SQLite/MongoDB."""

from __future__ import annotations

import asyncio
import json
import re
import sqlite3
import subprocess
import time
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import UUID

import pymysql

from app.core.exceptions import AppException, NotFoundError
from app.schemas.databases import (
    DatabaseEngine,
    DbColumnSchema,
    DbQueryRequest,
    DbQueryResponse,
    DbRowMutationRequest,
    DbRowsRequest,
    DbSchemaResponse,
    DbTableSchema,
)
from app.services.hosting.databases import DatabaseManagerService

_IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_WRITE_SQL = re.compile(
    r"^\s*(INSERT|UPDATE|DELETE|ALTER|DROP|CREATE|TRUNCATE|REPLACE|GRANT|REVOKE|RENAME)\b",
    re.I,
)


def _jsonable(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (bytes, bytearray)):
        return value.decode("utf-8", errors="replace")
    if isinstance(value, UUID):
        return str(value)
    return str(value)


def _quote_ident(name: str, engine: str) -> str:
    if not _IDENT.match(name):
        raise AppException(f"Invalid identifier: {name}", code="db_bad_ident")
    if engine == "mysql":
        return f"`{name}`"
    if engine == "postgresql":
        return f'"{name}"'
    return name


class DatabaseStudioService:
    """Query and mutate host databases for the studio UI / AI."""

    def __init__(self, manager: DatabaseManagerService) -> None:
        self._manager = manager

    def _managed(self, db_id: str) -> dict[str, Any]:
        for raw in self._manager._read_registry():
            if raw.get("id") == db_id:
                password = None
                if raw.get("password_encrypted"):
                    password = self._manager._decrypt(str(raw["password_encrypted"]))
                return {
                    "engine": raw.get("engine"),
                    "name": raw.get("name"),
                    "username": raw.get("username"),
                    "password": password,
                    "host": raw.get("host") or "127.0.0.1",
                    "port": raw.get("port"),
                    "path": raw.get("path"),
                    "id": db_id,
                }
        raise NotFoundError(f"Managed database {db_id} not found.")

    def _live(self, engine: DatabaseEngine, name: str, path: str | None = None) -> dict[str, Any]:
        if engine == "sqlite":
            if not path:
                raise AppException("SQLite live open requires path.", code="db_path_required")
            return {"engine": "sqlite", "name": Path(path).stem, "path": path, "id": None}
        return {
            "engine": engine,
            "name": name,
            "username": None,
            "password": None,
            "host": "127.0.0.1",
            "port": {"mysql": 3306, "postgresql": 5432, "mongodb": 27017}.get(engine),
            "path": None,
            "id": None,
            "system": True,
        }

    async def schema_managed(self, db_id: str) -> DbSchemaResponse:
        return await asyncio.to_thread(self._schema, self._managed(db_id))

    async def schema_live(self, engine: DatabaseEngine, name: str, path: str | None = None) -> DbSchemaResponse:
        return await asyncio.to_thread(self._schema, self._live(engine, name, path))

    async def rows_managed(self, db_id: str, body: DbRowsRequest) -> DbQueryResponse:
        return await asyncio.to_thread(self._preview_rows, self._managed(db_id), body)

    async def rows_live(
        self, engine: DatabaseEngine, name: str, body: DbRowsRequest, path: str | None = None
    ) -> DbQueryResponse:
        return await asyncio.to_thread(self._preview_rows, self._live(engine, name, path), body)

    async def query_managed(self, db_id: str, body: DbQueryRequest) -> DbQueryResponse:
        return await asyncio.to_thread(self._run_query, self._managed(db_id), body)

    async def query_live(
        self, engine: DatabaseEngine, name: str, body: DbQueryRequest, path: str | None = None
    ) -> DbQueryResponse:
        return await asyncio.to_thread(self._run_query, self._live(engine, name, path), body)

    async def update_row_managed(self, db_id: str, body: DbRowMutationRequest) -> DbQueryResponse:
        return await asyncio.to_thread(self._update_row, self._managed(db_id), body)

    async def update_row_live(
        self, engine: DatabaseEngine, name: str, body: DbRowMutationRequest, path: str | None = None
    ) -> DbQueryResponse:
        return await asyncio.to_thread(self._update_row, self._live(engine, name, path), body)

    async def delete_row_managed(self, db_id: str, body: DbRowMutationRequest) -> DbQueryResponse:
        return await asyncio.to_thread(self._delete_row, self._managed(db_id), body)

    async def delete_row_live(
        self, engine: DatabaseEngine, name: str, body: DbRowMutationRequest, path: str | None = None
    ) -> DbQueryResponse:
        return await asyncio.to_thread(self._delete_row, self._live(engine, name, path), body)

    async def insert_row_managed(self, db_id: str, body: DbRowMutationRequest) -> DbQueryResponse:
        return await asyncio.to_thread(self._insert_row, self._managed(db_id), body)

    async def insert_row_live(
        self, engine: DatabaseEngine, name: str, body: DbRowMutationRequest, path: str | None = None
    ) -> DbQueryResponse:
        return await asyncio.to_thread(self._insert_row, self._live(engine, name, path), body)

    # ── Schema ─────────────────────────────────────────────────────────────

    def _schema(self, conn: dict[str, Any]) -> DbSchemaResponse:
        engine = str(conn["engine"])
        if engine == "sqlite":
            return self._schema_sqlite(conn)
        if engine == "mysql":
            return self._schema_mysql(conn)
        if engine == "postgresql":
            return self._schema_pg(conn)
        if engine == "mongodb":
            return self._schema_mongo(conn)
        raise AppException(f"Unsupported engine: {engine}", code="db_engine_unsupported")

    def _schema_sqlite(self, conn: dict[str, Any]) -> DbSchemaResponse:
        path = Path(str(conn["path"]))
        if not path.exists():
            raise AppException(f"SQLite file not found: {path}", code="db_sqlite_missing")
        db = sqlite3.connect(str(path))
        try:
            tables: list[DbTableSchema] = []
            cur = db.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
            )
            for (tname,) in cur.fetchall():
                cols = []
                for row in db.execute(f"PRAGMA table_info({_quote_ident(tname, 'sqlite')})"):
                    cols.append(
                        DbColumnSchema(
                            name=row[1],
                            data_type=row[2],
                            nullable=not row[3],
                            primary_key=bool(row[5]),
                            default=str(row[4]) if row[4] is not None else None,
                        )
                    )
                tables.append(DbTableSchema(name=tname, columns=cols))
            return DbSchemaResponse(engine="sqlite", database=path.name, path=str(path), tables=tables)
        finally:
            db.close()

    def _schema_mysql(self, conn: dict[str, Any]) -> DbSchemaResponse:
        link = self._mysql_connect(conn)
        try:
            dbname = str(conn["name"])
            with link.cursor() as cur:
                cur.execute(
                    """
                    SELECT TABLE_NAME, TABLE_ROWS
                    FROM information_schema.TABLES
                    WHERE TABLE_SCHEMA=%s AND TABLE_TYPE='BASE TABLE'
                    ORDER BY TABLE_NAME
                    """,
                    (dbname,),
                )
                table_rows = cur.fetchall()
                tables: list[DbTableSchema] = []
                for tname, approx in table_rows:
                    cur.execute(
                        """
                        SELECT COLUMN_NAME, DATA_TYPE, IS_NULLABLE, COLUMN_KEY, COLUMN_DEFAULT
                        FROM information_schema.COLUMNS
                        WHERE TABLE_SCHEMA=%s AND TABLE_NAME=%s
                        ORDER BY ORDINAL_POSITION
                        """,
                        (dbname, tname),
                    )
                    cols = [
                        DbColumnSchema(
                            name=r[0],
                            data_type=r[1],
                            nullable=r[2] == "YES",
                            primary_key=r[3] == "PRI",
                            default=str(r[4]) if r[4] is not None else None,
                        )
                        for r in cur.fetchall()
                    ]
                    tables.append(
                        DbTableSchema(name=tname, columns=cols, approx_rows=int(approx or 0))
                    )
            return DbSchemaResponse(engine="mysql", database=dbname, tables=tables)
        finally:
            link.close()

    def _schema_pg(self, conn: dict[str, Any]) -> DbSchemaResponse:
        # Use psql as system user when no password (live), else asyncpg via sync wrapper
        dbname = str(conn["name"])
        sql = """
        SELECT c.relname, n.nspname,
               GREATEST(
                 COALESCE(s.n_live_tup, 0),
                 COALESCE(c.reltuples, 0)::bigint
               )::bigint
        FROM pg_class c
        JOIN pg_namespace n ON n.oid = c.relnamespace
        LEFT JOIN pg_stat_all_tables s ON s.relid = c.oid
        WHERE c.relkind = 'r' AND n.nspname NOT IN ('pg_catalog','information_schema')
        ORDER BY n.nspname, c.relname;
        """
        code, out, err = self._psql(conn, sql)
        if code != 0:
            raise AppException(f"PostgreSQL schema failed: {err}", code="db_pg_schema")
        tables: list[DbTableSchema] = []
        for line in out.splitlines():
            parts = [p.strip() for p in line.split("|")]
            if len(parts) < 2 or not parts[0]:
                continue
            tname, schema = parts[0], parts[1]
            approx = int(parts[2]) if len(parts) > 2 and parts[2].isdigit() else None
            col_sql = f"""
            SELECT a.attname, pg_catalog.format_type(a.atttypid, a.atttypmod),
                   NOT a.attnotnull,
                   EXISTS (
                     SELECT 1 FROM pg_index i
                     WHERE i.indrelid = a.attrelid AND a.attnum = ANY(i.indkey) AND i.indisprimary
                   )
            FROM pg_attribute a
            JOIN pg_class c ON c.oid = a.attrelid
            JOIN pg_namespace n ON n.oid = c.relnamespace
            WHERE c.relname = '{tname}' AND n.nspname = '{schema}' AND a.attnum > 0 AND NOT a.attisdropped
            ORDER BY a.attnum;
            """
            ccode, cout, _ = self._psql(conn, col_sql)
            cols: list[DbColumnSchema] = []
            if ccode == 0:
                for crow in cout.splitlines():
                    cp = [p.strip() for p in crow.split("|")]
                    if len(cp) >= 2 and cp[0]:
                        cols.append(
                            DbColumnSchema(
                                name=cp[0],
                                data_type=cp[1],
                                nullable=cp[2].lower() in {"t", "true"} if len(cp) > 2 else None,
                                primary_key=cp[3].lower() in {"t", "true"} if len(cp) > 3 else False,
                            )
                        )
            tables.append(DbTableSchema(name=tname, schema_name=schema, columns=cols, approx_rows=approx))
        return DbSchemaResponse(engine="postgresql", database=dbname, tables=tables)

    def _schema_mongo(self, conn: dict[str, Any]) -> DbSchemaResponse:
        dbname = str(conn["name"])
        js = f"db.getSiblingDB('{dbname}').getCollectionNames().join('\\n')"
        code, out, err = self._mongo_eval(js)
        if code != 0:
            raise AppException(f"MongoDB schema failed: {err}", code="db_mongo_schema")
        collections = [c.strip() for c in out.splitlines() if c.strip()]
        return DbSchemaResponse(engine="mongodb", database=dbname, collections=collections)

    # ── Preview / query ────────────────────────────────────────────────────

    def _preview_rows(self, conn: dict[str, Any], body: DbRowsRequest) -> DbQueryResponse:
        engine = str(conn["engine"])
        if engine == "mongodb":
            coll = body.collection or body.table
            if not coll:
                raise AppException("collection is required", code="db_collection_required")
            js = (
                f"JSON.stringify(db.getSiblingDB('{conn['name']}').getCollection('{coll}')"
                f".find().skip({body.offset}).limit({body.limit}).toArray())"
            )
            code, out, err = self._mongo_eval(js)
            if code != 0:
                raise AppException(err or "Mongo preview failed", code="db_mongo_preview")
            try:
                docs = json.loads(out.strip() or "[]")
            except json.JSONDecodeError:
                docs = []
            if not isinstance(docs, list):
                docs = []
            cols: list[str] = []
            rows: list[dict[str, Any]] = []
            for doc in docs:
                if isinstance(doc, dict):
                    for k in doc:
                        if k not in cols:
                            cols.append(k)
                    rows.append({k: _jsonable(v) for k, v in doc.items()})
            return DbQueryResponse(
                engine="mongodb", columns=cols, rows=rows, row_count=len(rows), message=f"{coll}"
            )

        table = body.table
        if not table:
            raise AppException("table is required", code="db_table_required")
        limit = body.limit
        offset = body.offset
        if engine == "sqlite":
            sql = f"SELECT * FROM {_quote_ident(table, 'sqlite')} LIMIT {limit} OFFSET {offset}"
        elif engine == "mysql":
            sql = f"SELECT * FROM {_quote_ident(table, 'mysql')} LIMIT {limit} OFFSET {offset}"
        else:
            schema = body.schema_name or "public"
            sql = (
                f'SELECT * FROM {_quote_ident(schema, "postgresql")}.'
                f'{_quote_ident(table, "postgresql")} LIMIT {limit} OFFSET {offset}'
            )
        # Preview SQL already includes LIMIT/OFFSET — never auto-append another.
        return self._run_query(conn, DbQueryRequest(sql=sql, limit=limit), auto_limit=False)

    def _run_query(
        self, conn: dict[str, Any], body: DbQueryRequest, *, auto_limit: bool = True
    ) -> DbQueryResponse:
        engine = str(conn["engine"])
        started = time.perf_counter()
        if engine == "mongodb":
            script = body.script or body.sql
            if not script:
                raise AppException("script is required for MongoDB", code="db_script_required")
            # Wrap to return JSON when possible
            js = f"JSON.stringify((function(){{ {script} }})() ?? null)"
            code, out, err = self._mongo_eval(js)
            duration = (time.perf_counter() - started) * 1000
            if code != 0:
                # try raw script
                code2, out2, err2 = self._mongo_eval(script)
                duration = (time.perf_counter() - started) * 1000
                if code2 != 0:
                    raise AppException(err2 or err or "Mongo script failed", code="db_mongo_query")
                return DbQueryResponse(
                    engine="mongodb",
                    message=out2.strip()[:4000],
                    duration_ms=duration,
                    row_count=0,
                )
            try:
                data = json.loads(out.strip() or "null")
            except json.JSONDecodeError:
                return DbQueryResponse(
                    engine="mongodb", message=out.strip()[:4000], duration_ms=duration
                )
            if isinstance(data, list):
                cols: list[str] = []
                rows = []
                for doc in data:
                    if isinstance(doc, dict):
                        for k in doc:
                            if k not in cols:
                                cols.append(k)
                        rows.append({k: _jsonable(v) for k, v in doc.items()})
                truncated = len(rows) > body.limit
                return DbQueryResponse(
                    engine="mongodb",
                    columns=cols,
                    rows=rows[: body.limit],
                    row_count=min(len(rows), body.limit),
                    truncated=truncated,
                    duration_ms=duration,
                )
            if isinstance(data, dict):
                return DbQueryResponse(
                    engine="mongodb",
                    columns=list(data.keys()),
                    rows=[{k: _jsonable(v) for k, v in data.items()}],
                    row_count=1,
                    duration_ms=duration,
                )
            return DbQueryResponse(
                engine="mongodb", message=str(data), duration_ms=duration, row_count=0
            )

        sql = (body.sql or "").strip()
        if not sql:
            raise AppException("sql is required", code="db_sql_required")
        # Only allow a single statement
        if ";" in sql.rstrip(";"):
            raise AppException("Only one SQL statement is allowed per request.", code="db_multi_stmt")

        if engine == "sqlite":
            return self._query_sqlite(conn, sql, body.limit, started)
        if engine == "mysql":
            return self._query_mysql(conn, sql, body.limit, started)
        if engine == "postgresql":
            return self._query_pg(conn, sql, body.limit, started, auto_limit=auto_limit)
        raise AppException(f"Unsupported engine: {engine}", code="db_engine_unsupported")

    def _query_sqlite(self, conn: dict[str, Any], sql: str, limit: int, started: float) -> DbQueryResponse:
        path = Path(str(conn["path"]))
        db = sqlite3.connect(str(path))
        db.row_factory = sqlite3.Row
        try:
            cur = db.execute(sql)
            if cur.description:
                cols = [d[0] for d in cur.description]
                raw_rows = cur.fetchmany(limit + 1)
                truncated = len(raw_rows) > limit
                rows = [
                    {c: _jsonable(r[c]) for c in cols}
                    for r in raw_rows[:limit]
                ]
                return DbQueryResponse(
                    engine="sqlite",
                    columns=cols,
                    rows=rows,
                    row_count=len(rows),
                    truncated=truncated,
                    duration_ms=(time.perf_counter() - started) * 1000,
                )
            db.commit()
            return DbQueryResponse(
                engine="sqlite",
                affected_rows=cur.rowcount if cur.rowcount >= 0 else None,
                message="OK",
                duration_ms=(time.perf_counter() - started) * 1000,
            )
        except sqlite3.Error as exc:
            raise AppException(str(exc), code="db_sqlite_query") from exc
        finally:
            db.close()

    def _query_mysql(self, conn: dict[str, Any], sql: str, limit: int, started: float) -> DbQueryResponse:
        link = self._mysql_connect(conn)
        try:
            with link.cursor() as cur:
                cur.execute(sql)
                if cur.description:
                    cols = [d[0] for d in cur.description]
                    raw = cur.fetchmany(limit + 1)
                    truncated = len(raw) > limit
                    rows = [
                        {cols[i]: _jsonable(row[i]) for i in range(len(cols))}
                        for row in raw[:limit]
                    ]
                    return DbQueryResponse(
                        engine="mysql",
                        columns=cols,
                        rows=rows,
                        row_count=len(rows),
                        truncated=truncated,
                        duration_ms=(time.perf_counter() - started) * 1000,
                    )
                link.commit()
                return DbQueryResponse(
                    engine="mysql",
                    affected_rows=cur.rowcount,
                    message="OK",
                    duration_ms=(time.perf_counter() - started) * 1000,
                )
        except pymysql.MySQLError as exc:
            raise AppException(str(exc), code="db_mysql_query") from exc
        finally:
            link.close()

    def _query_pg(
        self,
        conn: dict[str, Any],
        sql: str,
        limit: int,
        started: float,
        *,
        auto_limit: bool = True,
    ) -> DbQueryResponse:
        # Prefer JSON output via psql for both system and user connections
        is_select = bool(re.match(r"^\s*(WITH|SELECT)\b", sql, re.I))
        if is_select:
            inner = sql.rstrip().rstrip(";")
            # Never append a second LIMIT when the operator (or preview helper)
            # already provided one — that produces invalid SQL like
            # "... LIMIT 100 OFFSET 0 LIMIT 101".
            has_limit = bool(re.search(r"\bLIMIT\b", inner, re.I))
            if auto_limit and not has_limit:
                inner = f"{inner}\nLIMIT {limit + 1}"
            wrapped = f"SELECT COALESCE(json_agg(t), '[]'::json) FROM ({inner}) t"
            code, out, err = self._psql(conn, wrapped)
            duration = (time.perf_counter() - started) * 1000
            if code != 0:
                raise AppException(err or "PostgreSQL query failed", code="db_pg_query")
            try:
                data = json.loads(out.strip() or "[]")
            except json.JSONDecodeError:
                data = []
            if not isinstance(data, list):
                data = []
            truncated = len(data) > limit
            data = data[:limit]
            cols: list[str] = []
            rows: list[dict[str, Any]] = []
            for doc in data:
                if isinstance(doc, dict):
                    for k in doc:
                        if k not in cols:
                            cols.append(k)
                    rows.append({k: _jsonable(v) for k, v in doc.items()})
            return DbQueryResponse(
                engine="postgresql",
                columns=cols,
                rows=rows,
                row_count=len(rows),
                truncated=truncated,
                duration_ms=duration,
            )
        code, out, err = self._psql(conn, sql)
        duration = (time.perf_counter() - started) * 1000
        if code != 0:
            raise AppException(err or "PostgreSQL exec failed", code="db_pg_query")
        return DbQueryResponse(
            engine="postgresql",
            message=(out or err or "OK").strip()[:4000] or "OK",
            duration_ms=duration,
        )

    # ── Row mutations ──────────────────────────────────────────────────────

    def _insert_row(self, conn: dict[str, Any], body: DbRowMutationRequest) -> DbQueryResponse:
        engine = str(conn["engine"])
        if engine == "mongodb":
            coll = body.collection or body.table
            if not coll or not body.values:
                raise AppException("collection and values required", code="db_mongo_insert")
            doc = json.dumps(body.values)
            js = (
                f"JSON.stringify(db.getSiblingDB('{conn['name']}').getCollection('{coll}')"
                f".insertOne({doc}))"
            )
            return self._run_query(conn, DbQueryRequest(script=js))

        table = body.table
        if not table or not body.values:
            raise AppException("table and values required", code="db_row_insert")
        cols = list(body.values.keys())
        vals = list(body.values.values())
        if engine == "postgresql":
            col_sql = ", ".join(_quote_ident(c, "postgresql") for c in cols)
            val_sql = ", ".join(self._sql_literal(v) for v in vals)
            schema = body.schema_name or "public"
            sql = (
                f'INSERT INTO {_quote_ident(schema, "postgresql")}.'
                f'{_quote_ident(table, "postgresql")} ({col_sql}) VALUES ({val_sql})'
            )
            return self._run_query(conn, DbQueryRequest(sql=sql))
        placeholders = ", ".join(["%s" if engine == "mysql" else "?"] * len(cols))
        col_sql = ", ".join(_quote_ident(c, engine) for c in cols)
        if engine == "mysql":
            sql = f"INSERT INTO {_quote_ident(table, 'mysql')} ({col_sql}) VALUES ({placeholders})"
            return self._exec_mysql_params(conn, sql, vals)
        sql = f"INSERT INTO {_quote_ident(table, 'sqlite')} ({col_sql}) VALUES ({placeholders})"
        return self._exec_sqlite_params(conn, sql, vals)

    def _update_row(self, conn: dict[str, Any], body: DbRowMutationRequest) -> DbQueryResponse:
        engine = str(conn["engine"])
        if engine == "mongodb":
            coll = body.collection or body.table
            if not coll or not body.filter:
                raise AppException("collection and filter required", code="db_mongo_update")
            filt = json.dumps(body.filter)
            vals = json.dumps({"$set": body.values})
            js = (
                f"JSON.stringify(db.getSiblingDB('{conn['name']}').getCollection('{coll}')"
                f".updateMany({filt}, {vals}))"
            )
            return self._run_query(conn, DbQueryRequest(script=js))

        table = body.table
        keys = body.primary_key or body.filter
        if not table or not keys or not body.values:
            raise AppException("table, primary_key/filter, and values required", code="db_row_update")
        set_parts = []
        where_parts = []
        params: list[Any] = []
        for k, v in body.values.items():
            set_parts.append(f"{_quote_ident(k, engine)}=%s" if engine == "mysql" else f"{_quote_ident(k, engine)}=?")
            params.append(v)
        for k, v in keys.items():
            where_parts.append(f"{_quote_ident(k, engine)}=%s" if engine == "mysql" else f"{_quote_ident(k, engine)}=?")
            params.append(v)
        if engine == "postgresql":
            # build via psql with literal escaping
            sets = ", ".join(f"{_quote_ident(k, 'postgresql')}={self._sql_literal(v)}" for k, v in body.values.items())
            wheres = " AND ".join(f"{_quote_ident(k, 'postgresql')}={self._sql_literal(v)}" for k, v in keys.items())
            schema = body.schema_name or "public"
            sql = f'UPDATE {_quote_ident(schema, "postgresql")}.{_quote_ident(table, "postgresql")} SET {sets} WHERE {wheres}'
            return self._run_query(conn, DbQueryRequest(sql=sql))
        if engine == "mysql":
            sql = f"UPDATE {_quote_ident(table, 'mysql')} SET {', '.join(set_parts)} WHERE {' AND '.join(where_parts)}"
            return self._exec_mysql_params(conn, sql, params)
        # sqlite
        sql = f"UPDATE {_quote_ident(table, 'sqlite')} SET {', '.join(set_parts)} WHERE {' AND '.join(where_parts)}"
        return self._exec_sqlite_params(conn, sql, params)

    def _delete_row(self, conn: dict[str, Any], body: DbRowMutationRequest) -> DbQueryResponse:
        engine = str(conn["engine"])
        if engine == "mongodb":
            coll = body.collection or body.table
            keys = body.primary_key or body.filter
            if not coll or not keys:
                raise AppException("collection and filter required", code="db_mongo_delete")
            filt = json.dumps(keys)
            js = (
                f"JSON.stringify(db.getSiblingDB('{conn['name']}').getCollection('{coll}')"
                f".deleteMany({filt}))"
            )
            return self._run_query(conn, DbQueryRequest(script=js))

        table = body.table
        keys = body.primary_key or body.filter
        if not table or not keys:
            raise AppException("table and primary_key/filter required", code="db_row_delete")
        if engine == "postgresql":
            wheres = " AND ".join(f"{_quote_ident(k, 'postgresql')}={self._sql_literal(v)}" for k, v in keys.items())
            schema = body.schema_name or "public"
            sql = f'DELETE FROM {_quote_ident(schema, "postgresql")}.{_quote_ident(table, "postgresql")} WHERE {wheres}'
            return self._run_query(conn, DbQueryRequest(sql=sql))
        where_parts = []
        params: list[Any] = []
        for k, v in keys.items():
            where_parts.append(f"{_quote_ident(k, engine)}=%s" if engine == "mysql" else f"{_quote_ident(k, engine)}=?")
            params.append(v)
        if engine == "mysql":
            sql = f"DELETE FROM {_quote_ident(table, 'mysql')} WHERE {' AND '.join(where_parts)}"
            return self._exec_mysql_params(conn, sql, params)
        sql = f"DELETE FROM {_quote_ident(table, 'sqlite')} WHERE {' AND '.join(where_parts)}"
        return self._exec_sqlite_params(conn, sql, params)

    def _exec_mysql_params(self, conn: dict[str, Any], sql: str, params: list[Any]) -> DbQueryResponse:
        started = time.perf_counter()
        link = self._mysql_connect(conn)
        try:
            with link.cursor() as cur:
                cur.execute(sql, params)
                link.commit()
                return DbQueryResponse(
                    engine="mysql",
                    affected_rows=cur.rowcount,
                    message="OK",
                    duration_ms=(time.perf_counter() - started) * 1000,
                )
        except pymysql.MySQLError as exc:
            raise AppException(str(exc), code="db_mysql_mutate") from exc
        finally:
            link.close()

    def _exec_sqlite_params(self, conn: dict[str, Any], sql: str, params: list[Any]) -> DbQueryResponse:
        started = time.perf_counter()
        db = sqlite3.connect(str(conn["path"]))
        try:
            cur = db.execute(sql, params)
            db.commit()
            return DbQueryResponse(
                engine="sqlite",
                affected_rows=cur.rowcount,
                message="OK",
                duration_ms=(time.perf_counter() - started) * 1000,
            )
        except sqlite3.Error as exc:
            raise AppException(str(exc), code="db_sqlite_mutate") from exc
        finally:
            db.close()

    # ── Drivers ────────────────────────────────────────────────────────────

    def _mysql_connect(self, conn: dict[str, Any]):
        kwargs: dict[str, Any] = {
            "database": conn["name"],
            "charset": "utf8mb4",
            "cursorclass": pymysql.cursors.Cursor,
            "autocommit": False,
        }
        if conn.get("system") or not conn.get("username"):
            # root via unix socket
            kwargs.update({"user": "root", "unix_socket": "/var/run/mysqld/mysqld.sock"})
        else:
            kwargs.update(
                {
                    "host": conn.get("host") or "127.0.0.1",
                    "port": int(conn.get("port") or 3306),
                    "user": conn.get("username"),
                    "password": conn.get("password") or "",
                }
            )
        try:
            return pymysql.connect(**kwargs)
        except pymysql.MySQLError as exc:
            raise AppException(f"MySQL connect failed: {exc}", code="db_mysql_connect") from exc

    def _psql(self, conn: dict[str, Any], sql: str) -> tuple[int, str, str]:
        dbname = str(conn["name"])
        if conn.get("system") or not conn.get("password"):
            cmd = ["sudo", "-u", "postgres", "psql", "-d", dbname, "-tAc", sql]
            return self._run(cmd)
        # URL form
        user = conn.get("username") or "postgres"
        password = conn.get("password") or ""
        host = conn.get("host") or "127.0.0.1"
        port = int(conn.get("port") or 5432)
        env_cmd = [
            "env",
            f"PGPASSWORD={password}",
            "psql",
            "-h",
            host,
            "-p",
            str(port),
            "-U",
            user,
            "-d",
            dbname,
            "-tAc",
            sql,
        ]
        return self._run(env_cmd)

    def _mongo_eval(self, js: str) -> tuple[int, str, str]:
        if Path("/usr/bin/mongosh").exists() or subprocess.getoutput("which mongosh"):
            return self._run(["mongosh", "--quiet", "--eval", js])
        # docker fallback used by DatabaseManagerService
        code, _, _ = self._run(["docker", "inspect", "ifnotus-mongo"])
        if code == 0:
            return self._run(["docker", "exec", "ifnotus-mongo", "mongosh", "--quiet", "--eval", js])
        return 1, "", "mongosh not available — Ensure MongoDB from Databases page first."

    @staticmethod
    def _sql_literal(value: Any) -> str:
        if value is None:
            return "NULL"
        if isinstance(value, bool):
            return "TRUE" if value else "FALSE"
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return str(value)
        s = str(value).replace("'", "''")
        return f"'{s}'"

    @staticmethod
    def _run(cmd: list[str], timeout: int = 60) -> tuple[int, str, str]:
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, check=False)
            return proc.returncode, proc.stdout or "", proc.stderr or ""
        except (OSError, subprocess.SubprocessError) as exc:
            return 1, "", str(exc)

    @staticmethod
    def is_write_sql(sql: str) -> bool:
        return bool(_WRITE_SQL.match(sql or ""))
