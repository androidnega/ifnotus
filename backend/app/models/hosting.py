"""Hosting control plane ORM models."""

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.base import TimestampMixin, UUIDPrimaryKeyMixin


class Domain(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Managed domain, subdomain, addon, alias, or redirect entry."""

    __tablename__ = "domains"

    name: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    domain_type: Mapped[str] = mapped_column(String(32), nullable=False, default="primary")
    parent_domain_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("domains.id"), nullable=True
    )
    application_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    document_root: Mapped[str | None] = mapped_column(String(512), nullable=True)
    proxy_port: Mapped[int | None] = mapped_column(nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    dns_points_here: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    nginx_enabled: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    ssl_certificate_path: Mapped[str | None] = mapped_column(String(512), nullable=True)
    force_https: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    redirect_url: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    nginx_site: Mapped[str | None] = mapped_column(String(255), nullable=True)
    subdomain_label: Mapped[str | None] = mapped_column(String(128), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    mailboxes: Mapped[list["Mailbox"]] = relationship(back_populates="domain", cascade="all, delete-orphan")
    aliases: Mapped[list["MailAlias"]] = relationship(back_populates="domain", cascade="all, delete-orphan")
    redirects: Mapped[list["DomainRedirect"]] = relationship(
        back_populates="domain", cascade="all, delete-orphan"
    )
    dns_records: Mapped[list["DomainDnsRecord"]] = relationship(
        back_populates="domain", cascade="all, delete-orphan"
    )


class DomainRedirect(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """HTTP redirect rule for a domain (cPanel Redirects)."""

    __tablename__ = "domain_redirects"

    domain_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("domains.id", ondelete="CASCADE"), nullable=False, index=True
    )
    source_path: Mapped[str] = mapped_column(String(512), nullable=False)
    target_url: Mapped[str] = mapped_column(String(1024), nullable=False)
    status_code: Mapped[int] = mapped_column(nullable=False, default=301)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    domain: Mapped[Domain] = relationship(back_populates="redirects")


class DomainDnsRecord(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Intended DNS records shown to operators (registrar still authoritative)."""

    __tablename__ = "domain_dns_records"

    domain_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("domains.id", ondelete="CASCADE"), nullable=False, index=True
    )
    record_type: Mapped[str] = mapped_column(String(16), nullable=False)
    host: Mapped[str] = mapped_column(String(255), nullable=False, default="@")
    value: Mapped[str] = mapped_column(String(1024), nullable=False)
    ttl: Mapped[int] = mapped_column(nullable=False, default=3600)
    priority: Mapped[int | None] = mapped_column(nullable=True)

    domain: Mapped[Domain] = relationship(back_populates="dns_records")


class Mailbox(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Mailbox account for a domain."""

    __tablename__ = "mailboxes"

    domain_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("domains.id"), nullable=False)
    local_part: Mapped[str] = mapped_column(String(64), nullable=False)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    quota_mb: Mapped[int | None] = mapped_column(nullable=True)
    suspended: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    display_name: Mapped[str | None] = mapped_column(String(128), nullable=True)

    domain: Mapped[Domain] = relationship(back_populates="mailboxes")


class MailAlias(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Mail forwarder / alias."""

    __tablename__ = "mail_aliases"

    domain_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("domains.id"), nullable=False)
    source_local: Mapped[str] = mapped_column(String(64), nullable=False)
    destination: Mapped[str] = mapped_column(String(320), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    domain: Mapped[Domain] = relationship(back_populates="aliases")


class TerminalAuditLog(Base, UUIDPrimaryKeyMixin):
    """Audit trail for terminal command execution."""

    __tablename__ = "terminal_audit_logs"

    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    username: Mapped[str] = mapped_column(String(64), nullable=False)
    command: Mapped[str] = mapped_column(Text, nullable=False)
    exit_code: Mapped[int | None] = mapped_column(nullable=True)
    success: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    output_preview: Mapped[str | None] = mapped_column(Text, nullable=True)
    executed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
