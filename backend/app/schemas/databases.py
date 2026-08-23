"""Database management schemas."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import Field, field_validator

from app.schemas.common import SchemaBase

DatabaseEngine = Literal["sqlite", "mysql", "postgresql", "mongodb"]


class EngineStatusSchema(SchemaBase):
    engine: DatabaseEngine
    available: bool
    running: bool = False
    version: str | None = None
    host: str | None = None
    port: int | None = None
    message: str | None = None
    installable: bool = False


class DatabaseRecordSchema(SchemaBase):
    id: str
    engine: DatabaseEngine
    name: str
    username: str | None = None
    host: str | None = None
    port: int | None = None
    path: str | None = None
    connection_uri: str | None = None
    password_set: bool = False
    password_masked: str | None = None
    notes: str | None = None
    created_at: str | None = None
    managed: bool = True
    size_bytes: int | None = None
    table_count: int | None = None


class LiveDatabaseSchema(SchemaBase):
    engine: DatabaseEngine
    name: str
    owner: str | None = None
    size_bytes: int | None = None
    path: str | None = None
    table_count: int | None = None


class DatabaseCreateRequest(SchemaBase):
    engine: DatabaseEngine
    name: str = Field(min_length=1, max_length=64)
    username: str | None = Field(default=None, max_length=64)
    password: str | None = Field(default=None, max_length=128)
    path: str | None = Field(default=None, max_length=512)
    host: str | None = None
    port: int | None = None
    create_user: bool = True
    # PHASE 38H — only create user@'%' when True (plan remote DB entitlement).
    remote_access: bool = False
    notes: str | None = Field(default=None, max_length=500)
    overwrite: bool = False

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("Database name is required.")
        # Allow letters, numbers, underscore, hyphen; SQLite path handled separately
        import re

        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_-]{0,63}", cleaned):
            raise ValueError(
                "Name must start with a letter/underscore and use only letters, numbers, _ or -."
            )
        return cleaned

    @field_validator("username")
    @classmethod
    def validate_username(cls, value: str | None) -> str | None:
        if value is None or not value.strip():
            return None
        cleaned = value.strip()
        import re

        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_-]{0,63}", cleaned):
            raise ValueError("Username has invalid characters.")
        return cleaned


class DatabaseCreatedResponse(SchemaBase):
    success: bool = True
    message: str
    database: DatabaseRecordSchema
    password: str | None = None
    connection_uri: str | None = None
    details: dict[str, Any] = Field(default_factory=dict)


class DatabaseListResponse(SchemaBase):
    engines: list[EngineStatusSchema] = Field(default_factory=list)
    managed: list[DatabaseRecordSchema] = Field(default_factory=list)
    live: list[LiveDatabaseSchema] = Field(default_factory=list)


class DatabasePasswordResponse(SchemaBase):
    id: str
    password: str
    connection_uri: str | None = None


class DatabaseDropOptions(SchemaBase):
    drop_user: bool = True
    remove_files: bool = True


class DatabaseDropRequest(DatabaseDropOptions):
    confirm_password: str = Field(min_length=1, max_length=128)


class DatabaseAdoptRequest(SchemaBase):
    engine: DatabaseEngine
    name: str = Field(min_length=1, max_length=64)
    username: str | None = Field(default=None, max_length=64)
    password: str | None = Field(default=None, max_length=128)
    path: str | None = Field(default=None, max_length=512)
    host: str | None = None
    port: int | None = None
    notes: str | None = Field(default=None, max_length=500)

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("Database name is required.")
        return cleaned


class DatabaseLiveDropRequest(SchemaBase):
    engine: DatabaseEngine
    name: str = Field(min_length=1, max_length=64)
    confirm_password: str = Field(min_length=1, max_length=128)
    path: str | None = Field(default=None, max_length=512)
    username: str | None = Field(default=None, max_length=64)
    drop_user: bool = False
    remove_files: bool = True

    def as_options(self) -> DatabaseDropOptions:
        return DatabaseDropOptions(drop_user=self.drop_user, remove_files=self.remove_files)


class DbColumnSchema(SchemaBase):
    name: str
    data_type: str | None = None
    nullable: bool | None = None
    primary_key: bool = False
    default: str | None = None


class DbTableSchema(SchemaBase):
    name: str
    schema_name: str | None = None
    columns: list[DbColumnSchema] = Field(default_factory=list)
    approx_rows: int | None = None


class DbSchemaResponse(SchemaBase):
    engine: DatabaseEngine
    database: str
    path: str | None = None
    tables: list[DbTableSchema] = Field(default_factory=list)
    collections: list[str] = Field(default_factory=list)


class DbQueryRequest(SchemaBase):
    sql: str | None = Field(default=None, max_length=200_000)
    script: str | None = Field(default=None, max_length=200_000)
    limit: int = Field(default=200, ge=1, le=2000)


class DbQueryResponse(SchemaBase):
    success: bool = True
    engine: DatabaseEngine
    columns: list[str] = Field(default_factory=list)
    rows: list[dict[str, Any]] = Field(default_factory=list)
    row_count: int = 0
    affected_rows: int | None = None
    message: str | None = None
    truncated: bool = False
    duration_ms: float | None = None


class DbRowsRequest(SchemaBase):
    table: str | None = None
    collection: str | None = None
    schema_name: str | None = None
    limit: int = Field(default=100, ge=1, le=1000)
    offset: int = Field(default=0, ge=0)


class DbRowMutationRequest(SchemaBase):
    table: str | None = None
    collection: str | None = None
    schema_name: str | None = None
    primary_key: dict[str, Any] = Field(default_factory=dict)
    filter: dict[str, Any] = Field(default_factory=dict)
    values: dict[str, Any] = Field(default_factory=dict)


class DatabaseBackupSchema(SchemaBase):
    id: str
    engine: DatabaseEngine
    database: str
    filename: str
    path: str
    size_bytes: int | None = None
    created_at: str | None = None
    kind: str = "manual"


class DatabaseBackupListResponse(SchemaBase):
    backups: list[DatabaseBackupSchema] = Field(default_factory=list)


class DatabaseBackupRequest(SchemaBase):
    engine: DatabaseEngine | None = None
    name: str | None = None
    path: str | None = None


class DatabaseRestoreRequest(SchemaBase):
    confirm_password: str = Field(min_length=1, max_length=128)
    engine: DatabaseEngine
    name: str = Field(min_length=1, max_length=64)
    path: str | None = Field(default=None, max_length=512)
    backup_id: str | None = None
    create_if_missing: bool = True


class DatabaseUnlockRequest(SchemaBase):
    password: str = Field(min_length=1, max_length=128)
