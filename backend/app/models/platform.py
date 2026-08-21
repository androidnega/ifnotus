"""IFNOTUS product layer — customers, plans, orders, environments.

Sits beside the existing operator hosting models. Staff users stay on
``users``; paying customers get a ``customers`` profile linked to a user.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.base import TimestampMixin, UUIDPrimaryKeyMixin


class Customer(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Paying IFNOTUS customer (1:1 with a ``users`` row)."""

    __tablename__ = "customers"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), unique=True, nullable=False
    )
    email: Mapped[str] = mapped_column(String(320), unique=True, nullable=False, index=True)
    full_name: Mapped[str] = mapped_column(String(255), nullable=False)
    first_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    last_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(32), nullable=True)
    company: Mapped[str | None] = mapped_column(String(255), nullable=True)
    email_verified: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    phone_verified: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    two_factor_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    onboarding_stage: Mapped[str] = mapped_column(String(32), nullable=False, default="phone_verified")
    onboarding_completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    subscriptions: Mapped[list["Subscription"]] = relationship(back_populates="customer")
    orders: Mapped[list["Order"]] = relationship(back_populates="customer")


class HostingPlan(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Sellable hosting package (Student Starter, Business Pro, …)."""

    __tablename__ = "hosting_plans"

    slug: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    cpu_cores: Mapped[Decimal] = mapped_column(Numeric(8, 3), nullable=False)
    ram_gb: Mapped[Decimal] = mapped_column(Numeric(10, 4), nullable=False)
    storage_gb: Mapped[int] = mapped_column(Integer, nullable=False)
    bandwidth_tb: Mapped[Decimal] = mapped_column(Numeric(8, 2), nullable=False)
    ai_credits: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    price_monthly: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    price_yearly: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), nullable=True)
    currency: Mapped[str] = mapped_column(String(8), nullable=False, default="GHS")
    features: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)


class Order(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Checkout record — pending until Paystack is verified server-side."""

    __tablename__ = "orders"

    customer_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("customers.id", ondelete="CASCADE"), nullable=False, index=True
    )
    plan_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("hosting_plans.id"), nullable=False
    )
    domain_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    domain_extension: Mapped[str | None] = mapped_column(String(32), nullable=True)
    plan_price: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    domain_price: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False, default=0)
    total_price: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(8), nullable=False, default="GHS")
    payment_status: Mapped[str] = mapped_column(String(24), nullable=False, default="pending", index=True)
    provisioning_status: Mapped[str] = mapped_column(String(24), nullable=False, default="pending")
    paystack_reference: Mapped[str | None] = mapped_column(String(128), nullable=True, unique=True)
    invoice_number: Mapped[str | None] = mapped_column(String(40), nullable=True, unique=True, index=True)
    payment_method: Mapped[str] = mapped_column(String(24), nullable=False, default="momo")
    momo_transaction_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    payment_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    payment_amount_received: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), nullable=True)
    payment_confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    payment_confirmed_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    order_kind: Mapped[str] = mapped_column(String(24), nullable=False, default="hosting")
    meta_json: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)

    customer: Mapped[Customer] = relationship(back_populates="orders")
    plan: Mapped[HostingPlan] = relationship()


class Subscription(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Active (or suspended) hosting entitlement for a customer."""

    __tablename__ = "subscriptions"

    customer_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("customers.id", ondelete="CASCADE"), nullable=False, index=True
    )
    order_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("orders.id", ondelete="SET NULL"), nullable=True
    )
    plan_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("hosting_plans.id"), nullable=False
    )
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="active", index=True)
    cpu_allocated: Mapped[Decimal] = mapped_column(Numeric(8, 3), nullable=False)
    ram_allocated: Mapped[Decimal] = mapped_column(Numeric(10, 4), nullable=False)
    storage_allocated: Mapped[int] = mapped_column(Integer, nullable=False)
    bandwidth_used_gb: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False, default=0)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    renewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    auto_renew: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    grace_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_reminder_days: Mapped[int | None] = mapped_column(Integer, nullable=True)

    customer: Mapped[Customer] = relationship(back_populates="subscriptions")
    environments: Mapped[list["CustomerEnvironment"]] = relationship(back_populates="subscription")


class InfrastructureNode(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """A VPS / host that can run customer environments (starts as this box)."""

    __tablename__ = "infrastructure_nodes"

    hostname: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    ip_address: Mapped[str] = mapped_column(String(64), nullable=False)
    cpu_total: Mapped[int] = mapped_column(Integer, nullable=False)
    ram_total_gb: Mapped[int] = mapped_column(Integer, nullable=False)
    storage_total_gb: Mapped[int] = mapped_column(Integer, nullable=False)
    cpu_reserved_pct: Mapped[int] = mapped_column(Integer, nullable=False, default=20)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="healthy")
    last_heartbeat: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)


class CustomerEnvironment(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Provisioned customer space on a node. Wraps existing IFNOTUS hosting."""

    __tablename__ = "customer_environments"

    subscription_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("subscriptions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    customer_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("customers.id", ondelete="CASCADE"), nullable=False, index=True
    )
    node_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("infrastructure_nodes.id", ondelete="SET NULL"), nullable=True
    )
    hosting_domain_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("domains.id", ondelete="SET NULL"), nullable=True
    )
    container_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    isolation_type: Mapped[str] = mapped_column(String(24), nullable=False, default="filesystem")
    container_port: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="provisioning", index=True)
    cpu_limit: Mapped[Decimal] = mapped_column(Numeric(8, 3), nullable=False)
    ram_limit_gb: Mapped[Decimal] = mapped_column(Numeric(10, 4), nullable=False)
    storage_limit_gb: Mapped[int] = mapped_column(Integer, nullable=False)
    ip_address: Mapped[str | None] = mapped_column(String(64), nullable=True)
    domain: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    document_root: Mapped[str | None] = mapped_column(String(512), nullable=True)
    ssl_expiry: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    health_status: Mapped[str] = mapped_column(String(24), nullable=False, default="unknown")
    db_engine: Mapped[str | None] = mapped_column(String(24), nullable=True)
    db_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    db_username: Mapped[str | None] = mapped_column(String(128), nullable=True)
    db_password_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    db_host: Mapped[str | None] = mapped_column(String(255), nullable=True)
    db_port: Mapped[int | None] = mapped_column(Integer, nullable=True)
    db_registry_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    ftp_username: Mapped[str | None] = mapped_column(String(64), nullable=True)
    ftp_password_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    ftp_home: Mapped[str | None] = mapped_column(String(512), nullable=True)
    ftp_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    unix_uid: Mapped[int | None] = mapped_column(Integer, nullable=True)
    unix_gid: Mapped[int | None] = mapped_column(Integer, nullable=True)
    provisioning_step: Mapped[str | None] = mapped_column(String(64), nullable=True)
    ssh_password_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)

    subscription: Mapped[Subscription] = relationship(back_populates="environments")


class SubscriptionEntitlementSnapshot(Base, UUIDPrimaryKeyMixin):
    """Frozen entitlements for a subscription at purchase / plan change."""

    __tablename__ = "subscription_entitlement_snapshots"

    subscription_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("subscriptions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    plan_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    entitlements_json: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class ApplicationInstance(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Managed application runtime attached to a customer environment (PHASE 10)."""

    __tablename__ = "application_instances"

    environment_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("customer_environments.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    runtime: Mapped[str] = mapped_column(String(64), nullable=False)
    framework: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="pending")
    allocated_port: Mapped[int | None] = mapped_column(Integer, nullable=True)
    memory_limit_mb: Mapped[int | None] = mapped_column(Integer, nullable=True)
    worker_limit: Mapped[int | None] = mapped_column(Integer, nullable=True)
    deployment_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    config_json: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)


class EnvironmentDatabase(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Per-environment database registry (PHASE 11). Legacy env.db_* retained for compatibility."""

    __tablename__ = "environment_databases"

    environment_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("customer_environments.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    engine: Mapped[str] = mapped_column(String(24), nullable=False)
    logical_name: Mapped[str] = mapped_column(String(128), nullable=False)
    db_name: Mapped[str] = mapped_column(String(128), nullable=False)
    username: Mapped[str] = mapped_column(String(128), nullable=False)
    credential_secret_ref: Mapped[str | None] = mapped_column(String(255), nullable=True)
    host_ref: Mapped[str | None] = mapped_column(String(255), nullable=True)
    storage_limit_mb: Mapped[int | None] = mapped_column(Integer, nullable=True)
    remote_access_mode: Mapped[str] = mapped_column(String(24), nullable=False, default="off")
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="active")


class CustomerDomain(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Registrar-lifecycle domain (buy / renew). Separate from nginx ``domains``."""

    __tablename__ = "customer_domains"
    __table_args__ = (UniqueConstraint("domain_name", name="uq_customer_domains_name"),)

    customer_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("customers.id", ondelete="CASCADE"), nullable=False, index=True
    )
    environment_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("customer_environments.id", ondelete="SET NULL"), nullable=True
    )
    domain_name: Mapped[str] = mapped_column(String(255), nullable=False)
    registrar: Mapped[str | None] = mapped_column(String(64), nullable=True)
    registration_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    expiry_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    auto_renew: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    dns_records: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    # pending_verification | active | failed | detached (PHASE 12 domain lifecycle)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending_verification")
    ssl_status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    ssl_expiry: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class AiCreditAccount(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Per-customer IFNOTUS AI Engineer wallet."""

    __tablename__ = "ai_credit_accounts"

    customer_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("customers.id", ondelete="CASCADE"), unique=True, nullable=False
    )
    credits_remaining: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_allocated: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    lifetime_used: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class AiOperation(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Metered AI Engineer action with permission level 1–4."""

    __tablename__ = "ai_operations"

    customer_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("customers.id", ondelete="CASCADE"), nullable=False, index=True
    )
    environment_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("customer_environments.id", ondelete="SET NULL"), nullable=True
    )
    operation_type: Mapped[str] = mapped_column(String(24), nullable=False)
    permission_level: Mapped[int] = mapped_column(Integer, nullable=False)
    credits_used: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="pending", index=True)
    request: Mapped[str] = mapped_column(Text, nullable=False)
    result: Mapped[str | None] = mapped_column(Text, nullable=True)
    risk_classification: Mapped[str] = mapped_column(String(16), nullable=False, default="low")
    required_confirmation: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class PlatformJob(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Background job (provision, SSL, backup, notify)."""

    __tablename__ = "platform_jobs"

    job_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    customer_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("customers.id", ondelete="SET NULL"), nullable=True, index=True
    )
    environment_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("customer_environments.id", ondelete="SET NULL"), nullable=True
    )
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="pending", index=True)
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_retries: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    result: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    error_info: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class EnvironmentBackup(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Daily / on-demand backup of a customer environment."""

    __tablename__ = "environment_backups"

    customer_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("customers.id", ondelete="CASCADE"), nullable=False, index=True
    )
    environment_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("customer_environments.id", ondelete="CASCADE"), nullable=False, index=True
    )
    filename: Mapped[str] = mapped_column(String(512), nullable=False)
    file_size: Mapped[int | None] = mapped_column(Integer, nullable=True)
    checksum: Mapped[str | None] = mapped_column(String(128), nullable=True)
    backup_type: Mapped[str] = mapped_column(String(16), nullable=False, default="full")
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="pending")
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class PlatformAuditLog(Base, UUIDPrimaryKeyMixin):
    """Product-level audit (orders, provision, AI) — distinct from staff access logs."""

    __tablename__ = "platform_audit_logs"

    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), index=True
    )
    customer_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("customers.id", ondelete="SET NULL"), nullable=True, index=True
    )
    actor_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    action: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    target_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    target_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    result: Mapped[str] = mapped_column(String(16), nullable=False, default="success")
    metadata_json: Mapped[dict] = mapped_column("metadata", JSONB, nullable=False, default=dict)


class Notification(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Email / SMS / panel notification for a customer."""

    __tablename__ = "notifications"

    customer_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("customers.id", ondelete="CASCADE"), nullable=False, index=True
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    kind: Mapped[str] = mapped_column(String(64), nullable=False, default="info")
    channel: Mapped[str] = mapped_column(String(16), nullable=False, default="panel")
    is_read: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)


class SupportTicket(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Customer support ticket."""

    __tablename__ = "support_tickets"

    customer_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("customers.id", ondelete="CASCADE"), nullable=False, index=True
    )
    environment_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("customer_environments.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    subject: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="open", index=True)
    priority: Mapped[str] = mapped_column(String(16), nullable=False, default="normal")


class SupportTicketMessage(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Message on a support ticket (customer or staff)."""

    __tablename__ = "support_ticket_messages"

    ticket_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("support_tickets.id", ondelete="CASCADE"), nullable=False, index=True
    )
    author_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    author_role: Mapped[str] = mapped_column(String(16), nullable=False, default="customer")
    body: Mapped[str] = mapped_column(Text, nullable=False)
